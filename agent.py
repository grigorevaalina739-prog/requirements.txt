import json
import logging
import httpx
from config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

SINGLE_TASK_PROMPT = """Ты — ассистент управления задачами. Обработай текст и верни структурированную задачу.

СПИСОК СОТРУДНИКОВ (используй для распознавания ответственного):
- Абдуллах Н. (директор)
- Камалов Н. (заместитель директора)
- Кострыкин И. (руководитель IT отдела)
- Яманова Э. (директор департамента по стратегическому развитию)
- Аскарова М. (руководитель отдела розницы)
- Кульбаева Б. (руководитель отдела розницы)
- Мырзағали Е. (руководитель отдела логистики)
- Елемес Е. (руководитель отдела ВЭД)
- Оспанова А. (руководитель HR отдела)
- Луданная Л. (руководитель отдела маркетинга)
- Маркелова И. (заместитель главного бухгалтера)
- Мустафина А. (главный юрист)
- Куниязов З. (руководитель службы безопасности)

ПРАВИЛА РАСПОЗНАВАНИЯ ОТВЕТСТВЕННОГО:
- Если упомянуто имя, фамилия, часть имени или @упоминание — найди совпадение в списке выше
- Примеры: "Асель" → "Мустафина А.", "Маркелова" → "Маркелова И.", "@Кострыкин" → "Кострыкин И.", "HR" → "Оспанова А.", "логистика" → "Мырзағали Е."
- Если отдел упомянут — подставь руководителя этого отдела
- Если совпадения нет — оставь пустую строку

ПРАВИЛА:
1. Исправь орфографические и грамматические ошибки
2. Сформулируй название задачи чётко и профессионально
3. Сохрани исходный смысл
4. Извлеки ответственного, отдел, проект и срок если упомянуты
5. Если отдел понятен из контекста — подставь его
6. Если срок относительный — вычисли дату от сегодня

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


async def parse_task_with_ai(user_text: str, today: str):
    """Возвращает одну задачу или список задач."""
    raw = await _call_claude(
        messages=[{
            "role": "user",
            "content": f"Сегодня {today}. Обработай:\n\n{user_text}"
        }],
        system=SINGLE_TASK_PROMPT,
        max_tokens=2000,
    )
    if not raw:
        return None
    try:
        raw = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
        return None


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

