from datetime import datetime
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from agent import parse_task_with_ai, parse_deadline, analyze_project_tasks
from database import (add_task, get_tasks, update_status, get_projects,
                      add_project, get_overdue_tasks, get_stats)

logger = logging.getLogger(__name__)
router = Router()


class TaskCreation(StatesGroup):
    waiting_for_text = State()
    editing_field = State()
    choosing_project = State()
    confirming = State()
    confirming_multiple = State()


class ProjectAdding(StatesGroup):
    waiting_for_name = State()


class ImportAdding(StatesGroup):
    waiting_for_url = State()


FIELD_LABELS = {
    "title": "Задача",
    "assignee": "Ответственный",
    "department": "Отдел",
    "project": "Проект",
    "deadline": "Срок (ГГГГ-ММ-ДД или текстом)",
    "description": "Комментарий",
}


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


def format_multiple_tasks(tasks, project):
    lines = [f"📋 *Найдено {len(tasks)} задач:*\n"]
    for i, t in enumerate(tasks, 1):
        lines.append(
            f"*{i}.* {t.get('title','—')}\n"
            f"   👤 {t.get('assignee') or '—'} | 📅 {t.get('deadline') or '—'}\n"
        )
    lines.append(f"📁 *Проект:* {project}\n")
    lines.append("Сохранить все задачи?")
    return "\n".join(lines)


def projects_keyboard(projects):
    buttons = [[InlineKeyboardButton(text=f"📁 {p['name']}", callback_data=f"proj_{p['name']}")] for p in projects]
    buttons.append([InlineKeyboardButton(text="➕ Новый проект", callback_data="proj_new")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── /start ────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я агент управления задачами.\n\n"
        "➕ /newtask — создать задачу (или список задач)\n"
        "📊 /dashboard — ссылка на дашборд\n"
        "📋 /tasks — задачи по проектам\n"
        "✅ /done <ID> — отметить выполненной\n"
        "⚠️ /overdue — просроченные\n"
        "📁 /projects — список проектов\n"
        "🆕 /newproject — создать проект\n"
        "📥 /import — импорт из Google Sheets\n"
        "🗑 /cleartasks — очистить все задачи и проекты"
    )


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    from config import RAILWAY_PUBLIC_DOMAIN
    url = f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN else "http://localhost:8080"
    await message.answer(
        f"📊 [Открыть дашборд]({url})",
        parse_mode="Markdown"
    )


# ─── /newtask ──────────────────────────────────────────────────────────────
@router.message(Command("newtask"))
async def cmd_newtask(message: Message, state: FSMContext):
    await state.set_state(TaskCreation.waiting_for_text)
    await message.answer(
        "📝 Опишите задачу или список задач — AI разберёт автоматически.\n\n"
        "Можно писать с ошибками, AI исправит и структурирует.",
    )


@router.message(TaskCreation.waiting_for_text)
async def process_task_text(message: Message, state: FSMContext):
    await message.answer("🤖 Анализирую...")
    today = datetime.now().strftime("%Y-%m-%d")
    result = await parse_task_with_ai(message.text, today)

    if not result:
        await message.answer("❌ Не удалось разобрать. Попробуйте /newtask заново.")
        await state.clear()
        return

    if result.get("is_multiple") and result.get("tasks"):
        tasks = result["tasks"]
        projects = get_projects()
        await state.update_data(multiple_tasks=tasks)

        if projects:
            await state.set_state(TaskCreation.choosing_project)
            await message.answer(
                f"📋 Найдено *{len(tasks)} задач*. В какой проект добавить?",
                reply_markup=projects_keyboard(projects),
                parse_mode="Markdown"
            )
        else:
            await state.update_data(selected_project="Общие")
            await state.set_state(TaskCreation.confirming_multiple)
            await message.answer(
                format_multiple_tasks(tasks, "Общие"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="✅ Сохранить все", callback_data="confirm_multiple"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task"),
                ]]),
                parse_mode="Markdown"
            )
        return

    parsed = result
    await state.update_data(parsed=parsed)
    projects = get_projects()
    if not parsed.get("project") and projects:
        await state.set_state(TaskCreation.choosing_project)
        await message.answer("📁 В какой проект добавить?", reply_markup=projects_keyboard(projects))
    else:
        await state.set_state(TaskCreation.confirming)
        await message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")


