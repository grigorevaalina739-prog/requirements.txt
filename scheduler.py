import logging
from datetime import datetime, timedelta
from aiogram import Bot
from config import NOTIFY_CHAT_ID
from database import get_overdue_tasks, get_tasks, get_conn
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


async def check_deadline_reminders(bot: Bot):
    """Отправляет уведомления ответственным за 1 день и за 1 час до дедлайна."""
    logger.info("Проверка дедлайнов для уведомлений...")
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    all_tasks = get_tasks()

    for task in all_tasks:
        if task.get("status") == "Выполнена":
            continue
        assignee = task.get("assignee", "")
        deadline = task.get("deadline", "")
        if not assignee or not deadline:
            continue

        # Ищем ответственного в базе
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
            user = None
            for row in rows:
                if assignee.lower() in row["name"].lower() or row["name"].lower() in assignee.lower():
                    user = dict(row)
                    break

        if not user:
            continue

        telegram_id = user["telegram_id"]
        title = task.get("title", "—")
        task_id = task.get("id")

        # Уведомление за 1 день
        if deadline == tomorrow:
            try:
                await bot.send_message(
                    telegram_id,
                    f"⏰ *Напоминание: завтра дедлайн!*\n\n"
                    f"📌 *Задача #{task_id}:* {title}\n"
                    f"📅 *Срок:* {deadline}\n\n"
                    f"Не забудьте прикрепить файл или написать комментарий о статусе задачи.\n"
                    f"Напишите боту /mytasks чтобы открыть задачу.",
                    parse_mode="Markdown"
                )
                logger.info(f"Отправлено уведомление за 1 день: задача #{task_id} → {assignee}")
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания: {e}")

        # Уведомление за 1 час (дедлайн сегодня)
        if deadline == today:
            try:
                await bot.send_message(
                    telegram_id,
                    f"🚨 *Срочно: сегодня дедлайн!*\n\n"
                    f"📌 *Задача #{task_id}:* {title}\n"
                    f"📅 *Срок:* {deadline}\n\n"
                    f"Пожалуйста, прикрепите файл или напишите комментарий о выполнении.\n"
                    f"Напишите боту /mytasks чтобы открыть задачу.",
                    parse_mode="Markdown"
                )
                logger.info(f"Отправлено уведомление за сегодня: задача #{task_id} → {assignee}")
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания: {e}")
