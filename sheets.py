import json
import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_CREDENTIALS_JSON, SPREADSHEET_ID, SHEET_NAME

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = ["ID", "Ответственное лицо", "Отдел", "Проект", "Задача", "Дата постановки", "Срок исполнения", "Статус", "Комментарии"]
PROJECTS_HEADERS = ["ID", "Название", "SPREADSHEET_ID", "Добавлена"]

_worksheet = None
_projects_sheet = None


def _get_client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _apply_formatting(ws):
    """Применяет форматирование: заголовки жирные, условное форматирование просроченных."""
    try:
        spreadsheet = ws.spreadsheet

        # Жирные заголовки
        ws.format("A1:I1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.8},
            "horizontalAlignment": "CENTER"
        })
        ws.format("A1:I1", {"textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}}})

        # Условное форматирование: если Статус != "Выполнена" и Срок < сегодня → красный
        today = datetime.now().strftime("%Y-%m-%d")
        requests = [{
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 9}],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": f'=AND($H2<>"Выполнена",$G2<>"",$G2<TODAY())'}]
                        },
                        "format": {
                            "backgroundColor": {"red": 1.0, "green": 0.8, "blue": 0.8}
                        }
                    }
                },
                "index": 0
            }
        }]
        spreadsheet.batch_update({"requests": requests})
        logger.info("Форматирование применено.")
    except Exception as e:
        logger.error(f"Ошибка форматирования: {e}")


async def init_sheet():
    global _worksheet, _projects_sheet
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        try:
            _worksheet = spreadsheet.worksheet(SHEET_NAME)
        except gspread.WorksheetNotFound:
            _worksheet = spreadsheet.add_worksheet(SHEET_NAME, rows=1000, cols=10)
            _worksheet.append_row(HEADERS)
            _apply_formatting(_worksheet)
            logger.info(f"Создан лист '{SHEET_NAME}'.")

        try:
            _projects_sheet = spreadsheet.worksheet("Projects")
        except gspread.WorksheetNotFound:
            _projects_sheet = spreadsheet.add_worksheet("Projects", rows=100, cols=5)
            _projects_sheet.append_row(PROJECTS_HEADERS)

        logger.info("Google Sheets инициализирован.")
    except Exception as e:
        logger.error(f"Ошибка инициализации Sheets: {e}")


def _sheet():
    if _worksheet is None:
        raise RuntimeError("Sheets не инициализирован.")
    return _worksheet


def get_all_tasks():
    return _sheet().get_all_records()


def add_task(assignee, department, project, title, deadline, comment=""):
    ws = _sheet()
    task_id = len(ws.get_all_values())
    created_at = datetime.now().strftime("%Y-%m-%d")
    ws.append_row([task_id, assignee, department, project, title, created_at, deadline, "Открыта", comment])
    return task_id


def update_task_status(task_id, status):
    ws = _sheet()
    for i, row in enumerate(ws.get_all_records(), start=2):
        if str(row.get("ID")) == str(task_id):
            ws.update_cell(i, 8, status)
            return True
    return False


def get_overdue_tasks():
    today = datetime.now().date()
    overdue = []
    for task in get_all_tasks():
        if task.get("Статус") in ("Открыта", "В работе"):
            try:
                deadline = datetime.strptime(str(task["Срок исполнения"]), "%Y-%m-%d").date()
                if deadline < today:
                    overdue.append({**task, "_project": task.get("Проект", "Основной")})
            except (ValueError, KeyError):
                pass
    return overdue


def get_all_projects():
    if _projects_sheet is None:
        return []
    return _projects_sheet.get_all_records()


def add_project(name, spreadsheet_id):
    if _projects_sheet is None:
        return False
    projects = get_all_projects()
    project_id = len(projects) + 1
    created_at = datetime.now().strftime("%Y-%m-%d")
    _projects_sheet.append_row([project_id, name, spreadsheet_id, created_at])
    return project_id


def get_overdue_from_project(spreadsheet_id, project_name):
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(spreadsheet_id)
        ws = spreadsheet.get_worksheet(0)
        rows = ws.get_all_values()
        return {"project": project_name, "spreadsheet_id": spreadsheet_id, "rows": rows}
    except Exception as e:
        logger.error(f"Ошибка чтения проекта {project_name}: {e}")
        return None
