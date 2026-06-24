from datetime import datetime
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from agent import parse_task_with_ai, parse_deadline, analyze_project_tasks
from database import (add_task, get_tasks, update_status, get_projects,
                      add_project, get_overdue_tasks, get_stats,
                      register_user, get_user_by_name, get_conn,
                      add_task_comment, get_task_comments)

logger = logging.getLogger(__name__)
router = Router()


class TaskCreation(StatesGroup):
    waiting_for_text = State()
    editing_field = State()
    choosing_project = State()
    confirming = State()
    confirming_multiple = State()
    correcting_field_multiple = State()
    editing_one_of_multiple = State()
    editing_one_field = State()


class ProjectAdding(StatesGroup):
    waiting_for_name = State()


class ImportAdding(StatesGroup):
    waiting_for_url = State()


class TaskEditing(StatesGroup):
    choosing_field = State()
    editing_field = State()
    choosing_project = State()


class TaskCommenting(StatesGroup):
    waiting_for_comment = State()
    waiting_for_file = State()


FIELD_LABELS = {
    "title": "Задача",
    "assignee": "Ответственный",
    "department": "Отдел",
    "project": "Проект",
    "deadline": "Срок",
    "comment": "Комментарий",
}


async def notify_assignee(bot: Bot, assignee: str, title: str, project: str, deadline: str):
    if not assignee:
        return
    user = get_user_by_name(assignee)
    if user:
        try:
            await bot.send_message(
                user["telegram_id"],
                f"📌 *Вам назначена задача!*\n\n"
                f"📋 *Задача:* {title}\n"
                f"📁 *Проект:* {project}\n"
                f"📅 *Срок:* {deadline or '—'}\n\n"
                f"_Откройте дашборд для подробностей._",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")


def task_keyboard(parsed):
    def btn(key, label):
        v = parsed.get(key) or "—"
        return InlineKeyboardButton(text=f"✏️ {label}: {v}", callback_data=f"edit_{key}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("title", "Задача")],
        [btn("assignee", "Ответственный")],
        [btn("department", "Отдел")],
        [btn("project", "Проект")],
        [btn("deadline", "Срок")],
        [btn("description", "Комментарий")],
        [
            InlineKeyboardButton(text="✅ Сохранить", callback_data="confirm_task"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task"),
        ]
    ])


def edit_task_keyboard(task_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Изменить задачу", callback_data=f"etask_title_{task_id}")],
        [InlineKeyboardButton(text="👤 Изменить ответственного", callback_data=f"etask_assignee_{task_id}")],
        [InlineKeyboardButton(text="📅 Изменить срок", callback_data=f"etask_deadline_{task_id}")],
        [InlineKeyboardButton(text="📁 Изменить проект", callback_data=f"etask_project_{task_id}")],
        [InlineKeyboardButton(text="💬 Изменить комментарий", callback_data=f"etask_comment_{task_id}")],
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"etask_delete_{task_id}")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_task")],
    ])


def mytask_keyboard(task_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать комментарий", callback_data=f"addcomment_{task_id}")],
        [InlineKeyboardButton(text="📎 Прикрепить файл", callback_data=f"addfile_{task_id}")],
        [InlineKeyboardButton(text="📋 История комментариев", callback_data=f"viewcomments_{task_id}")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_task")],
    ])


def edit_one_of_multiple_keyboard(task_idx):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Изменить название", callback_data=f"eom_title_{task_idx}")],
        [InlineKeyboardButton(text="👤 Изменить ответственного", callback_data=f"eom_assignee_{task_idx}")],
        [InlineKeyboardButton(text="📅 Изменить срок", callback_data=f"eom_deadline_{task_idx}")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="eom_done_0")],
    ])


def format_one_of_multiple(task, idx, total):
    return (
        f"✏️ *Задача {idx+1} из {total}:*\n\n"
        f"📌 *Название:* {task.get('title') or '—'}\n"
        f"👤 *Ответственный:* {task.get('assignee') or '—'}\n"
        f"📅 *Срок:* {task.get('deadline') or '—'}\n\n"
        f"_Нажмите поле чтобы изменить или Готово._"
    )


def format_task_text(parsed):
    return (
        f"📋 *Проверьте задачу:*\n\n"
        f"📌 *Задача:* {parsed.get('title') or '—'}\n"
        f"👤 *Ответственный:* {parsed.get('assignee') or '—'}\n"
        f"🏢 *Отдел:* {parsed.get('department') or '—'}\n"
        f"📁 *Проект:* {parsed.get('project') or '—'}\n"
        f"📅 *Срок:* {parsed.get('deadline') or '—'}\n"
        f"💬 *Комментарий:* {parsed.get('description') or '—'}\n\n"
        f"_Нажмите поле чтобы изменить._"
    )


