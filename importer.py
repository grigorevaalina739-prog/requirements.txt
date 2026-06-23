"""
Импорт задач из Google Sheets в SQLite базу данных.
"""
import json
import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_JSON
from database import add_task, add_project, get_conn

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_sheets_client():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def detect_columns(headers: list) -> dict:
    """Определяет какая колонка за что отвечает."""
    mapping = {}
    for i, h in enumerate(headers):
        h_lower = str(h).lower().strip()
        if any(x in h_lower for x in ["задача", "task", "название", "наименование"]):
            mapping["title"] = i
        elif any(x in h_lower for x in ["срок", "дедлайн", "deadline", "дата", "выполнения", "исполнения"]):
            mapping["deadline"] = i
        elif any(x in h_lower for x in ["ответственный", "исполнитель", "assignee", "responsible"]):
            mapping["assignee"] = i
        elif any(x in h_lower for x in ["отдел", "department", "подразделение"]):
            mapping["department"] = i
        elif any(x in h_lower for x in ["проект", "project"]):
            mapping["project"] = i
        elif any(x in h_lower for x in ["статус", "status"]):
            mapping["status"] = i
        elif any(x in h_lower for x in ["комментар", "comment", "примечание"]):
            mapping["comment"] = i
    return mapping


def parse_date(value: str) -> str:
    """Пробует распарсить дату в формат YYYY-MM-DD."""
    if not value or str(value).strip() in ("", "—", "-"):
        return ""
    value = str(value).strip()
    formats = ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%y"]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return value


def import_from_sheet(spreadsheet_id: str, project_name: str, sheet_index: int = 0) -> dict:
    """Импортирует задачи из Google Sheet в базу данных."""
    try:
        client = get_sheets_client()
        ss = client.open_by_key(spreadsheet_id)
        ws = ss.get_worksheet(sheet_index)
        all_rows = ws.get_all_values()

        if not all_rows:
            return {"success": False, "error": "Таблица пустая", "imported": 0}

        # Найти строку с заголовками (первая непустая)
        headers = all_rows[0]
        mapping = detect_columns(headers)

        if "title" not in mapping:
            return {"success": False, "error": "Не найдена колонка с задачами", "imported": 0}

        # Создать проект
        add_project(project_name)

        # Проверить уже импортированные (по source_id)
        imported = 0
        skipped = 0

        with get_conn() as conn:
            existing = set(
                row[0] for row in conn.execute(
                    "SELECT source_id FROM tasks WHERE source_sheet=?", (spreadsheet_id,)
                ).fetchall()
            )

        for row_idx, row in enumerate(all_rows[1:], start=2):
            if not any(row):  # пустая строка
                continue

            title = row[mapping["title"]].strip() if mapping.get("title") is not None and mapping["title"] < len(row) else ""
            if not title:
                continue

            source_id = f"{spreadsheet_id}_{row_idx}"
            if source_id in existing:
                skipped += 1
                continue

            deadline = parse_date(row[mapping["deadline"]]) if mapping.get("deadline") is not None and mapping["deadline"] < len(row) else ""
            assignee = row[mapping["assignee"]].strip() if mapping.get("assignee") is not None and mapping["assignee"] < len(row) else ""
            department = row[mapping["department"]].strip() if mapping.get("department") is not None and mapping["department"] < len(row) else ""
            comment = row[mapping["comment"]].strip() if mapping.get("comment") is not None and mapping["comment"] < len(row) else ""
            status_raw = row[mapping["status"]].strip() if mapping.get("status") is not None and mapping["status"] < len(row) else ""

            # Нормализуем статус
            status = "Открыта"
            if any(x in status_raw.lower() for x in ["выполн", "готов", "done", "complete", "закрыт"]):
                status = "Выполнена"
            elif any(x in status_raw.lower() for x in ["работ", "process", "прогресс", "in progress"]):
                status = "В работе"

            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO tasks 
                    (project, assignee, department, title, deadline, status, comment, source_sheet, source_id)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (project_name, assignee, department, title, deadline, status, comment, spreadsheet_id, source_id)
                )
            imported += 1

        return {"success": True, "imported": imported, "skipped": skipped}

    except Exception as e:
        logger.error(f"Ошибка импорта: {e}")
        return {"success": False, "error": str(e), "imported": 0}
