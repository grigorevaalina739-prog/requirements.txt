from datetime import datetime
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from agent import parse_task_with_ai
from sheets import add_task, get_all_tasks, update_task_status, get_overdue_tasks

logger = logging.getLogger(__name__)
router = Router()


class TaskCreation(StatesGroup):
    waiting_for_text = State()
    confirming = State()


# ─────────────────── /start ───────────────────
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я агент управления задачами.\n\n"
        "Команды:\n"
        "➕ /newtask — создать задачу (AI поможет оформить)\n"
        "📋 /tasks — список всех задач\n"
        "✅ /done <ID> — отметить задачу выполненной\n"
        "⚠️ /overdue — показать просроченные задачи\n"
        "❓ /help — справка"
    )


# ─────────────────── /newtask ───────────────────
@router.message(Command("newtask"))
async def cmd_newtask(message: Message, state: FSMContext):
    await state.set_state(TaskCreation.waiting_for_text)
    await message.answer(
        "📝 Опишите задачу в свободной форме.\n\n"
        "Пример: _Подготовить презентацию для клиента Иванов к пятнице, ответственный — Алексей_\n\n"
        "AI сам разберёт название, дедлайн и ответственного.",
        parse_mode="Markdown"
    )


@router.message(TaskCreation.waiting_for_text)
async def process_task_text(message: Message, state: FSMContext):
    await message.answer("🤖 Анализирую задачу...")
    today = datetime.now().strftime("%Y-%m-%d")
    parsed = await parse_task_with_ai(message.text, today)

    if not parsed:
        await message.answer("❌ Не удалось разобрать задачу. Попробуйте ещё раз или /newtask заново.")
        await state.clear()
        return

    await state.update_data(parsed=parsed)
    await state.set_state(TaskCreation.confirming)

    deadline = parsed.get("deadline", "Не указан")
    text = (
        f"✅ *Задача распознана:*\n\n"
        f"📌 *Название:* {parsed.get('title')}\n"
        f"📝 *Описание:* {parsed.get('description')}\n"
        f"👤 *Ответственный:* {parsed.get('assignee')}\n"
        f"📅 *Дедлайн:* {deadline}\n\n"
        f"Сохранить задачу?"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Сохранить", callback_data="confirm_task"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task"),
        ]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data == "confirm_task", TaskCreation.confirming)
async def confirm_task(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    parsed = data["parsed"]
    task_id = add_task(
        title=parsed.get("title", "Без названия"),
        description=parsed.get("description", ""),
        assignee=parsed.get("assignee", "Не указан"),
        deadline=parsed.get("deadline", "Не указан"),
    )
    await state.clear()
    await callback.message.edit_text(
        f"✅ Задача #{task_id} сохранена в Google Sheets!", parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_task")
async def cancel_task(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Создание задачи отменено.")
    await callback.answer()


# ─────────────────── /tasks ───────────────────
@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    tasks = get_all_tasks()
    if not tasks:
        await message.answer("📋 Задач пока нет. Создайте первую: /newtask")
        return

    lines = ["📋 *Все задачи:*\n"]
    for t in tasks[-20:]:  # последние 20
        status_emoji = {"Открыта": "🔵", "В работе": "🟡", "Выполнена": "🟢"}.get(t.get("Статус", ""), "⚪")
        lines.append(
            f"{status_emoji} [{t['ID']}] *{t['Название']}*\n"
            f"   👤 {t['Ответственный']} | 📅 {t['Дедлайн']} | {t['Статус']}"
        )

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─────────────────── /done ───────────────────
@router.message(Command("done"))
async def cmd_done(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Укажите ID задачи: /done 5")
        return

    task_id = int(parts[1])
    success = update_task_status(task_id, "Выполнена")
    if success:
        await message.answer(f"✅ Задача #{task_id} отмечена как выполненная!")
    else:
        await message.answer(f"❌ Задача #{task_id} не найдена.")


# ─────────────────── /overdue ───────────────────
@router.message(Command("overdue"))
async def cmd_overdue(message: Message):
    tasks = get_overdue_tasks()
    if not tasks:
        await message.answer("🎉 Просроченных задач нет!")
        return

    lines = [f"⚠️ *Просроченные задачи ({len(tasks)}):*\n"]
    for t in tasks:
        lines.append(
            f"🔴 [{t['ID']}] *{t['Название']}*\n"
            f"   👤 {t['Ответственный']} | 📅 {t['Дедлайн']}"
        )
    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─────────────────── /help ───────────────────
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 *Справка:*\n\n"
        "/newtask — описать задачу текстом, AI оформит её\n"
        "/tasks — список задач (последние 20)\n"
        "/done <ID> — отметить задачу выполненной\n"
        "/overdue — просроченные задачи\n\n"
        "Уведомления о просрочке приходят автоматически каждый день в 09:00 МСК.",
        parse_mode="Markdown"
    )
