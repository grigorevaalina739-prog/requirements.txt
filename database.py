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


def seed_bord_16_06():
    """Разовый импорт задач с Борд 16.06.2026."""
    PROJECT = 'Board Miniso'
    add_project(PROJECT)
    TASKS = [{"assignee": "Мустафина А.", "title": "Подготовить письмо в Форум о переносе ярмарки", "status": "Выполнена", "comment": ""}, {"assignee": "Турбина Е.", "title": "Распределить ассортимент FIFA и Star Wars по магазинам согласно рейтингу и потенциалу продаж", "status": "Открыта", "comment": ""}, {"assignee": "Оспанова А.", "title": "Реструктурировать операционный отдел: Операционный менеджер, Мерчендайзер, 2 супервайзера", "status": "Открыта", "comment": ""}, {"assignee": "Мырзагали Е.", "title": "Разработать и утвердить процесс контроля сроков годности товаров", "status": "Открыта", "comment": "совместно с Турбина Е."}, {"assignee": "Турбина Е.", "title": "Разработать и утвердить процесс контроля сроков годности товаров", "status": "Открыта", "comment": "совместно с Мырзагали Е."}, {"assignee": "Мырзагали Е.", "title": "Организовать перестикеровку 13 товаров в связи с требованиями СЭС", "status": "Открыта", "comment": ""}, {"assignee": "Луданная Л.", "title": "Разработать шаблоны POSM-материалов для магазинов", "status": "Открыта", "comment": ""}, {"assignee": "Мустафина А.", "title": "Подготовить письмо в Москву по вопросу отмены работы магазинов за 2 дня в связи с отсутствием электроснабжения", "status": "Открыта", "comment": ""}]
    with get_conn() as conn:
        existing = set(
            row[0] for row in conn.execute(
                "SELECT title FROM tasks WHERE project=?", (PROJECT,)
            ).fetchall()
        )
        for t in TASKS:
            if t['title'] in existing:
                continue
            conn.execute(
                "INSERT INTO tasks (project, assignee, department, title, deadline, status, comment) VALUES (?,?,?,?,?,?,?)",
                (PROJECT, t['assignee'], '', t['title'], '', t['status'], t['comment'])
            )


def fix_board_miniso_tasks():
    """Ставит дедлайн 30.06.2026 задачам без срока в Board Miniso и удаляет задачи."""
    to_delete = [
        "Рассмотреть снижение стоимости",
        "Вернуться к рассмотрению вопроса перестикеровки",
        "Запустить акцию через бота",
    ]
    with get_conn() as conn:
        for fragment in to_delete:
            conn.execute("DELETE FROM tasks WHERE title LIKE ?", (f"%{fragment}%",))
        conn.execute(
            "UPDATE tasks SET deadline='2026-06-30' WHERE project='Board Miniso' AND (deadline IS NULL OR deadline='' OR deadline='None')"
        )
        # Принудительное удаление дублей через SQL
        conn.execute("""
            DELETE FROM tasks WHERE id NOT IN (
                SELECT MIN(id) FROM tasks
                GROUP BY LOWER(TRIM(title)), LOWER(TRIM(COALESCE(assignee,''))), LOWER(TRIM(COALESCE(project,'')))
            )
        """)
        # Объединяем задачи #6 и #7 — обновляем название #6
        conn.execute(
            "UPDATE tasks SET title=? WHERE id=6",
            ("Передать дизайн и плотность пакета Асель и Алексею; получить прайс на маленькие пакеты Минисо",)
        )
        # Удаляем дубль #19 (оставляем #31 с правильным названием)
        conn.execute("DELETE FROM tasks WHERE id=19")
        # Удаляем лишний комментарий из задачи #6
        conn.execute("DELETE FROM task_comments WHERE task_id=6 AND text LIKE '%прайс%'")
        conn.execute("DELETE FROM task_comments WHERE task_id=6 AND author='Система'")

def migrate_bord_to_miniso():
    """Переносит задачи из Борд 16.06.2026 в Board Miniso и удаляет старый проект."""
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET project='Board Miniso' WHERE project='Борд 16.06.2026'")
        conn.execute("DELETE FROM projects WHERE name='Борд 16.06.2026'")


def dedup_tasks():
    """Удаляет дублирующиеся задачи — оставляет только первую по ID."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id, title, assignee, project FROM tasks ORDER BY id ASC").fetchall()
        seen = set()
        to_delete = []
        for row in rows:
            key = (row["title"].strip().lower(), (row["assignee"] or "").strip().lower(), (row["project"] or "").strip().lower())
            if key in seen:
                to_delete.append(row["id"])
            else:
                seen.add(key)
        if to_delete:
            conn.executemany("DELETE FROM tasks WHERE id=?", [(i,) for i in to_delete])
            return len(to_delete)
        return 0

def force_dedup():
    """Принудительная дедупликация — запускается при каждом старте."""
    dedup_tasks()
    # Удалить конкретные известные дубли
    with get_conn() as conn:
        # Оставить только минимальный ID для каждой комбинации title+assignee+project
        conn.execute("""
            DELETE FROM tasks WHERE id NOT IN (
                SELECT MIN(id) FROM tasks
                GROUP BY LOWER(TRIM(title)), LOWER(TRIM(COALESCE(assignee,''))), LOWER(TRIM(COALESCE(project,'')))
            )
        """)


def merge_task_assignees():
    """Объединяет задачи с одинаковым названием и проектом — ответственные через запятую."""
    with get_conn() as conn:
        # Находим группы задач с одинаковым title+project
        rows = conn.execute("""
            SELECT title, project, GROUP_CONCAT(id) as ids, GROUP_CONCAT(assignee) as assignees
            FROM tasks
            WHERE status != 'Архив'
            GROUP BY LOWER(TRIM(title)), LOWER(TRIM(COALESCE(project,'')))
            HAVING COUNT(*) > 1
        """).fetchall()
        for row in rows:
            ids = [int(i) for i in row["ids"].split(",")]
            assignees = [a.strip() for a in row["assignees"].split(",") if a.strip()]
            # Уникальные ответственные
            unique_assignees = list(dict.fromkeys(assignees))
            combined = ", ".join(unique_assignees)
            min_id = min(ids)
            # Обновляем первую задачу
            conn.execute("UPDATE tasks SET assignee=? WHERE id=?", (combined, min_id))
            # Удаляем остальные
            for dup_id in ids:
                if dup_id != min_id:
                    conn.execute("DELETE FROM tasks WHERE id=?", (dup_id,))

def cleanup_users():
    """Удаляет/переименовывает пользователей при запуске."""
    to_delete = ["Аскарова", "Елемес", "Яманова"]
    with get_conn() as conn:
        for name in to_delete:
            conn.execute("DELETE FROM users WHERE name LIKE ?", (f"%{name}%",))
        # Исправляем ник Лидии
        conn.execute("UPDATE users SET name='Луданная Л.' WHERE name LIKE '%Lidiya%' OR name LIKE '%Лидия%' OR name LIKE '%lidiya%'")

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
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (date('now'))
        );
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            changed_by TEXT DEFAULT 'Дашборд',
            field TEXT DEFAULT 'status',
            old_value TEXT DEFAULT '',
            new_value TEXT DEFAULT '',
            changed_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            project TEXT DEFAULT '',
            date TEXT NOT NULL,
            time_start TEXT DEFAULT '',
            time_end TEXT DEFAULT '',
            participants TEXT DEFAULT '',
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS task_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            author TEXT DEFAULT '',
            text TEXT DEFAULT '',
            file_id TEXT DEFAULT '',
            file_name TEXT DEFAULT '',
            file_type TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );
        """)
    logger.info("База данных инициализирована.")
    # Разовые операции при первом запуске
    force_dedup()
    merge_task_assignees()
    cleanup_users()
    migrate_bord_to_miniso()
    seed_bord_16_06()
    fix_board_miniso_tasks()


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

# Эти функции вызываются из init_db() при старте приложения

def add_task(project, assignee, department, title, deadline, comment="", status="Открыта"):
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (project, assignee, department, title, deadline, comment, status) VALUES (?,?,?,?,?,?,?)",
            (project, assignee, department, title, deadline, comment, status)
        )
        conn.execute("INSERT OR IGNORE INTO projects (name) VALUES (?)", (project,))
        return cur.lastrowid

def get_tasks(project=None, status=None):
    query = "SELECT * FROM tasks WHERE status != 'Архив'"
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

