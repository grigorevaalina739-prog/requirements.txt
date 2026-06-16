"""
AI-агент на базе Claude — помогает формировать задачи из свободного текста.
"""
import json
import logging
import httpx

from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — ассистент управления задачами. Пользователь описывает задачу в свободной форме.
Твоя цель — извлечь из текста структурированную задачу и вернуть ТОЛЬКО JSON без пояснений.

Формат ответа (строго JSON):
{
  "title": "Краткое название задачи (до 60 символов)",
  "description": "Подробное описание",
  "assignee": "Имя ответственного или 'Не указан'",
  "deadline": "YYYY-MM-DD или 'Не указан'"
}

Если дедлайн указан относительно (например 'через 3 дня'), вычисли дату от сегодня.
Если что-то не указано — используй 'Не указан'.
Отвечай только валидным JSON, без markdown, без пояснений."""


async def parse_task_with_ai(user_text: str, today: str) -> dict | None:
    """Отправляет текст в Claude и получает структурированную задачу."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 500,
                    "system": SYSTEM_PROMPT,
                    "messages": [
                        {
                            "role": "user",
                            "content": f"Сегодня {today}. Создай задачу из текста:\n\n{user_text}",
                        }
                    ],
                },
            )
            data = response.json()
            raw = data["content"][0]["text"].strip()
            # Убираем возможные markdown-обёртки
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
    except Exception as e:
        logger.error(f"Ошибка AI агента: {e}")
        return None


async def generate_overdue_summary(tasks: list[dict]) -> str:
    """Генерирует человекочитаемый отчёт о просроченных задачах."""
    if not tasks:
        return "Просроченных задач нет. 🎉"

    tasks_text = "\n".join(
        f"- [{t['ID']}] {t['Название']} | Ответственный: {t['Ответственный']} | Дедлайн: {t['Дедлайн']}"
        for t in tasks
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 600,
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Составь краткое и чёткое Telegram-уведомление о просроченных задачах.\n"
                                f"Используй эмодзи. Не более 10 строк. Список задач:\n{tasks_text}"
                            ),
                        }
                    ],
                },
            )
            data = response.json()
            return data["content"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Ошибка генерации отчёта: {e}")
        # Fallback — простой текст
        lines = ["⚠️ *Просроченные задачи:*\n"]
        for t in tasks:
            lines.append(f"🔴 [{t['ID']}] *{t['Название']}*\n   👤 {t['Ответственный']} | 📅 {t['Дедлайн']}\n")
        return "\n".join(lines)
