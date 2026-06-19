from datetime import datetime
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from agent import parse_task_with_ai, analyze_project_tasks, parse_deadline
from sheets import (add_task, get_all_tasks, update_task_status, get_overdue_tasks,
                    get_project_names, add_project_sheet, get_overdue_from_project)

logger = logging.getLogger(__name__)
router = Router()


class TaskCreation(StatesGroup):
    waiting_for_text = State()
    editing_field = State()
    choosing_project = State()
    confirming = State()


class ProjectAdding(StatesGroup):
    waiting_for_name = State()


FIELD_LABELS = {
    "title": "Задача",
    "assignee": "Ответственный",
    "department": "Отдел",
    "project": "Проект",
    "deadline": "Срок (ГГГГ-ММ-ДД)",
    "description": "Комментарий",
}


def task_keyboard(parsed: dict) -> InlineKeyboardMarkup:
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


def format_task_text(parsed: dict) -> str:
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


def projects_keyboard(projects: list, include_new=True) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text=f"📁 {p}", callback_data=f"proj_{p}")] for p in projects]
    if include_new:
        buttons.append([InlineKeyboardButton(text="➕ Создать новый проект", callback_data="proj_new")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── /start ────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я агент управления задачами.\n\n"
        "➕ /newtask — создать задачу\n"
        "📋 /tasks — список задач\n"
        "✅ /done <ID> — отметить выполненной\n"
        "⚠️ /overdue — просроченные задачи\n"
        "📁 /projects — список проектов\n"
        "🆕 /newproject — создать проект\n"
        "❓ /help — справка"
    )


# ─── /newtask ──────────────────────────────────────────────────────────────
@router.message(Command("newtask"))
async def cmd_newtask(message: Message, state: FSMContext):
    await state.set_state(TaskCreation.waiting_for_text)
    await message.answer(
        "📝 Опишите задачу текстом — AI заполнит поля автоматически.\n\n"
        "Пример: _Подготовить презентацию, отдел маркетинга, ответственный Алексей, до пятницы_",
        parse_mode="Markdown"
    )


@router.message(TaskCreation.waiting_for_text)
async def process_task_text(message: Message, state: FSMContext):
    await message.answer("🤖 Анализирую задачу...")
    today = datetime.now().strftime("%Y-%m-%d")
    parsed = await parse_task_with_ai(message.text, today)
    if not parsed:
        await message.answer("❌ Не удалось разобрать. Попробуйте /newtask заново.")
        await state.clear()
        return

    await state.update_data(parsed=parsed)

    # Если проект не распознан — предложить выбрать
    projects = get_project_names()
    if not parsed.get("project") and projects:
        await state.set_state(TaskCreation.choosing_project)
        await message.answer(
            "📁 В какой проект добавить задачу?",
            reply_markup=projects_keyboard(projects)
        )
    else:
        await state.set_state(TaskCreation.confirming)
        await message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")


# ─── Выбор проекта ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("proj_"), TaskCreation.choosing_project)
async def choose_project(callback: CallbackQuery, state: FSMContext):
    project = callback.data.replace("proj_", "")
    if project == "new":
        await callback.message.answer("📁 Введите название нового проекта:")
        await state.set_state(ProjectAdding.waiting_for_name)
        await callback.answer()
        return

    data = await state.get_data()
    parsed = data["parsed"]
    parsed["project"] = project
    await state.update_data(parsed=parsed)
    await state.set_state(TaskCreation.confirming)
    await callback.message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")
    await callback.answer()


# ─── Редактирование поля ───────────────────────────────────────────────────
@router.callback_query(F.data.startswith("edit_"), TaskCreation.confirming)
async def edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_", "")
    label = FIELD_LABELS.get(field, field)

    # Для проекта — показать список
    if field == "project":
        projects = get_project_names()
        await state.update_data(editing=field)
        await state.set_state(TaskCreation.choosing_project)
        await callback.message.answer("📁 Выберите проект:", reply_markup=projects_keyboard(projects))
        await callback.answer()
        return

    await state.update_data(editing=field)
    await state.set_state(TaskCreation.editing_field)
    await callback.message.answer(f"✏️ Введите *{label}*:", parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("proj_"), TaskCreation.choosing_project)
async def choose_project_edit(callback: CallbackQuery, state: FSMContext):
    project = callback.data.replace("proj_", "")
    if project == "new":
        await callback.message.answer("📁 Введите название нового проекта:")
        await state.set_state(ProjectAdding.waiting_for_name)
        await callback.answer()
        return
    data = await state.get_data()
    parsed = data["parsed"]
    parsed["project"] = project
    await state.update_data(parsed=parsed)
    await state.set_state(TaskCreation.confirming)
    await callback.message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")
    await callback.answer()


@router.message(TaskCreation.editing_field)
async def save_edited_field(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("editing")
    parsed = data.get("parsed", {})
    value = message.text.strip()

    if field == "deadline" and value not in ("", "—"):
        parsed[field] = await parse_deadline(value) or value
    else:
        parsed[field] = "" if value == "—" else value

    await state.update_data(parsed=parsed)
    await state.set_state(TaskCreation.confirming)
    await message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")


# ─── Сохранение ────────────────────────────────────────────────────────────
@router.callback_query(F.data == "confirm_task", TaskCreation.confirming)
async def confirm_task(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    p = data["parsed"]
    project = p.get("project") or "Tasks"
    task_id = add_task(
        assignee=p.get("assignee") or "",
        department=p.get("department") or "",
        project=project,
        title=p.get("title") or "Без названия",
        deadline=p.get("deadline") or "",
        comment=p.get("description") or "",
    )
    await state.clear()
    await callback.message.edit_text(
        f"✅ Задача #{task_id} сохранена в проект *{project}*!",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_task")
async def cancel_task(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()


# ─── /tasks ────────────────────────────────────────────────────────────────
@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    projects = get_project_names()
    if not projects:
        await message.answer("📋 Задач нет. Создайте: /newtask")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📁 {p}", callback_data=f"show_{p}")] for p in projects
    ])
    await message.answer("📋 Выберите проект:", reply_markup=kb)


@router.callback_query(F.data.startswith("show_"))
async def show_project_tasks(callback: CallbackQuery):
    project = callback.data.replace("show_", "")
    tasks = get_all_tasks(project)
    if not tasks:
        await callback.message.answer(f"📋 В проекте *{project}* задач нет.", parse_mode="Markdown")
        await callback.answer()
        return
    lines = [f"📁 *{project}:*\n"]
    for t in tasks[-20:]:
        emoji = {"Открыта": "🔵", "В работе": "🟡", "Выполнена": "🟢"}.get(t.get("Статус", ""), "⚪")
        lines.append(f"{emoji} [{t['ID']}] *{t.get('Задача','')}*\n   👤 {t.get('Ответственное лицо','—')} | 📅 {t.get('Срок исполнения','—')}")
    await callback.message.answer("\n".join(lines), parse_mode="Markdown")
    await callback.answer()


# ─── /done ─────────────────────────────────────────────────────────────────
@router.message(Command("done"))
async def cmd_done(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Укажите ID: /done 5")
        return
    success = update_task_status(int(parts[1]), "Выполнена")
    await message.answer(f"✅ Задача #{parts[1]} выполнена!" if success else f"❌ Задача #{parts[1]} не найдена.")


# ─── /overdue ──────────────────────────────────────────────────────────────
@router.message(Command("overdue"))
async def cmd_overdue(message: Message):
    await message.answer("🔍 Проверяю все проекты...")
    overdue = get_overdue_tasks()
    if not overdue:
        await message.answer("🎉 Просроченных задач нет!")
        return
    lines = ["⚠️ *Просроченные задачи:*\n"]
    for t in overdue:
        lines.append(
            f"🔴 [{t['ID']}] *{t.get('Задача','')}*\n"
            f"   📁 {t.get('Проект','—')} | 👤 {t.get('Ответственное лицо','—')} | 📅 {t.get('Срок исполнения','—')}"
        )
    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─── /projects ─────────────────────────────────────────────────────────────
@router.message(Command("projects"))
async def cmd_projects(message: Message):
    projects = get_project_names()
    if not projects:
        await message.answer("📁 Проектов нет. Создайте: /newproject")
        return
    lines = ["📁 *Проекты:*\n"] + [f"• {p}" for p in projects]
    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─── /newproject ───────────────────────────────────────────────────────────
@router.message(Command("newproject"))
async def cmd_newproject(message: Message, state: FSMContext):
    await state.set_state(ProjectAdding.waiting_for_name)
    await message.answer("📁 Введите название нового проекта:")


@router.message(ProjectAdding.waiting_for_name)
async def process_project_name(message: Message, state: FSMContext):
    name = message.text.strip()
    add_project_sheet(name)
    await state.clear()
    await message.answer(f"✅ Проект *{name}* создан!\n\nТеперь при создании задачи вы сможете выбрать этот проект.", parse_mode="Markdown")


# ─── /help ─────────────────────────────────────────────────────────────────
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 *Справка:*\n\n"
        "/newtask — создать задачу (AI заполнит поля, вы выберете проект)\n"
        "/tasks — задачи по проектам\n"
        "/done <ID> — отметить выполненной\n"
        "/overdue — просроченные во всех проектах\n"
        "/projects — список проектов\n"
        "/newproject — создать новый проект\n\n"
        "Уведомления о просрочке — каждый день в 09:00 МСК.",
        parse_mode="Markdown"
    )
