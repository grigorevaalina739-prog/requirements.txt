import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web
from config import BOT_TOKEN
from handlers import router
from scheduler import check_overdue_tasks, check_deadline_reminders, auto_mark_overdue, escalate_overdue, weekly_digest, auto_mark_overdue, escalate_overdue, weekly_digest
from database import init_db
from dashboard import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    # Инициализация БД
    init_db()

    # Telegram бот
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Планировщик
    scheduler = AsyncIOScheduler(timezone="Asia/Almaty")
    
    # Напоминание за 1 день — каждый день в 10:00
    scheduler.add_job(check_deadline_reminders, trigger="cron", hour=10, minute=0, args=[bot])

    # Сводка просроченных в общий чат — каждый день в 9:00
    scheduler.add_job(check_overdue_tasks, trigger="cron", hour=9, minute=0, args=[bot])

    # Эскалация руководителю если просрочено 3+ дней — каждый день в 9:05
    scheduler.add_job(escalate_overdue, trigger="cron", hour=9, minute=5, args=[bot])

    # Еженедельный дайджест каждому сотруднику — каждый понедельник в 9:00
    scheduler.add_job(weekly_digest, trigger="cron", day_of_week="mon", hour=9, minute=0, args=[bot])

    scheduler.start()

    # Веб-дашборд
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logger.info("Дашборд запущен на порту 8080")

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())

