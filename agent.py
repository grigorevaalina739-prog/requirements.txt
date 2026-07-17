"""
Умный AI агент на основе Claude API для анализа и создания задач.
Понимает контекст, парсит задачи, предлагает проекты и сотрудников.
"""

import json
import logging
from database import get_managers, get_projects

logger = logging.getLogger(__name__)

# Пытаемся импортировать anthropic, если не установлен - используем fallback
try:
    import anthropic
    client = anthropic.Anthropic()
    ANTHROPIC_AVAILABLE = True
except ImportError:
    logger.warning("anthropic не установлен - используется режим fallback")
    ANTHROPIC_AVAILABLE = False
    client = None

SYSTEM_PROMPT = """Ты — умный AI ассистент для системы управления задачами MINISO.

Ты помогаешь анализировать текст пользователя и извлекать информацию о задачах.

ВАШИ ВОЗМОЖНОСТИ:
1. Понимание на любом языке (русский, английский, казахский и т.д.)
2. Парсинг одной или нескольких задач из текста
3. Автоматическое определение приоритета
4. Рекомендации по проектам и сотрудникам
5. Уточняющие вопросы если информации недостаточно

ФОРМАТ ОТВЕТА (ВСЕГДА JSON):
{
  "understood": true/false,
  "tasks": [
    {
      "title": "Название задачи",
      "description": "Описание (если есть)",
      "project": "Имя проекта или null",
      "assignee": "ФИ сотрудника или массив если несколько",
      "deadline": "YYYY-MM-DD или null",
      "priority": "high/medium/low",
      "confidence": 0.95
    }
  ],
  "clarifications": "Уточняющие вопросы если нужны",
  "suggestions": {
    "projects": ["Рекомендуемые проекты"],
    "people": ["Рекомендуемые люди"]
  }
}

ПРАВИЛА:
- Всегда отвечай JSON (без markdown, без пояснений)
- Если текст на другом языке - переводи в контексте и анализируй
- Задачи должны быть ясными и конкретными
- Приоритет: high если срочное/критичное, low если может подождать
- Не выдумывай имена сотрудников - рекомендуй из списка
- Confidence от 0 до 1 - насколько уверен в парсинге
"""

async def parse_task_with_ai(user_text: str, today_date: str = None) -> dict:
    """
    Парсит текст пользователя и возвращает задачу для создания.
    Совместима с dashboard.py маршрутом /agent/parse
    
    Args:
        user_text: Текст от пользователя
        today_date: Текущая дата (YYYY-MM-DD)
    
    Returns:
        dict: Задача для создания или None
    """
    
    if not ANTHROPIC_AVAILABLE or not client:
        logger.warning("Claude API недоступен - возвращаю None")
        return None
    
    managers = get_managers()
    projects = [p["name"] for p in get_projects()]
    
    context = f"""
ДОСТУПНЫЕ СОТРУДНИКИ: {', '.join(managers)}
ДОСТУПНЫЕ ПРОЕКТЫ: {', '.join(projects)}
СЕГОДНЯ: {today_date or ''}

Пожалуйста, парсь ПЕРВУЮ задачу из текста пользователя.
Используй точные имена из списков.
Если проект не указан - верни null.
"""
    
    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT + "\n\n" + context,
            messages=[
                {
                    "role": "user",
                    "content": user_text
                }
            ]
        )
        
        response_text = message.content[0].text
        result = json.loads(response_text)
        
        if result.get("understood") and result.get("tasks"):
            task = result["tasks"][0]  # Берём первую задачу
            return {
                "title": task.get("title", ""),
                "description": task.get("description", ""),
                "project": task.get("project"),
                "assignee": task.get("assignee", ""),
                "deadline": task.get("deadline"),
                "priority": task.get("priority", "medium"),
                "multi": len(result.get("tasks", [])) > 1
            }
        else:
            return None
            
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return None


async def analyze_task_text(user_text: str, context_managers: list = None, context_projects: list = None) -> dict:
    """
    Анализирует текст пользователя и извлекает информацию о задачах.
    
    Args:
        user_text: Текст от пользователя
        context_managers: Список доступных сотрудников (для контекста)
        context_projects: Список доступных проектов (для контекста)
    
    Returns:
        dict: Распарсенные задачи и рекомендации
    """
    
    if not context_managers:
        context_managers = [m for m in get_managers()]
    if not context_projects:
        context_projects = [p["name"] for p in get_projects()]
    
    # Формирую контекст с доступными вариантами
    context = f"""
ДОСТУПНЫЕ СОТРУДНИКИ: {', '.join(context_managers)}
ДОСТУПНЫЕ ПРОЕКТЫ: {', '.join(context_projects)}

Пожалуйста, анализируй задачи в контексте этих данных.
Используй точные имена из списка сотрудников.
"""
    
    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT + "\n\n" + context,
            messages=[
                {
                    "role": "user",
                    "content": user_text
                }
            ]
        )
        
        response_text = message.content[0].text
        
        # Парсим JSON из ответа
        try:
            result = json.loads(response_text)
            return result
        except json.JSONDecodeError:
            logger.error(f"Не удалось распарсить JSON: {response_text}")
            return {
                "understood": False,
                "tasks": [],
                "clarifications": "Ошибка при обработке. Пожалуйста, переформулируйте запрос.",
                "suggestions": {"projects": [], "people": []}
            }
            
    except Exception as e:
        logger.error(f"Ошибка Claude API: {e}")
        return {
            "understood": False,
            "tasks": [],
            "clarifications": f"Ошибка API: {str(e)}",
            "suggestions": {"projects": [], "people": []}
        }


async def improve_task(task_title: str, context: str = "") -> dict:
    """
    Улучшает описание задачи, делает его более ясным.
    
    Args:
        task_title: Текущее название/описание задачи
        context: Дополнительный контекст
    
    Returns:
        dict: Улучшенное название и описание
    """
    
    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            system="""Ты помогаешь улучшать описания задач. 
            Делай их более ясными, конкретными и понятными.
            Ответь JSON: {"title": "...", "description": "..."}""",
            messages=[
                {
                    "role": "user",
                    "content": f"Улучши эту задачу: {task_title}\nКонтекст: {context}"
                }
            ]
        )
        
        response_text = message.content[0].text
        result = json.loads(response_text)
        return result
        
    except Exception as e:
        logger.error(f"Ошибка улучшения задачи: {e}")
        return {"title": task_title, "description": ""}


async def generate_task_suggestions(project: str = "", assignee: str = "") -> list:
    """
    Генерирует предложения по задачам на основе проекта/сотрудника.
    
    Args:
        project: Имя проекта
        assignee: Имя сотрудника
    
    Returns:
        list: Список предложений по задачам
    """
    
    try:
        prompt = f"Предложи 3-5 типичных задач для "
        if project:
            prompt += f"проекта '{project}' "
        if assignee:
            prompt += f"для {assignee}"
        
        prompt += ".\nОтвети JSON массивом: [{'title': '...', 'description': '...'}, ...]"
        
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system="Ты генерируешь реалистичные задачи для управления проектами.",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        
        response_text = message.content[0].text
        suggestions = json.loads(response_text)
        return suggestions if isinstance(suggestions, list) else []
        
    except Exception as e:
        logger.error(f"Ошибка генерации предложений: {e}")
        return []


async def analyze_task_description(description: str) -> dict:
    """
    Анализирует описание задачи и извлекает ключевую информацию.
    
    Args:
        description: Описание задачи
    
    Returns:
        dict: Анализ с ключевыми точками
    """
    
    try:
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=512,
            system="""Анализируй описание задачи и извлеки:
            - Основная цель
            - Критерии завершения
            - Потенциальные риски
            - Зависимости
            Ответь JSON.""",
            messages=[
                {
                    "role": "user",
                    "content": f"Проанализируй задачу: {description}"
                }
            ]
        )
        
        response_text = message.content[0].text
        analysis = json.loads(response_text)
        return analysis
        
    except Exception as e:
        logger.error(f"Ошибка анализа: {e}")
        return {}
