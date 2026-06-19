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

_client = None
_spreadsheet = None


def _get_client():
    global _client
    if _client is None:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client


def _get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        _spreadsheet = _get_client().open_by_key(SPREADSHEET_ID)
    return _spreadsheet


def _get_or_create_sheet(name):
    """Получить лист по имени или создать новый."""
    ss = _get_spreadsheet()
    try:
        ws = ss.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(name, rows=1000, cols=10)
        ws.append_row(HEADERS)
        ws.format("A1:I1", {"textFormat": {"bold": True}})
        logger.info(f"Создан лист '{name}'.")
    return ws


async def init_sheet():
    try:
        _get_or_create_sheet(SHEET_NAME)
        logger.info("Google Sheets инициализирован.")
    except Exception as e:
        logger.error(f"Ошибка инициализации Sheets: {e}")


def get_project_names():
    """Список всех листов-проектов (кроме служебных)."""
    ss = _get_spreadsheet()
    skip = {"Projects", "Sheet1"}
    return [ws.title for ws in ss.worksheets() if ws.title not in skip]


def add_project_sheet(name):
    """Создать новый лист для проекта."""
    _get_or_create_sheet(name)
    return name


def add_task(assignee, department, project, title, deadline, comment=""):
    """Сохранить задачу на лист нужного проекта."""
    ws = _get_or_create_sheet(project if project else SHEET_NAME)
    records = ws.get_all_values()
    task_id = len(records)  # ID = номер строки
    created_at = datetime.now().strftime("%Y-%m-%d")
    ws.append_row([task_id, assignee, department, project, title, created_at, deadline, "Открыта", comment])
    return task_id


def get_all_tasks(project=None):
    """Получить задачи из листа проекта или всех листов."""
    if project:
        try:
            ws = _get_spreadsheet().worksheet(project)
            return ws.get_all_records()
        except gspread.WorksheetNotFound:
            return []
    # Все проекты
    all_tasks = []
    for name in get_project_names():
        try:
            ws = _get_spreadsheet().worksheet(name)
            for task in ws.get_all_records():
                all_tasks.append({**task, "_sheet": name})
        except Exception:
            pass
    return all_tasks


def update_task_status(task_id, status, project=None):
    sheets_to_check = [project] if project else get_project_names()
    for sheet_name in sheets_to_check:
        try:
            ws = _get_spreadsheet().worksheet(sheet_name)
            for i, row in enumerate(ws.get_all_records(), start=2):
                if str(row.get("ID")) == str(task_id):
                    ws.update_cell(i, 8, status)
                    return True
        except Exception:
            pass
    return False


def get_overdue_tasks():
    today = datetime.now().date()
    overdue = []
    for task in get_all_tasks():
        if task.get("Статус") in ("Открыта", "В работе"):
            try:
                deadline = datetime.strptime(str(task["Срок исполнения"]), "%Y-%m-%d").date()
                if deadline < today:
                    overdue.append(task)
            except (ValueError, KeyError):
                pass
    return overdue


def get_overdue_from_project(spreadsheet_id, project_name):
    try:
        client = _get_client()
        ss = client.open_by_key(spreadsheet_id)
        ws = ss.get_worksheet(0)
        rows = ws.get_all_values()
        return {"project": project_name, "rows": rows}
    except Exception as e:
        logger.error(f"Ошибка чтения {project_name}: {e}")
        return None


def get_all_projects():
    return [{"Название": name} for name in get_project_names()]


def add_project(name, spreadsheet_id=None):
    add_project_sheet(name)
    return name
