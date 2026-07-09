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
    TASKS = [
    {
        "assignee": "Мустафина А.",
        "title": "Подготовить письмо в Форум о переносе ярмарки",
        "status": "Выполнена",
        "comment": ""
    },
    {
        "assignee": "Турбина Е.",
        "title": "Распределить ассортимент FIFA и Star Wars по магазинам согласно рейтингу и потенциалу продаж",
        "status": "Открыта",
        "comment": ""
    },
    {
        "assignee": "Мырзагали Е.",
        "title": "Разработать и утвердить процесс контроля сроков годности товаров",
        "status": "Открыта",
        "comment": "совместно с Турбина Е."
    },
    {
        "assignee": "Турбина Е.",
        "title": "Разработать и утвердить процесс контроля сроков годности товаров",
        "status": "Открыта",
        "comment": "совместно с Мырзагали Е."
    },
    {
        "assignee": "Мырзагали Е.",
        "title": "Организовать перестикеровку 13 товаров в связи с требованиями СЭС",
        "status": "Открыта",
        "comment": ""
    },
    {
        "assignee": "Луданная Л.",
        "title": "Разработать шаблоны POSM-материалов для магазинов",
        "status": "Открыта",
        "comment": ""
    },
    {
        "assignee": "Мустафина А.",
        "title": "Подготовить письмо в Москву по вопросу отмены работы магазинов за 2 дня в связи с отсутствием электроснабжения",
        "status": "Открыта",
        "comment": ""
    },
    {
        "title": "Просчитать логику АДС прогнозные АДС по месяцам на 20 СКЮ",
        "assignee": "Турбина Е.",
        "deadline": "",
        "project": "SC MINISO"
    },
    {
        "title": "Сделать прогноз через IA по месяцам по текущим продажам, МДС, дата прихода, сколько в пути",
        "assignee": "Турбина Е.",
        "deadline": "",
        "project": "SC MINISO"
    }
]
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
        # Принудительное удаление дублей — сохраняя выполненную копию, если она есть
        _smart_dedup(conn)
        # Объединяем задачи #6 и #7 — обновляем название #6
        conn.execute(
            "UPDATE tasks SET title=? WHERE id=6",
            ("Передать дизайн и плотность пакета Асель и Алексею; получить прайс на маленькие пакеты Минисо",)
        )
        # Удаляем дубль #19 (оставляем #31 с правильным названием)
        conn.execute("DELETE FROM tasks WHERE id=19")
        # Удаляем неверно загруженные задачи SC MINISO #32-37
        for del_id in [32, 33, 34, 35, 36, 37]:
            conn.execute("DELETE FROM tasks WHERE id=?", (del_id,))
        # Удаляем лишний комментарий из задачи #6
        conn.execute("DELETE FROM task_comments WHERE task_id=6 AND text LIKE '%прайс%'")
        conn.execute("DELETE FROM task_comments WHERE task_id=6 AND author='Система'")

def migrate_bord_to_miniso():
    """Переносит задачи из Борд 16.06.2026 в Board Miniso и удаляет старый проект."""
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET project='Board Miniso' WHERE project='Борд 16.06.2026'")
        conn.execute("DELETE FROM projects WHERE name='Борд 16.06.2026'")


def dedup_tasks():
    """Удаляет дублирующиеся задачи — сохраняет выполненную копию, если она есть,
    иначе самую раннюю по ID."""
    with get_conn() as conn:
        rows = conn.execute("SELECT id, title, assignee, project, status FROM tasks ORDER BY id ASC").fetchall()
        groups = {}
        for row in rows:
            key = (row["title"].strip().lower(), (row["assignee"] or "").strip().lower(), (row["project"] or "").strip().lower())
            groups.setdefault(key, []).append(dict(row))
        to_delete = []
        for items in groups.values():
            if len(items) <= 1:
                continue
            done = [it for it in items if it["status"] == "Выполнена"]
            keep = done[0] if done else items[0]
            for it in items:
                if it["id"] != keep["id"]:
                    to_delete.append(it["id"])
        if to_delete:
            conn.executemany("DELETE FROM tasks WHERE id=?", [(i,) for i in to_delete])
            return len(to_delete)
        return 0