def format_existing_task(t):
    return (
        f"✏️ *Редактирование задачи #{t['id']}:*\n\n"
        f"📌 *Задача:* {t.get('title') or '—'}\n"
        f"👤 *Ответственный:* {t.get('assignee') or '—'}\n"
        f"🏢 *Отдел:* {t.get('department') or '—'}\n"
        f"📁 *Проект:* {t.get('project') or '—'}\n"
        f"📅 *Срок:* {t.get('deadline') or '—'}\n"
        f"💬 *Комментарий:* {t.get('comment') or '—'}\n\n"
        f"_Выберите поле для изменения._"
    )


def format_my_task(t):
    return (
        f"📋 *Задача #{t['id']}:*\n\n"
        f"📌 {t.get('title') or '—'}\n"
        f"📁 *Проект:* {t.get('project') or '—'}\n"
        f"📅 *Срок:* {t.get('deadline') or '—'}\n"
        f"🔵 *Статус:* {t.get('status') or '—'}\n"
        f"💬 *Комментарий:* {t.get('comment') or '—'}"
    )


def format_multiple_preview(tasks, project, deadline, assignee):
    lines = [f"📋 *{len(tasks)} задач:*\n"]
    for i, t in enumerate(tasks, 1):
        title = t.get('title', '—')
        lines.append(f"*{i}.* {title}")
    lines.append(f"\n📁 *Проект:* {project}")
    lines.append(f"📅 *Срок:* {deadline or '—'}")
    lines.append(f"👤 *Ответственный:* {assignee or '—'}")
    lines.append("\n_Изменить или сохранить?_")
    return "\n".join(lines)


def multiple_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сохранить все", callback_data="confirm_multiple")],
        [InlineKeyboardButton(text="✏️ Редактировать задачи", callback_data="edit_tasks_list")],
        [InlineKeyboardButton(text="📁 Изменить проект", callback_data="correct_project")],
        [InlineKeyboardButton(text="📅 Изменить срок", callback_data="correct_deadline")],
        [InlineKeyboardButton(text="👤 Изменить ответственного", callback_data="correct_assignee")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task")],
    ])


def projects_keyboard(projects):
    buttons = [[InlineKeyboardButton(text=f"📁 {p['name']}", callback_data=f"proj_{i}")] for i, p in enumerate(projects)]
    buttons.append([InlineKeyboardButton(text="➕ Новый проект", callback_data="proj_new")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def projects_keyboard_for_edit(projects, task_id):
    buttons = [[InlineKeyboardButton(text=f"📁 {p['name']}", callback_data=f"eproj_{i}_{task_id}")] for i, p in enumerate(projects)]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def show_multiple_preview(target, state, edit=False):
    data = await state.get_data()
    tasks = data["multiple_tasks"]
    project = data.get("selected_project", "Общие")
    deadline = data.get("selected_deadline", "")
    assignee = data.get("selected_assignee", "")
    text = format_multiple_preview(tasks, project, deadline, assignee)
    if len(text) > 3000:
        text = text[:3000] + "..."
    await state.set_state(TaskCreation.confirming_multiple)
    if edit:
        await target.message.edit_text(text, reply_markup=multiple_confirm_keyboard(), parse_mode="Markdown")
    else:
        if hasattr(target, 'message'):
            await target.message.answer(text, reply_markup=multiple_confirm_keyboard(), parse_mode="Markdown")
        else:
            await target.answer(text, reply_markup=multiple_confirm_keyboard(), parse_mode="Markdown")


# ─── /start ────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я агент управления задачами.\n\n"
        "➕ /newtask — создать задачу\n"
        "✏️ /edit <ID> — редактировать задачу\n"
        "🗑 /delete <ID> — удалить задачу\n"
        "📋 /mytasks — мои задачи\n"
        "📊 /dashboard — дашборд\n"
        "📋 /tasks — задачи по проектам\n"
        "✅ /done <ID> — отметить выполненной\n"
        "⚠️ /overdue — просроченные\n"
        "📁 /projects — список проектов\n"
        "🆕 /newproject — создать проект\n"
        "📥 /import — импорт из Google Sheets\n"
        "👤 /register — зарегистрироваться для уведомлений"
    )


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    from config import RAILWAY_PUBLIC_DOMAIN
    url = f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN else "http://localhost:8080"
    await message.answer(f"📊 [Открыть дашборд]({url})", parse_mode="Markdown")


# ─── /register ─────────────────────────────────────────────────────────────
@router.message(Command("register"))
async def cmd_register(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "👤 Введите своё имя после команды:\n"
            "Например: `/register Турбина Е.`",
            parse_mode="Markdown"
        )
        return
    name = parts[1].strip()
    register_user(message.from_user.id, name)
    await message.answer(
        f"✅ Вы зарегистрированы как *{name}*!\n\n"
        f"Теперь вы будете получать уведомления когда вам назначают задачи.",
        parse_mode="Markdown"
    )


# ─── /mytasks ──────────────────────────────────────────────────────────────
@router.message(Command("mytasks"))
async def cmd_mytasks(message: Message):
    with get_conn() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (message.from_user.id,)
        ).fetchone()
    if not user:
        await message.answer(
            "👤 Вы не зарегистрированы!\n"
            "Напишите: `/register Ваше имя`",
            parse_mode="Markdown"
        )
        return
    name = user["name"]
    all_tasks = get_tasks()
    my_tasks = [t for t in all_tasks if name.lower() in (t.get("assignee") or "").lower()]
    if not my_tasks:
        await message.answer(f"📋 У вас нет задач, *{name}*.", parse_mode="Markdown")
        return
    for t in my_tasks[:10]:
        emoji = {"Открыта": "🔵", "В работе": "🟡", "Выполнена": "🟢"}.get(t.get("status", ""), "⚪")
        await message.answer(
            f"{emoji} {format_my_task(t)}",
            reply_markup=mytask_keyboard(t["id"]),
            parse_mode="Markdown"
        )