# ─── Выбор проекта ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("proj_"), TaskCreation.choosing_project)
async def choose_project(callback: CallbackQuery, state: FSMContext):
    project = callback.data.replace("proj_", "")
    data = await state.get_data()

    if project == "new":
        await state.set_state(ProjectAdding.waiting_for_name)
        await callback.message.answer("📁 Введите название нового проекта:")
        await callback.answer()
        return

    if data.get("multiple_tasks"):
        tasks = data["multiple_tasks"]
        await state.update_data(selected_project=project)
        await state.set_state(TaskCreation.confirming_multiple)
        await callback.message.answer(
            format_multiple_tasks(tasks, project),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Сохранить все", callback_data="confirm_multiple"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task"),
            ]]),
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    parsed = data["parsed"]
    parsed["project"] = project
    await state.update_data(parsed=parsed)
    await state.set_state(TaskCreation.confirming)
    await callback.message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")
    await callback.answer()


# ─── Сохранение нескольких задач ───────────────────────────────────────────
@router.callback_query(F.data == "confirm_multiple", TaskCreation.confirming_multiple)
async def confirm_multiple(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tasks = data["multiple_tasks"]
    project = data.get("selected_project", "Общие")
    saved = 0
    for t in tasks:
        add_task(
            project=t.get("project") or project,
            assignee=t.get("assignee") or "",
            department=t.get("department") or "",
            title=t.get("title") or "Без названия",
            deadline=t.get("deadline") or "",
            comment=t.get("description") or "",
        )
        saved += 1
    await state.clear()
    await callback.message.edit_text(
        f"✅ Сохранено *{saved} задач* в проект *{project}*!",
        parse_mode="Markdown"
    )
    await callback.answer()


# ─── Редактирование поля ───────────────────────────────────────────────────
@router.callback_query(F.data.startswith("edit_"), TaskCreation.confirming)
async def edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_", "")
    if field == "project":
        projects = get_projects()
        await state.update_data(editing=field)
        await state.set_state(TaskCreation.choosing_project)
        await callback.message.answer("📁 Выберите проект:", reply_markup=projects_keyboard(projects))
        await callback.answer()
        return
    await state.update_data(editing=field)
    await state.set_state(TaskCreation.editing_field)
    await callback.message.answer(f"✏️ Введите *{FIELD_LABELS.get(field, field)}*:", parse_mode="Markdown")
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


@router.callback_query(F.data == "confirm_task", TaskCreation.confirming)
async def confirm_task(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    p = data["parsed"]
    project = p.get("project") or "Общие"
    task_id = add_task(
        project=project,
        assignee=p.get("assignee") or "",
        department=p.get("department") or "",
        title=p.get("title") or "Без названия",
        deadline=p.get("deadline") or "",
        comment=p.get("description") or "",
    )
    await state.clear()
    await callback.message.edit_text(
        f"✅ Задача #{task_id} добавлена в *{project}*!",
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
    projects = get_projects()
    if not projects:
        await message.answer("📋 Задач нет. /newtask")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📁 {p['name']}", callback_data=f"show_{p['name']}")] for p in projects
    ])
    await message.answer("📋 Выберите проект:", reply_markup=kb)


@router.callback_query(F.data.startswith("show_"))
async def show_project_tasks(callback: CallbackQuery):
    project = callback.data.replace("show_", "")
    tasks = get_tasks(project=project)
    if not tasks:
        await callback.message.answer(f"📋 В *{project}* задач нет.", parse_mode="Markdown")
        await callback.answer()
        return
    lines = [f"📁 *{project}:*\n"]
    for t in tasks[:15]:
        emoji = {"Открыта": "🔵", "В работе": "🟡", "Выполнена": "🟢"}.get(t.get("status", ""), "⚪")
        lines.append(f"{emoji} [{t['id']}] *{t['title']}*\n   👤 {t['assignee'] or '—'} | 📅 {t['deadline'] or '—'}")
    await callback.message.answer("\n".join(lines), parse_mode="Markdown")
    await callback.answer()


# ─── /done ─────────────────────────────────────────────────────────────────
@router.message(Command("done"))
async def cmd_done(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Укажите ID: /done 5")
        return
    update_status(int(parts[1]), "Выполнена")
    await message.answer(f"✅ Задача #{parts[1]} выполнена!")


# ─── /overdue ──────────────────────────────────────────────────────────────
@router.message(Command("overdue"))
async def cmd_overdue(message: Message):
    tasks = get_overdue_tasks()
    if not tasks:
        await message.answer("🎉 Просроченных задач нет!")
        return
    lines = ["⚠️ *Просроченные задачи:*\n"]
    for t in tasks:
        lines.append(f"🔴 [{t['id']}] *{t['title']}*\n   📁 {t['project']} | 👤 {t['assignee'] or '—'} | 📅 {t['deadline']}")
    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─── /projects ─────────────────────────────────────────────────────────────
@router.message(Command("projects"))
async def cmd_projects(message: Message):
    projects = get_projects()
    if not projects:
        await message.answer("📁 Проектов нет. /newproject")
        return
    stats = get_stats()
    by_proj = {p["project"]: p["cnt"] for p in stats["by_project"]}
    lines = ["📁 *Проекты:*\n"]
    for p in projects:
        cnt = by_proj.get(p["name"], 0)
        lines.append(f"• *{p['name']}* — {cnt} задач")
    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─── /newproject ───────────────────────────────────────────────────────────
@router.message(Command("newproject"))
async def cmd_newproject(message: Message, state: FSMContext):
    await state.set_state(ProjectAdding.waiting_for_name)
    await message.answer("📁 Введите название проекта:")


@router.message(ProjectAdding.waiting_for_name)
async def process_project_name(message: Message, state: FSMContext):
    name = message.text.strip()
    add_project(name)
    await state.clear()
    await message.answer(f"✅ Проект *{name}* создан!", parse_mode="Markdown")


# ─── /cleartasks ───────────────────────────────────────────────────────────
@router.message(Command("cleartasks"))
async def cmd_cleartasks(message: Message):
    from database import get_conn
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM projects")
    await message.answer("🗑 Все задачи и проекты удалены!")


# ─── /import ───────────────────────────────────────────────────────────────
@router.message(Command("import"))
async def cmd_import(message: Message, state: FSMContext):
    await state.set_state(ImportAdding.waiting_for_url)
    await message.answer("🔗 Вставьте ссылку на Google таблицу для импорта:")


@router.message(ImportAdding.waiting_for_url)
async def import_url(message: Message, state: FSMContext):
    url = message.text.strip()
    try:
        spreadsheet_id = url.split("/d/")[1].split("/")[0]
    except IndexError:
        await message.answer("❌ Неверная ссылка.")
        return
    await state.clear()
    await message.answer("⏳ Импортирую задачи из всех листов...", parse_mode="Markdown")
    from importer import import_from_sheet
    result = import_from_sheet(spreadsheet_id, "")
    if result["success"]:
        await message.answer(
            f"✅ Импорт завершён!\n\n"
            f"📥 Добавлено: *{result['imported']}* задач\n"
            f"⏭ Пропущено: *{result['skipped']}*",
            parse_mode="Markdown"
        )
    else:
        await message.answer(f"❌ Ошибка: {result['error']}")