def _smart_dedup(conn):
    """Дедупликация, которая ВСЕГДА сохраняет выполненную копию задачи,
    если среди дублей есть хотя бы одна со статусом 'Выполнена'."""
    rows = conn.execute("SELECT id, title, assignee, project, status FROM tasks").fetchall()
    groups = {}
    for row in rows:
        key = (
            (row["title"] or "").strip().lower(),
            (row["assignee"] or "").strip().lower(),
            (row["project"] or "").strip().lower(),
        )
        groups.setdefault(key, []).append(dict(row))
    to_delete = []
    for items in groups.values():
        if len(items) <= 1:
            continue
        done = [it for it in items if it["status"] == "Выполнена"]
        keep = done[0] if done else min(items, key=lambda it: it["id"])
        for it in items:
            if it["id"] != keep["id"]:
                to_delete.append(it["id"])
    if to_delete:
        conn.executemany("DELETE FROM tasks WHERE id=?", [(i,) for i in to_delete])


def force_dedup():
    """Принудительная дедупликация — запускается при каждом старте.
    Сохраняет выполненную задачу, если среди дублей есть завершённая копия."""
    dedup_tasks()
    with get_conn() as conn:
        _smart_dedup(conn)


def merge_task_assignees():
    """Объединяет задачи с одинаковым названием и проектом — ответственные через запятую.
    Если среди дублей есть выполненная задача, сохраняем статус 'Выполнена'."""
    with get_conn() as conn:
        # Находим группы задач с одинаковым title+project
        rows = conn.execute("""
            SELECT title, project, GROUP_CONCAT(id) as ids, GROUP_CONCAT(assignee) as assignees,
                   GROUP_CONCAT(status, '||') as statuses
            FROM tasks
            WHERE status != 'Архив'
            GROUP BY LOWER(TRIM(title)), LOWER(TRIM(COALESCE(project,'')))
            HAVING COUNT(*) > 1
        """).fetchall()
        for row in rows:
            ids = [int(i) for i in row["ids"].split(",")]
            assignees = [a.strip() for a in row["assignees"].split(",") if a.strip()]
            statuses = row["statuses"].split("||") if row["statuses"] else []
            # Уникальные ответственные
            unique_assignees = list(dict.fromkeys(assignees))
            combined = ", ".join(unique_assignees)
            min_id = min(ids)
            # Если хотя бы одна из объединяемых задач выполнена — сохраняем этот статус
            if "Выполнена" in statuses:
                conn.execute("UPDATE tasks SET assignee=?, status='Выполнена' WHERE id=?", (combined, min_id))
            else:
                conn.execute("UPDATE tasks SET assignee=? WHERE id=?", (combined, min_id))
            # Удаляем остальные
            for dup_id in ids:
                if dup_id != min_id:
                    conn.execute("DELETE FROM tasks WHERE id=?", (dup_id,))





def seed_sc_tasks_v2():
    """Задачи SC MINISO от пользователя."""
    PROJECT = "SC MINISO"
    add_project(PROJECT)
    TASKS = [{"title": "Создать папку в AI Claude — отдел закупа", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Найти топовые расчески, проверить наличие следующего МДС", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Провести глубокий анализ категорий: влажные салфетки, бальзамы для губ, Yupilow, парфюм", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Крем для рук 990 тенге — проверить МДС на наличие", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Крем Fruit Energy 1890 — распределить по магазинам", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Крем для рук Sakura — проверить сроки годности", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Food-категория: расширить ввод в крупных магазинах Алматы и Астаны", "assignee": "Турбина Е.", "deadline": ""}, {"title": "По каждому товару определить тип размещения: блистер, полка, способ крепления товара", "assignee": "Турбина Е.", "deadline": ""}]
    with get_conn() as conn:
        existing = set(row[0] for row in conn.execute(
            "SELECT title FROM tasks WHERE project=?", (PROJECT,)
        ).fetchall())
        for t in TASKS:
            if t["title"] not in existing:
                conn.execute(
                    "INSERT INTO tasks (project, assignee, department, title, deadline, status, comment) VALUES (?,?,?,?,?,?,?)",
                    (PROJECT, t["assignee"], "", t["title"], t["deadline"], "Открыта", "")
                )


