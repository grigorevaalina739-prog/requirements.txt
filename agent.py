"""
Stub AI агента - заглушка для совместимости.
Полный AI агент будет добавлен после переезда на платный хостинг.
"""

import json
import logging
from database import get_managers, get_projects

logger = logging.getLogger(__name__)


async def parse_task_with_ai(user_text: str, today_date: str = None) -> dict:
    """
    Stub функция - возвращает None.
    Реальный AI будет добавлен позже.
    """
    return None


async def analyze_task_text(user_text: str, context_managers: list = None, context_projects: list = None) -> dict:
    """Stub функция"""
    return {
        "understood": False,
        "tasks": [],
        "clarifications": "AI агент отключен",
        "suggestions": {"projects": [], "people": []}
    }