def update_status(task_id, status, changed_by="Дашборд"):
    with get_conn() as conn:
        old = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        old_status = old["status"] if old else ""
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
        conn.execute(
            "INSERT INTO task_history (task_id, changed_by, field, old_value, new_value) VALUES (?,?,?,?,?)",
            (task_id, changed_by, "status", old_status, status)
        )
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

def register_user(telegram_id: int, name: str):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO users (telegram_id, name) VALUES (?,?)",
                (telegram_id, name)
            )
        return True
    except Exception as e:
        logger.error(f"Ошибка регистрации пользователя: {e}")
        return False

def get_user_by_name(name: str):
    """Ищет пользователя по имени — поддерживает форматы:
    'Луданная Л.' -> совпадёт с 'Лидия Луданная', 'Ludannaya' и т.д.
    """
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users").fetchall()
        name_lower = name.strip().lower()
        # Извлекаем фамилию (первое слово) из искомого имени
        search_surname = name_lower.split()[0] if name_lower else ""

        for row in rows:
            row_name = row["name"].lower().strip()
            # 1. Прямое совпадение
            if name_lower in row_name or row_name in name_lower:
                return dict(row)
            # 2. Совпадение по фамилии (первое слово искомого в любом слове пользователя)
            if search_surname and len(search_surname) >= 4:
                for word in row_name.split():
                    if search_surname in word or word in search_surname:
                        return dict(row)
            # 3. Совпадение по фамилии пользователя в искомом имени
            for word in row_name.split():
                if len(word) >= 4 and word in name_lower:
                    return dict(row)
    return None

def get_all_users():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY name").fetchall()]

def add_task_comment(task_id: int, author: str, text: str = "", file_id: str = "", file_name: str = "", file_type: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO task_comments (task_id, author, text, file_id, file_name, file_type) VALUES (?,?,?,?,?,?)",
            (task_id, author, text, file_id, file_name, file_type)
        )
    return True

def get_task_comments(task_id: int):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM task_comments WHERE task_id=? ORDER BY created_at",
            (task_id,)
        ).fetchall()]


def log_task_change(task_id: int, changed_by: str, field: str, old_value: str, new_value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO task_history (task_id, changed_by, field, old_value, new_value) VALUES (?,?,?,?,?)",
            (task_id, changed_by, field, old_value, new_value)
        )
    return True

def get_task_history(task_id: int):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM task_history WHERE task_id=? ORDER BY changed_at DESC",
            (task_id,)
        ).fetchall()]




def add_meeting(title, project, date, time_start, time_end, participants, description):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meetings (title, project, date, time_start, time_end, participants, description) VALUES (?,?,?,?,?,?,?)",
            (title, project, date, time_start, time_end, participants, description)
        )
    return True

def get_meetings(month=None, project=None):
    with get_conn() as conn:
        q = "SELECT * FROM meetings"
        conditions = []
        params = []
        if month:
            conditions.append("date LIKE ?")
            params.append(f"{month}%")
        if project:
            conditions.append("project=?")
            params.append(project)
        if conditions:
            q += " WHERE " + " AND ".join(conditions)
        q += " ORDER BY date, time_start"
        return [dict(r) for r in conn.execute(q, params).fetchall()]

def delete_meeting(meeting_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM meetings WHERE id=?", (meeting_id,))
    return True

def update_meeting(meeting_id, title, project, date, time_start, time_end, participants, description):
    with get_conn() as conn:
        conn.execute(
            "UPDATE meetings SET title=?, project=?, date=?, time_start=?, time_end=?, participants=?, description=? WHERE id=?",
            (title, project, date, time_start, time_end, participants, description, meeting_id)
        )
    return True




def archive_task(task_id: int):
    """Перемещает задачу в архив."""
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET status='Архив' WHERE id=?", (task_id,))
    return True

def get_archived_tasks(project=None):
    """Возвращает архивные задачи."""
    with get_conn() as conn:
        if project:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status='Архив' AND project=? ORDER BY id DESC",
                (project,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status='Архив' ORDER BY project, id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

def restore_task(task_id: int):
    """Восстанавливает задачу из архива."""
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET status='Выполнена' WHERE id=?", (task_id,))
    return True


def delete_task_comment(comment_id: int):
    """Удаляет комментарий/файл по ID."""
    with get_conn() as conn:
        conn.execute("DELETE FROM task_comments WHERE id=?", (comment_id,))
    return True