# ─── Комментарий к задаче ──────────────────────────────────────────────────
@router.callback_query(F.data.startswith("addcomment_"))
async def add_comment_start(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("addcomment_", ""))
    await state.update_data(commenting_task_id=task_id)
    await state.set_state(TaskCommenting.waiting_for_comment)
    await callback.message.answer("💬 Напишите комментарий к задаче:")
    await callback.answer()


@router.message(TaskCommenting.waiting_for_comment)
async def save_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("commenting_task_id")
    with get_conn() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (message.from_user.id,)
        ).fetchone()
    author = user["name"] if user else message.from_user.first_name or "Неизвестно"
    add_task_comment(task_id=task_id, author=author, text=message.text.strip())
    await state.clear()
    await message.answer(f"✅ Комментарий к задаче #{task_id} сохранён!")


# ─── Файл к задаче ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("addfile_"))
async def add_file_start(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("addfile_", ""))
    await state.update_data(commenting_task_id=task_id)
    await state.set_state(TaskCommenting.waiting_for_file)
    await callback.message.answer("📎 Отправьте файл или фото:")
    await callback.answer()


@router.message(TaskCommenting.waiting_for_file)
async def save_file(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("commenting_task_id")
    with get_conn() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (message.from_user.id,)
        ).fetchone()
    author = user["name"] if user else message.from_user.first_name or "Неизвестно"
    file_id = ""
    file_name = ""
    file_type = ""
    caption = message.caption or ""
    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "файл"
        file_type = "document"
    elif message.photo:
        file_id = message.photo[-1].file_id
        file_name = "фото"
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "видео"
        file_type = "video"
    else:
        await message.answer("❌ Поддерживаются файлы, фото и видео.")
        return
    add_task_comment(task_id=task_id, author=author, text=caption, file_id=file_id, file_name=file_name, file_type=file_type)
    await state.clear()
    await message.answer(f"✅ Файл *{file_name}* прикреплён к задаче #{task_id}!", parse_mode="Markdown")


# ─── История комментариев ──────────────────────────────────────────────────
@router.callback_query(F.data.startswith("viewcomments_"))
async def view_comments(callback: CallbackQuery):
    task_id = int(callback.data.replace("viewcomments_", ""))
    comments = get_task_comments(task_id)
    if not comments:
        await callback.message.answer(f"💬 К задаче #{task_id} нет комментариев.")
        await callback.answer()
        return
    lines = [f"💬 *Комментарии к задаче #{task_id}:*\n"]
    for c in comments:
        time = c.get("created_at", "")[:16]
        if c.get("file_id"):
            lines.append(f"📎 *{c['author']}* [{time}]: {c['file_name']} {c.get('text', '')}")
        else:
            lines.append(f"💬 *{c['author']}* [{time}]:
