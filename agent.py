import json
import logging
import httpx
from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

SINGLE_TASK_PROMPT = """Ты — ассистент постановки задач в компании MINISO.

ТВОЯ ЗАДАЧА: получить текст от руководителя в любой форме → вернуть чёткую структурированную задачу.

ПРАВИЛА ПЕРЕФОРМУЛИРОВКИ НАЗВАНИЯ:
1. Исправь орфографию и грамматику
2. Сформулируй глаголом действия: "Подготовить...", "Разработать...", "Согласовать...", "Проверить..."
3. Сохрани ТОЛЬКО то что сказал пользователь — не добавляй детали от себя
4. Убери слова-паразиты, сленг, сокращения
5. Максимум 100 символов в названии
6. Если текст непонятен — напиши title: "Уточнение задачи" и description с исходным текстом

ПРИМЕРЫ ПЕРЕФОРМУЛИРОВКИ:
"маркелова сделай отчёт по складу до пятницы" → "Подготовить отчёт по складу"
"надо разобраться с накладными мирада" → "Разобраться с накладными Мирада"
"кострыкин поправь сайт побыстрее" → "Исправить ошибки на сайте"
"луданная сделай красивую презу для борда" → "Подготовить презентацию для борда"

СПИСОК СОТРУДНИКОВ:
- Абдуллах Н. (директор)
- Камалов Н. (заместитель директора)
- Кострыкин И. (IT отдел)
- Яманова Э. (стратегическое развитие)
- Аскарова М. (розница)
- Кульбаева Б. (розница)
- Мырзағали Е. (логистика)
- Елемес Е. (ВЭД)
- Оспанова А. (HR)
- Луданная Л. (маркетинг)
- Маркелова И. (бухгалтерия)
- Мустафина А. (юридический)
- Куниязов З. (безопасность)

РАСПОЗНАВАНИЕ ОТВЕТСТВЕННОГО:
- Имя/фамилия/часть → найди в списке: "Асель"→"Мустафина А.", "Маркелова"→"Маркелова И."
- Отдел → руководитель: "HR"→"Оспанова А.", "логистика"→"Мырзағали Е.", "бухгалтерия"→"Маркелова И."
- Нет совпадений → пустая строка

РАСПОЗНАВАНИЕ СРОКА:
- "до пятницы", "к понедельнику" → вычисли дату от сегодня
- "срочно", "сегодня" → сегодняшняя дата
- "на следующей неделе" → ближайший понедельник
- Конкретная дата "10 июля" → YYYY-MM-DD

ИСПОЛЬЗОВАНИЕ КОНТЕКСТА:
- Если в блоке КОНТЕКСТ КОМПАНИИ есть похожие задачи — используй их стиль формулировки
- Если есть похожий проект — подставь его
- Учись на примерах выполненных задач компании

Верни ТОЛЬКО валидный JSON:
{
  "is_multiple": false,
  "title": "Чёткое название задачи",
  "description": "Подробное описание",
  "assignee": "Имя или пустая строка",
  "department": "Отдел или пустая строка",
  "project": "Проект или пустая строка",
  "deadline": "YYYY-MM-DD или пустая строка"
}

Если в тексте НЕСКОЛЬКО задач (список, нумерация, несколько действий) — верни:
{
  "is_multiple": true,
  "tasks": [
    {
      "title": "Название задачи 1",
      "description": "Описание",
      "assignee": "Ответственный или пустая строка",
      "department": "Отдел или пустая строка", 
      "project": "Проект или пустая строка",
      "deadline": "YYYY-MM-DD или пустая строка"
    }
  ]
}"""


async def _call_claude(messages, system=None, max_tokens=2000):
    try:
        payload = {
            "model": "claude-sonnet-4-6",
            "max_tokens": max_tokens,
            "messages": messages
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json=payload,
            )
            data = response.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Ошибка Claude API: {e}")
        return None


