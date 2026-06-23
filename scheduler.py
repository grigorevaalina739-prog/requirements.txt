import logging
from aiogram import Bot
from config import NOTIFY_CHAT_ID
from database import get_overdue_tasks
from agent import generate_overdue_summary

logger = logging.getLogger(__name__)


async def check_overdue_tasks(bot: Bot):
    logger.info("Проверка просроченных задач...")
    tasks = get_overdue_tasks()
    if not tasks:
        return
    summary = await generate_overdue_summary(tasks)
    try:
        await bot.send_message(chat_id=NOTIFY_CHAT_ID, text=summary, parse_mode="Markdown")
        logger.info(f"Отправлено уведомление о {len(tasks)} просроченных задачах.")
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
