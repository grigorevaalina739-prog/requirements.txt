import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web
from config import BOT_TOKEN
from handlers import router
from scheduler import check_overdue_tasks, check_deadline_reminders
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
    
    # Просроченные задачи — каждый день в 9:00
    scheduler.add_job(check_overdue_tasks, trigger="cron", hour=9, minute=0, args=[bot])
    
    # Уведомление за 1 день — каждый день в 10:00
    scheduler.add_job(check_deadline_reminders, trigger="cron", hour=10, minute=0, args=[bot])
    
    # Уведомление в день дедлайна — каждый день в 8:00
    scheduler.add_job(check_deadline_reminders, trigger="cron", hour=8, minute=0, args=[bot])

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