def get_task_context() -> str:
    """Собирает контекст из истории задач для обучения AI."""
    try:
        import sqlite3, os
        db_path = os.environ.get("DB_PATH", "tasks.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Берём последние 30 выполненных задач как образцы
        rows = conn.execute(
            "SELECT title, assignee, project, department FROM tasks "
            "WHERE status='Выполнена' ORDER BY id DESC LIMIT 30"
        ).fetchall()
        # Берём все уникальные проекты
        projects = conn.execute("SELECT name FROM projects").fetchall()
        conn.close()

        context_lines = []
        if projects:
            context_lines.append("ПРОЕКТЫ КОМПАНИИ: " + ", ".join(p["name"] for p in projects))

        if rows:
            context_lines.append("\nПРИМЕРЫ ВЫПОЛНЕННЫХ ЗАДАЧ (используй как образец формулировок):")
            for r in rows:
                context_lines.append(f"- [{r['project']}] {r['title']} → {r['assignee'] or '—'}")

        return "\n".join(context_lines) if context_lines else ""
    except Exception:
        return ""


async def parse_task_with_ai(user_text: str, today: str):
    """Возвращает одну задачу или список задач."""
    # Добавляем контекст из истории задач
    task_context = get_task_context()
    context_block = f"\n\nКОНТЕКСТ КОМПАНИИ:\n{task_context}" if task_context else ""

    raw = await _call_claude(
        messages=[{
            "role": "user",
            "content": f"Сегодня {today}.{context_block}\n\nОбработай текст и верни JSON:\n\n{user_text}"
        }],
        system=SINGLE_TASK_PROMPT,
        max_tokens=2000,
    )
    if not raw:
        return None
    try:
        raw = raw.replace("```json", "").replace("```", "").strip()
        # Если вернул не JSON а текст об ошибке
        if not raw.startswith("{"):
            return {"is_multiple": False, "title": "Уточнение задачи", "description": user_text,
                    "assignee": "", "department": "", "project": "", "deadline": ""}
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Ошибка парсинга JSON: {e}. Raw: {raw[:200]}")
        return {"is_multiple": False, "title": user_text[:80], "description": user_text,
                "assignee": "", "department": "", "project": "", "deadline": ""}


async def parse_deadline(text: str) -> str:
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    raw = await _call_claude(
        messages=[{
            "role": "user",
            "content": f"Сегодня {today}. Переведи срок '{text}' в формат YYYY-MM-DD. Верни ТОЛЬКО дату."
        }],
        max_tokens=20,
    )
    return raw.strip() if raw else text


async def analyze_project_tasks(project_name: str, rows: list) -> str:
    if not rows or len(rows) < 2:
        return f"В проекте '{project_name}' данных нет."
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    table_text = "\n".join(["\t".join(str(c) for c in row) for row in rows[:50]])
    raw = await _call_claude(
        messages=[{
            "role": "user",
            "content": (
                f"Сегодня {today}. Таблица проекта '{project_name}'.\n"
                f"Найди просроченные задачи. Верни краткий список для Telegram с эмодзи. "
                f"Если нет — напиши '✅ Просроченных задач нет'.\n\nТаблица:\n{table_text}"
            )
        }],
        max_tokens=800,
    )
    return raw or f"Не удалось проанализировать '{project_name}'."


async def generate_overdue_summary(tasks: list) -> str:
    if not tasks:
        return "🎉 Просроченных задач нет!"
    tasks_text = "\n".join(
        f"- [{t['id']}] {t['title']} | {t['assignee']} | {t['deadline']} | {t['project']}"
        for t in tasks
    )
    raw = await _call_claude(
        messages=[{
            "role": "user",
            "content": f"Составь Telegram-уведомление о просроченных задачах (с эмодзи, до 10 строк):\n{tasks_text}"
        }],
        max_tokens=600,
    )
    if raw:
        return raw
    lines = ["⚠️ *Просроченные задачи:*\n"]
    for t in tasks:
        lines.append(f"🔴 [{t['id']}] *{t['title']}*\n   👤 {t['assignee'] or '—'} | 📅 {t['deadline']}")
    return "\n".join(lines)




async def learn_from_task(task_id: int):
    """Запоминает паттерн задачи для будущего использования."""
    # Паттерны хранятся в отдельной таблице task_patterns
    try:
        import sqlite3, os
        db_path = os.environ.get("DB_PATH", "tasks.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Создаём таблицу паттернов если нет
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT,
                assignee TEXT,
                project TEXT,
                department TEXT,
                example_title TEXT,
                used_count INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Получаем задачу
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task and task["title"] and task["assignee"]:
            # Извлекаем ключевые слова из названия
            words = [w.lower() for w in task["title"].split() if len(w) > 4]
            for word in words[:3]:
                existing = conn.execute(
                    "SELECT id, used_count FROM task_patterns WHERE keyword=? AND assignee=?",
                    (word, task["assignee"])
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE task_patterns SET used_count=used_count+1 WHERE id=?",
                        (existing["id"],)
                    )
                else:
                    conn.execute(
                        "INSERT INTO task_patterns (keyword, assignee, project, department, example_title) VALUES (?,?,?,?,?)",
                        (word, task["assignee"], task["project"] or "", task["department"] or "", task["title"])
                    )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка сохранения паттерна: {e}")


def get_smart_suggestions(user_text: str) -> dict:
    """Подбирает подсказки на основе истории паттернов."""
    try:
        import sqlite3, os
        db_path = os.environ.get("DB_PATH", "tasks.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        words = [w.lower() for w in user_text.split() if len(w) > 3]
        best = None
        best_score = 0
        for word in words:
            rows = conn.execute(
                "SELECT * FROM task_patterns WHERE keyword LIKE ? ORDER BY used_count DESC LIMIT 3",
                (f"%{word}%",)
            ).fetchall()
            for r in rows:
                if r["used_count"] > best_score:
                    best_score = r["used_count"]
                    best = dict(r)
        conn.close()
        return best or {}
    except Exception:
        return {}
