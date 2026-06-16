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

# Заголовки таблицы
HEADERS = ["ID", "Название", "Описание", "Ответственный", "Дедлайн", "Статус", "Создана"]

_worksheet = None


def _get_client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


async def init_sheet():
    global _worksheet
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        try:
            _worksheet = spreadsheet.worksheet(SHEET_NAME)
        except gspread.WorksheetNotFound:
            _worksheet = spreadsheet.add_worksheet(SHEET_NAME, rows=1000, cols=10)
            _worksheet.append_row(HEADERS)
            logger.info(f"Создан лист '{SHEET_NAME}' с заголовками.")
        logger.info("Google Sheets инициализирован.")
    except Exception as e:
        logger.error(f"Ошибка инициализации Sheets: {e}")


def _sheet():
    if _worksheet is None:
        raise RuntimeError("Sheets не инициализирован. Вызовите init_sheet().")
    return _worksheet


def get_all_tasks() -> list[dict]:
    ws = _sheet()
    records = ws.get_all_records()
    return records


def add_task(title: str, description: str, assignee: str, deadline: str) -> int:
    ws = _sheet()
    all_rows = ws.get_all_values()
    task_id = len(all_rows)  # ID = номер строки (без заголовка = реальный порядок)
    created_at = datetime.now().strftime("%Y-%m-%d")
    ws.append_row([task_id, title, description, assignee, deadline, "Открыта", created_at])
    return task_id


def update_task_status(task_id: int, status: str) -> bool:
    ws = _sheet()
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):  # строки с 2-й (1-я — заголовок)
        if str(row.get("ID")) == str(task_id):
            # Колонка "Статус" — 6-я
            ws.update_cell(i, 6, status)
            return True
    return False


def get_overdue_tasks() -> list[dict]:
    today = datetime.now().date()
    overdue = []
    for task in get_all_tasks():
        if task.get("Статус") in ("Открыта", "В работе"):
            try:
                deadline = datetime.strptime(str(task["Дедлайн"]), "%Y-%m-%d").date()
                if deadline < today:
                    overdue.append(task)
            except (ValueError, KeyError):
                pass
    return overdue
