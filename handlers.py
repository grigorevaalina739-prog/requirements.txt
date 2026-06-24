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
                      register_user, get_user_by_name, get_conn)

logger = logging.getLogger(__name__)
router = Router()


class TaskCreation(StatesGroup):
    waiting_for_text = State()
    editing_field = State()
    choosing_project = State()
    confirming = State()
    confirming_multiple = State()
    correcting_field_multiple = State()


class ProjectAdding(StatesGroup):
    waiting_for_name = State()


class ImportAdding(StatesGroup):
    waiting_for_url = State()


class TaskEditing(StatesGroup):
    choosing_field = State()
    editing_field = State()
    choosing_project = State()


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
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_task")],
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


def format_multiple_preview(tasks, project, deadline, assignee):
    lines = [f"📋 *{len(tasks)} задач:*\n"]
    for i, t in enumerate(tasks[:8], 1):
        title = t.get('title', '—')
        if len(title) > 40:
            title = title[:40] + "..."
        lines.append(f"*{i}.* {title}")
    if len(tasks) > 8:
        lines.append(f"_...и ещё {len(tasks) - 8}_")
    lines.append(f"\n📁 *Проект:* {project}")
    lines.append(f"📅 *Срок:* {deadline or '—'}")
    lines.append(f"👤 *Ответственный:* {assignee or '—'}")
    lines.append("\n_Изменить или сохранить?_")
    return "\n".join(lines)


def multiple_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сохранить все", callback_data="confirm_multiple")],
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
        "📊 /dashboard — дашборд\n"
        "📋 /tasks — задачи по проектам\n"
        "✅ /done <ID> — отметить выполненной\n"
        "⚠️ /overdue — просроченные\n"
        "📁 /projects — список проектов\n"
        "🆕 /newproject — создать проект\n"
        "📥 /import — импорт из Google Sheets\n"
        "🗑 /cleartasks — очистить все задачи\n"
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


# ─── /edit ─────────────────────────────────────────────────────────────────
@router.message(Command("edit"))
async def cmd_edit(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Укажите ID задачи: /edit 5")
        return
    task_id = int(parts[1])
    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        await message.answer(f"❌ Задача #{task_id} не найдена.")
        return
    await state.update_data(editing_task_id=task_id)
    await state.set_state(TaskEditing.choosing_field)
    await message.answer(
        format_existing_task(task),
        reply_markup=edit_task_keyboard(task_id),
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("etask_"), TaskEditing.choosing_field)
async def etask_choose_field(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    field = parts[1]
    task_id = parts[2]
    await state.update_data(etask_field=field, editing_task_id=int(task_id))

    if field == "project":
        projects = get_projects()
        await state.set_state(TaskEditing.choosing_project)
        await callback.message.answer("📁 Выберите проект:", reply_markup=projects_keyboard_for_edit(projects, task_id))
        await callback.answer()
        return

    labels = {
        "title": "название задачи",
        "assignee": "ответственного",
        "deadline": "срок (например: 30.06.2026)",
        "comment": "комментарий",
    }
    await state.set_state(TaskEditing.editing_field)
    await callback.message.answer(f"✏️ Введите новый {labels.get(field, field)}:")
    await callback.answer()


@router.callback_query(F.data.startswith("eproj_"), TaskEditing.choosing_project)
async def etask_choose_project(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    proj_idx = int(parts[1])
    task_id = int(parts[2])
    projects = get_projects()
    try:
        project = projects[proj_idx]["name"]
    except IndexError:
        project = ""
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET project=? WHERE id=?", (project, task_id))
    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    await state.set_state(TaskEditing.choosing_field)
    await callback.message.answer(
        format_existing_task(task),
        reply_markup=edit_task_keyboard(task_id),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(TaskEditing.editing_field)
async def etask_save_field(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("etask_field")
    task_id = data.get("editing_task_id")
    value = message.text.strip()

    if field == "deadline":
        value = await parse_deadline(value) or value

    with get_conn() as conn:
        conn.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (value, task_id))

    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    await state.set_state(TaskEditing.choosing_field)
    await message.answer(
        format_existing_task(task),
        reply_markup=edit_task_keyboard(task_id),
        parse_mode="Markdown"
    )


# ─── /newtask ──────────────────────────────────────────────────────────────
@router.message(Command("newtask"))
async def cmd_newtask(message: Message, state: FSMContext):
    await state.set_state(TaskCreation.waiting_for_text)
    await message.answer("📝 Опишите задачу или список задач — AI разберёт автоматически.")


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
        first = tasks[0] if tasks else {}
        await state.update_data(
            multiple_tasks=tasks,
            selected_project="",
            selected_deadline=first.get("deadline", ""),
            selected_assignee=first.get("assignee", "")
        )
        projects = get_projects()
        if projects:
            await state.set_state(TaskCreation.choosing_project)
            await message.answer(
                f"📋 Найдено *{len(tasks)} задач*. В какой проект добавить?",
                reply_markup=projects_keyboard(projects),
                parse_mode="Markdown"
            )
        else:
            await state.update_data(selected_project="Общие")
            await show_multiple_preview(message, state)
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
    proj_data = callback.data.replace("proj_", "")
    data = await state.get_data()

    if proj_data == "new":
        await state.set_state(ProjectAdding.waiting_for_name)
        await callback.message.answer("📁 Введите название нового проекта:")
        await callback.answer()
        return

    projects = get_projects()
    try:
        project = projects[int(proj_data)]["name"]
    except (ValueError, IndexError):
        project = proj_data

    if data.get("multiple_tasks"):
        await state.update_data(selected_project=project)
        await show_multiple_preview(callback, state, edit=False)
        await callback.answer()
        return

    parsed = data.get("parsed", {})
    parsed["project"] = project
    await state.update_data(parsed=parsed)
    await state.set_state(TaskCreation.confirming)
    await callback.message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")
    await callback.answer()


# ─── Кнопки изменения ──────────────────────────────────────────────────────
@router.callback_query(F.data == "correct_project", TaskCreation.confirming_multiple)
async def correct_project(callback: CallbackQuery, state: FSMContext):
    projects = get_projects()
    await state.set_state(TaskCreation.choosing_project)
    await callback.message.answer("📁 Выберите проект:", reply_markup=projects_keyboard(projects))
    await callback.answer()


@router.callback_query(F.data == "correct_deadline", TaskCreation.confirming_multiple)
async def correct_deadline(callback: CallbackQuery, state: FSMContext):
    await state.update_data(correcting="deadline")
    await state.set_state(TaskCreation.correcting_field_multiple)
    await callback.message.answer("📅 Введите срок (например: 30.06.2026):")
    await callback.answer()


@router.callback_query(F.data == "correct_assignee", TaskCreation.confirming_multiple)
async def correct_assignee(callback: CallbackQuery, state: FSMContext):
    await state.update_data(correcting="assignee")
    await state.set_state(TaskCreation.correcting_field_multiple)
    await callback.message.answer("👤 Введите ответственного:")
    await callback.answer()


@router.message(TaskCreation.correcting_field_multiple)
async def apply_correction(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("correcting")
    value = message.text.strip()
    if field == "deadline":
        value = await parse_deadline(value) or value
        await state.update_data(selected_deadline=value)
    elif field == "assignee":
        await state.update_data(selected_assignee=value)
    await show_multiple_preview(message, state)


# ─── Сохранение нескольких задач ───────────────────────────────────────────
@router.callback_query(F.data == "confirm_multiple", TaskCreation.confirming_multiple)
async def confirm_multiple(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tasks = data["multiple_tasks"]
    project = data.get("selected_project", "Общие")
    deadline = data.get("selected_deadline", "")
    assignee = data.get("selected_assignee", "")
    saved = 0
    for t in tasks:
        final_assignee = assignee or t.get("assignee") or ""
        final_deadline = deadline or t.get("deadline") or ""
        title = t.get("title") or "Без названия"
        add_task(
            project=project,
            assignee=final_assignee,
            department=t.get("department") or "",
            title=title,
            deadline=final_deadline,
            comment=t.get("description") or "",
        )
        await notify_assignee(callback.bot, final_assignee, title, project, final_deadline)
        saved += 1
    await state.clear()
    await callback.message.edit_text(
        f"✅ Сохранено *{saved} задач* в проект *{project}*!",
        parse_mode="Markdown"
    )
    await callback.answer()


# ─── Редактирование одной задачи (при создании) ───────────────────────────
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
    assignee = p.get("assignee") or ""
    deadline = p.get("deadline") or ""
    title = p.get("title") or "Без названия"
    task_id = add_task(
        project=project,
        assignee=assignee,
        department=p.get("department") or "",
        title=title,
        deadline=deadline,
        comment=p.get("description") or "",
    )
    await notify_assignee(callback.bot, assignee, title, project, deadline)
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
        [InlineKeyboardButton(text=f"📁 {p['name']}", callback_data=f"show_{i}")] for i, p in enumerate(projects)
    ])
    await message.answer("📋 Выберите проект:", reply_markup=kb)


@router.callback_query(F.data.startswith("show_"))
async def show_project_tasks(callback: CallbackQuery):
    idx = callback.data.replace("show_", "")
    projects = get_projects()
    try:
        project = projects[int(idx)]["name"]
    except (ValueError, IndexError):
        project = idx
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