def init_project_patterns():
    """Создаёт таблицу паттернов проектов."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                project TEXT NOT NULL,
                weight INTEGER DEFAULT 1,
                UNIQUE(keyword, project)
            )
        """)
        # Базовые паттерны из коробки
        base = [
            ("sc", "SC MINISO"), ("закуп", "SC MINISO"), ("товар", "SC MINISO"),
            ("sku", "SC MINISO"), ("мдс", "SC MINISO"), ("поставщик", "SC MINISO"),
            ("заказ", "SC MINISO"), ("ip", "SC MINISO"), ("sku", "SC MINISO"),
            ("аДС", "SC MINISO"), ("адс", "SC MINISO"), ("прогноз", "SC MINISO"),
            ("борд", "Board Miniso"), ("board", "Board Miniso"), ("posm", "Board Miniso"),
            ("пакет", "Board Miniso"), ("стратегия", "Board Miniso"), ("встреча", "Board Miniso"),
            ("сверка", "Сверка баз"), ("склад", "Сверка баз"), ("мирада", "Сверка баз"),
            ("накладная", "Сверка баз"), ("списание", "Сверка баз"), ("инвентаризация", "Сверка баз"),
        ]
        for kw, proj in base:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO project_patterns (keyword, project, weight) VALUES (?,?,?)",
                    (kw.lower(), proj, 5)
                )
            except Exception:
                pass


def learn_project_from_task(title: str, project: str):
    """Запоминает связь слов из задачи с проектом."""
    if not title or not project:
        return
    words = [w.lower().strip(".,!?:;") for w in title.split() if len(w) > 3]
    with get_conn() as conn:
        for word in words[:8]:  # Берём первые 8 слов
            try:
                conn.execute("""
                    INSERT INTO project_patterns (keyword, project, weight) VALUES (?,?,1)
                    ON CONFLICT(keyword, project) DO UPDATE SET weight = weight + 1
                """, (word, project))
            except Exception:
                pass


def predict_project(title: str) -> str:
    """Предсказывает проект по тексту задачи на основе обученных паттернов."""
    if not title:
        return ""
    words = [w.lower().strip(".,!?:;") for w in title.split() if len(w) > 3]
    if not words:
        return ""
    try:
        with get_conn() as conn:
            scores = {}
            for word in words:
                rows = conn.execute(
                    "SELECT project, weight FROM project_patterns WHERE keyword=? ORDER BY weight DESC",
                    (word,)
                ).fetchall()
                for row in rows:
                    proj = row["project"]
                    scores[proj] = scores.get(proj, 0) + row["weight"]
            if scores:
                return max(scores, key=scores.get)
    except Exception:
        pass
    return ""

def cleanup_users():
    """Удаляет/переименовывает пользователей при запуске."""
    to_delete = ["Аскарова", "Елемес", "Яманова", "Оспанова"]
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
            reminded INTEGER DEFAULT 0,
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
        CREATE TABLE IF NOT EXISTS managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (date('now'))
        );
        """)
    logger.info("База данных инициализирована.")
    # Разовые операции при первом запуске
    try:
        init_project_patterns()
        # Обучаем на всех существующих задачах
        with get_conn() as conn:
            rows = conn.execute("SELECT title, project FROM tasks WHERE project!='' AND title!=''").fetchall()
            for row in rows:
                learn_project_from_task(row["title"], row["project"])
    except Exception as e:
        print(f'init_project_patterns error: {e}')
    try:
        force_dedup()
    except Exception as e:
        print(f"force_dedup error: {e}")
    try:
        merge_task_assignees()
    except Exception as e:
        print(f"merge_task_assignees error: {e}")
    try:
        seed_sc_tasks_v2()
    except Exception as e:
        print(f"seed_sc_tasks_v2 error: {e}")
    try:
        cleanup_users()
    except Exception as e:
        print(f"cleanup_users error: {e}")
    try:
        migrate_bord_to_miniso()
    except Exception as e:
        print(f"migrate error: {e}")
    try:
        seed_bord_16_06()
    except Exception as e:
        print(f"seed_bord error: {e}")
    try:
        fix_board_miniso_tasks()
    except Exception as e:
        print(f"fix_board error: {e}")
    try:
        seed_managers()
    except Exception as e:
        print(f"seed_managers error: {e}")
    # Миграция: поле reminded в meetings (для баз, созданных до этого поля)
    try:
        with get_conn() as conn:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(meetings)").fetchall()]
            if "reminded" not in cols:
                conn.execute("ALTER TABLE meetings ADD COLUMN reminded INTEGER DEFAULT 0")
    except Exception as e:
        print(f"migrate meetings.reminded error: {e}")


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
            "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('Выполнена', 'Архив') AND deadline!='' AND deadline<?",
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
        rows = conn.execute(
            "SELECT * FROM tasks WHERE deadline!='' AND deadline<? ORDER BY deadline",
            (today,)
        ).fetchall()
    # Надёжно отсеиваем выполненные (учитываем пробелы/регистр/варианты слова)
    done_words = ("выполн", "готов", "заверш", "закрыт", "сделан", "архив", "done", "complete")
    result = []
    seen = set()
    for r in rows:
        d = dict(r)
        status_norm = (d.get("status") or "").strip().lower()
        if any(w in status_norm for w in done_words):
            continue
        # Убираем дубли одинаковых задач (один и тот же текст + ответственный)
        key = ((d.get("title") or "").strip().lower(), (d.get("assignee") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(d)
    return result

def clear_tasks_from_sheet(spreadsheet_id: str):
    """Заглушка — не используется."""
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
            # 3. Совпадение по фамилии пользователя в иском имени
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


def get_meeting(meeting_id):
    """Возвращает одну встречу по id."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        return dict(row) if row else None


def get_upcoming_meetings():
    """Встречи, которые ещё не начались и по которым не отправлено напоминание за 15 мин."""
    with get_conn() as conn:
        try:
            rows = conn.execute(
                "SELECT * FROM meetings WHERE COALESCE(reminded,0)=0 AND time_start!='' ORDER BY date, time_start"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


def mark_meeting_reminded(meeting_id):
    """Отмечает, что напоминание за 15 минут по встрече уже отправлено."""
    with get_conn() as conn:
        conn.execute("UPDATE meetings SET reminded=1 WHERE id=?", (meeting_id,))
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
    TASKS = [
    {
        "assignee": "Мустафина А.",
        "title": "Подготовить письмо в Форум о переносе ярмарки",
        "status": "Выполнена",
        "comment": ""
    },
    {
        "assignee": "Турбина Е.",
        "title": "Распределить ассортимент FIFA и Star Wars по магазинам согласно рейтингу и потенциалу продаж",
        "status": "Открыта",
        "comment": ""
    },
    {
        "assignee": "Мырзагали Е.",
        "title": "Разработать и утвердить процесс контроля сроков годности товаров",
        "status": "Открыта",
        "comment": "совместно с Турбина Е."
    },
    {
        "assignee": "Турбина Е.",
        "title": "Разработать и утвердить процесс контроля сроков годности товаров",
        "status": "Открыта",
        "comment": "совместно с Мырзагали Е."
    },
    {
        "assignee": "Мырзагали Е.",
        "title": "Организовать перестикеровку 13 товаров в связи с требованиями СЭС",
        "status": "Открыта",
        "comment": ""
    },
    {
        "assignee": "Луданная Л.",
        "title": "Разработать шаблоны POSM-материалов для магазинов",
        "status": "Открыта",
        "comment": ""
    },
    {
        "assignee": "Мустафина А.",
        "title": "Подготовить письмо в Москву по вопросу отмены работы магазинов за 2 дня в связи с отсутствием электроснабжения",
        "status": "Открыта",
        "comment": ""
    },
    {
        "title": "Просчитать логику АДС прогнозные АДС по месяцам на 20 СКЮ",
        "assignee": "Турбина Е.",
        "deadline": "",
        "project": "SC MINISO"
    },
    {
        "title": "Сделать прогноз через IA по месяцам по текущим продажам, МДС, дата прихода, сколько в пути",
        "assignee": "Турбина Е.",
        "deadline": "",
        "project": "SC MINISO"
    }
]
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
        # Удаляем неверно загруженные задачи SC MINISO #32-37
        for del_id in [32, 33, 34, 35, 36, 37]:
            conn.execute("DELETE FROM tasks WHERE id=?", (del_id,))
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





def seed_sc_tasks_v2():
    """Задачи SC MINISO от пользователя."""
    PROJECT = "SC MINISO"
    add_project(PROJECT)
    TASKS = [{"title": "Создать папку в AI Claude — отдел закупа", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Найти топовые расчески, проверить наличие следующего МДС", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Провести глубокий анализ категорий: влажные салфетки, бальзамы для губ, Yupilow, парфюм", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Крем для рук 990 тенге — проверить МДС на наличие", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Крем Fruit Energy 1890 — распределить по магазинам", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Крем для рук Sakura — проверить сроки годности", "assignee": "Турбина Е.", "deadline": ""}, {"title": "Food-категория: расширить ввод в крупных магазинах Алматы и Астаны", "assignee": "Турбина Е.", "deadline": ""}, {"title": "По каждому товару определить тип размещения: блистер, полка, способ крепления товара", "assignee": "Турбина Е.", "deadline": ""}]
    with get_conn() as conn:
        existing = set(row[0] for row in conn.execute(
            "SELECT title FROM tasks WHERE project=?", (PROJECT,)
        ).fetchall())
        for t in TASKS:
            if t["title"] not in existing:
                conn.execute(
                    "INSERT INTO tasks (project, assignee, department, title, deadline, status, comment) VALUES (?,?,?,?,?,?,?)",
                    (PROJECT, t["assignee"], "", t["title"], t["deadline"], "Открыта", "")
                )


def init_project_patterns():
    """Создаёт таблицу паттернов проектов."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                project TEXT NOT NULL,
                weight INTEGER DEFAULT 1,
                UNIQUE(keyword, project)
            )
        """)
        # Базовые паттерны из коробки
        base = [
            ("sc", "SC MINISO"), ("закуп", "SC MINISO"), ("товар", "SC MINISO"),
            ("sku", "SC MINISO"), ("мдс", "SC MINISO"), ("поставщик", "SC MINISO"),
            ("заказ", "SC MINISO"), ("ip", "SC MINISO"), ("sku", "SC MINISO"),
            ("аДС", "SC MINISO"), ("адс", "SC MINISO"), ("прогноз", "SC MINISO"),
            ("борд", "Board Miniso"), ("board", "Board Miniso"), ("posm", "Board Miniso"),
            ("пакет", "Board Miniso"), ("стратегия", "Board Miniso"), ("встреча", "Board Miniso"),
            ("сверка", "Сверка баз"), ("склад", "Сверка баз"), ("мирада", "Сверка баз"),
            ("накладная", "Сверка баз"), ("списание", "Сверка баз"), ("инвентаризация", "Сверка баз"),
        ]
        for kw, proj in base:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO project_patterns (keyword, project, weight) VALUES (?,?,?)",
                    (kw.lower(), proj, 5)
                )
            except Exception:
                pass


def learn_project_from_task(title: str, project: str):
    """Запоминает связь слов из задачи с проектом."""
    if not title or not project:
        return
    words = [w.lower().strip(".,!?:;") for w in title.split() if len(w) > 3]
    with get_conn() as conn:
        for word in words[:8]:  # Берём первые 8 слов
            try:
                conn.execute("""
                    INSERT INTO project_patterns (keyword, project, weight) VALUES (?,?,1)
                    ON CONFLICT(keyword, project) DO UPDATE SET weight = weight + 1
                """, (word, project))
            except Exception:
                pass


def predict_project(title: str) -> str:
    """Предсказывает проект по тексту задачи на основе обученных паттернов."""
    if not title:
        return ""
    words = [w.lower().strip(".,!?:;") for w in title.split() if len(w) > 3]
    if not words:
        return ""
    try:
        with get_conn() as conn:
            scores = {}
            for word in words:
                rows = conn.execute(
                    "SELECT project, weight FROM project_patterns WHERE keyword=? ORDER BY weight DESC",
                    (word,)
                ).fetchall()
                for row in rows:
                    proj = row["project"]
                    scores[proj] = scores.get(proj, 0) + row["weight"]
            if scores:
                return max(scores, key=scores.get)
    except Exception:
        pass
    return ""

def cleanup_users():
    """Удаляет/переименовывает пользователей при запуске."""
    to_delete = ["Аскарова", "Елемес", "Яманова", "Оспанова"]
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
            reminded INTEGER DEFAULT 0,
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
        CREATE TABLE IF NOT EXISTS managers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT (date('now'))
        );
        """)
    logger.info("База данных инициализирована.")
    # Разовые операции при первом запуске
    try:
        init_project_patterns()
        # Обучаем на всех существующих задачах
        with get_conn() as conn:
            rows = conn.execute("SELECT title, project FROM tasks WHERE project!='' AND title!=''").fetchall()
            for row in rows:
                learn_project_from_task(row["title"], row["project"])
    except Exception as e:
        print(f'init_project_patterns error: {e}')
    try:
        force_dedup()
    except Exception as e:
        print(f"force_dedup error: {e}")
    try:
        merge_task_assignees()
    except Exception as e:
        print(f"merge_task_assignees error: {e}")
    try:
        seed_sc_tasks_v2()
    except Exception as e:
        print(f"seed_sc_tasks_v2 error: {e}")
    try:
        cleanup_users()
    except Exception as e:
        print(f"cleanup_users error: {e}")
    try:
        migrate_bord_to_miniso()
    except Exception as e:
        print(f"migrate error: {e}")
    try:
        seed_bord_16_06()
    except Exception as e:
        print(f"seed_bord error: {e}")
    try:
        fix_board_miniso_tasks()
    except Exception as e:
        print(f"fix_board error: {e}")
    try:
        seed_managers()
    except Exception as e:
        print(f"seed_managers error: {e}")
    # Миграция: поле reminded в meetings (для баз, созданных до этого поля)
    try:
        with get_conn() as conn:
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(meetings)").fetchall()]
            if "reminded" not in cols:
                conn.execute("ALTER TABLE meetings ADD COLUMN reminded INTEGER DEFAULT 0")
    except Exception as e:
        print(f"migrate meetings.reminded error: {e}")


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
        rows = conn.execute(
            "SELECT * FROM tasks WHERE deadline!='' AND deadline<? ORDER BY deadline",
            (today,)
        ).fetchall()
    # Надёжно отсеиваем выполненные (учитываем пробелы/регистр/варианты слова)
    done_words = ("выполн", "готов", "заверш", "закрыт", "сделан", "архив", "done", "complete")
    result = []
    seen = set()
    for r in rows:
        d = dict(r)
        status_norm = (d.get("status") or "").strip().lower()
        if any(w in status_norm for w in done_words):
            continue
        # Убираем дубли одинаковых задач (один и тот же текст + ответственный)
        key = ((d.get("title") or "").strip().lower(), (d.get("assignee") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(d)
    return result

def clear_tasks_from_sheet(spreadsheet_id: str):
    """Заглушка — не используется."""
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


def get_meeting(meeting_id):
    """Возвращает одну встречу по id."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
        return dict(row) if row else None


def get_upcoming_meetings():
    """Встречи, которые ещё не начались и по которым не отправлено напоминание за 15 мин."""
    with get_conn() as conn:
        try:
            rows = conn.execute(
                "SELECT * FROM meetings WHERE COALESCE(reminded,0)=0 AND time_start!='' ORDER BY date, time_start"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


def mark_meeting_reminded(meeting_id):
    """Отмечает, что напоминание за 15 минут по встрече уже отправлено."""
    with get_conn() as conn:
        conn.execute("UPDATE meetings SET reminded=1 WHERE id=?", (meeting_id,))
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


# ─── Управление списком сотрудников (managers) ─────────────────────────────

DEFAULT_MANAGERS = [
    "Абдуллах Н.", "Камалов Н.", "Кострыкин И.", "Кульбаева Б.",
    "Мырзағали Е.", "Луданная Л.", "Маркелова И.", "Мустафина А.",
    "Куниязов З.",
]


def seed_managers():
    """Заполняет таблицу managers начальным списком, если она пустая."""
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM managers").fetchone()
        if row["c"] == 0:
            for name in DEFAULT_MANAGERS:
                conn.execute("INSERT OR IGNORE INTO managers (name) VALUES (?)", (name,))


def get_managers():
    """Возвращает список имён сотрудников (отсортирован по имени)."""
    with get_conn() as conn:
        try:
            rows = conn.execute("SELECT name FROM managers ORDER BY name").fetchall()
            return [r["name"] for r in rows]
        except Exception:
            return list(DEFAULT_MANAGERS)


def add_manager(name: str) -> bool:
    """Добавляет сотрудника. Возвращает True если добавлен, False если уже существует или имя пустое."""
    name = (name or "").strip()
    if not name:
        return False
    with get_conn() as conn:
        try:
            conn.execute("INSERT INTO managers (name) VALUES (?)", (name,))
            return True
        except sqlite3.IntegrityError:
            return False


def delete_manager(name: str) -> bool:
    """Удаляет сотрудника из списка. Возвращает True если удалён."""
    name = (name or "").strip()
    if not name:
        return False
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM managers WHERE name=?", (name,))
        return cur.rowcount > 0
