import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
DB_PATH = Path("/data/tasks.db")

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (date('now'))
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            assignee TEXT DEFAULT '',
            department TEXT DEFAULT '',
            title TEXT NOT NULL,
            created_at TEXT DEFAULT (date('now')),
            deadline TEXT DEFAULT '',
            status TEXT DEFAULT 'Открыта',
            comment TEXT DEFAULT '',
            source_sheet TEXT DEFAULT '',
            source_id TEXT DEFAULT ''
        );
        """)
    logger.info("База данных инициализирована.")

def get_projects():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY name").fetchall()]

def add_project(name):
    try:
        with get_conn() as conn:
            conn.execute("INSERT OR IGNORE INTO projects (name) VALUES (?)", (name,))
        return True
    except Exception as e:
        logger.error(f"Ошибка добавления проекта: {e}")
        return False

def add_task(project, assignee, department, title, deadline, comment="", status="Открыта"):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (project, assignee, department, title, deadline, comment, status) VALUES (?,?,?,?,?,?,?)",
            (project, assignee, department, title, deadline, comment, status)
        )
        conn.execute("INSERT OR IGNORE INTO projects (name) VALUES (?)", (project,))
        return cur.lastrowid

def get_tasks(project=None, status=None):
    query = "SELECT * FROM tasks WHERE 1=1"
    params = []
    if project:
        query += " AND project = ?"
        params.append(project)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]

def update_status(task_id, status):
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    return True

def get_stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        open_ = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='Открыта'").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='Выполнена'").fetchone()[0]
        today = datetime.now().strftime("%Y-%m-%d")
        overdue = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status!='Выполнена' AND deadline!='' AND deadline<?",
            (today,)
        ).fetchone()[0]
        by_project = conn.execute(
            "SELECT project, COUNT(*) as cnt FROM tasks GROUP BY project"
        ).fetchall()
    return {
        "total": total, "open": open_, "done": done, "overdue": overdue,
        "by_project": [dict(r) for r in by_project]
    }

def get_overdue_tasks():
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM tasks WHERE status!='Выполнена' AND deadline!='' AND deadline<? ORDER BY deadline",
            (today,)
        ).fetchall()]

def clear_tasks_from_sheet(spreadsheet_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE source_sheet=?", (spreadsheet_id,))
    return True
