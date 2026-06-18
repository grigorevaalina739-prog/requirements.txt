import json
import logging
import httpx
from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — ассистент управления задачами. Извлеки из текста структурированную задачу.
Верни ТОЛЬКО JSON без пояснений и без markdown.

Формат:
{
  "title": "Краткое название задачи (до 60 символов)",
  "description": "Подробное описание или комментарий",
  "assignee": "Имя ответственного или пустая строка",
  "department": "Название отдела или пустая строка",
  "project": "Название проекта или пустая строка",
  "deadline": "YYYY-MM-DD или пустая строка"
}

Если дедлайн относительный (через 3 дня, в пятницу) — вычисли от сегодня.
Если что-то не упомянуто — оставь пустую строку.
Отвечай только валидным JSON."""


async def _call_claude(messages, system=None, max_tokens=600):
    try:
        payload = {"model": "claude-sonnet-4-6", "max_tokens": max_tokens, "messages": messages}
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json=payload,
            )
            data = response.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Ошибка Claude API: {e}")
        return None


async def parse_task_with_ai(user_text, today):
    raw = await _call_claude(
        messages=[{"role": "user", "content": f"Сегодня {today}. Создай задачу:\n\n{user_text}"}],
        system=SYSTEM_PROMPT,
        max_tokens=500,
    )
    if not raw:
        return None
    try:
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception:
        return None


async def analyze_project_tasks(project_name, rows):
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
                f"Найди просроченные задачи (дедлайн прошёл) и задачи на сегодня.\n"
                f"Верни краткий список для Telegram с эмодзи. "
                f"Если просроченных нет — напиши '✅ Просроченных задач нет'.\n\n"
                f"Таблица:\n{table_text}"
            )
        }],
        max_tokens=800,
    )
    return raw or f"Не удалось проанализировать '{project_name}'."


async def generate_overdue_summary(tasks):
    if not tasks:
        return "🎉 Просроченных задач нет!"
    tasks_text = "\n".join(
        f"- [{t['ID']}] {t.get('Задача','')} | {t.get('Ответственное лицо','')} | {t.get('Срок исполнения','')} | {t.get('_project','')}"
        for t in tasks
    )
    raw = await _call_claude(
        messages=[{"role": "user", "content": f"Составь Telegram-уведомление о просроченных задачах (с эмодзи, до 10 строк):\n{tasks_text}"}],
        max_tokens=600,
    )
    if raw:
        return raw
    lines = ["⚠️ *Просроченные задачи:*\n"]
    for t in tasks:
        lines.append(f"🔴 [{t['ID']}] *{t.get('Задача','')}*\n   👤 {t.get('Ответственное лицо','—')} | 📅 {t.get('Срок исполнения','—')}")
    return "\n".join(lines)
