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
            conn.execute("INSERT OR IGNORE INTO
