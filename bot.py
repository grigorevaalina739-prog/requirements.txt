import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN
from handlers import router
from scheduler import check_overdue_tasks
from sheets import init_sheet

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Инициализация Google Sheets
    await init_sheet()

    # Планировщик: проверка просроченных задач каждый день в 09:00
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        check_overdue_tasks,
        trigger="cron",
        hour=9,
        minute=0,
        args=[bot],
        id="overdue_check",
    )
    scheduler.start()
    logger.info("Scheduler started. Overdue check runs every day at 09:00 MSK.")

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
