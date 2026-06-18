from datetime import datetime
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from agent import parse_task_with_ai, analyze_project_tasks
from sheets import (add_task, get_all_tasks, update_task_status, get_overdue_tasks,
                    get_all_projects, add_project, get_overdue_from_project)

logger = logging.getLogger(__name__)
router = Router()


class TaskCreation(StatesGroup):
    waiting_for_text = State()
    editing_field = State()
    confirming = State()


class ProjectAdding(StatesGroup):
    waiting_for_name = State()
    waiting_for_url = State()


def task_keyboard(parsed: dict) -> InlineKeyboardMarkup:
    """Клавиатура с кнопками редактирования каждого поля."""
    def val(key, label):
        v = parsed.get(key) or "—"
        return InlineKeyboardButton(text=f"✏️ {label}: {v}", callback_data=f"edit_{key}")

    return InlineKeyboardMarkup(inline_keyboard=[
        [val("title", "Задача")],
        [val("assignee", "Ответственный")],
        [val("department", "Отдел")],
        [val("project", "Проект")],
        [val("deadline", "Срок")],
        [val("description", "Комментарий")],
        [
            InlineKeyboardButton(text="✅ Сохранить", callback_data="confirm_task"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task"),
        ]
    ])


def format_task_text(parsed: dict) -> str:
    return (
        f"📋 *Проверьте и отредактируйте задачу:*\n\n"
        f"📌 *Задача:* {parsed.get('title') or '—'}\n"
        f"👤 *Ответственный:* {parsed.get('assignee') or '—'}\n"
        f"🏢 *Отдел:* {parsed.get('department') or '—'}\n"
        f"📁 *Проект:* {parsed.get('project') or '—'}\n"
        f"📅 *Срок:* {parsed.get('deadline') or '—'}\n"
        f"💬 *Комментарий:* {parsed.get('description') or '—'}\n\n"
        f"_Нажмите на поле чтобы изменить его._"
    )


FIELD_LABELS = {
    "title": "Задача",
    "assignee": "Ответственный",
    "department": "Отдел",
    "project": "Проект",
    "deadline": "Срок (ГГГГ-ММ-ДД или напишите текстом)",
    "description": "Комментарий",
}


# ─── /start ────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я агент управления задачами.\n\n"
        "➕ /newtask — создать задачу\n"
        "📋 /tasks — список задач\n"
        "✅ /done <ID> — отметить выполненной\n"
        "⚠️ /overdue — просроченные (все проекты)\n"
        "🗂 /projects — список проектов\n"
        "🔗 /addproject — подключить таблицу проекта\n"
        "❓ /help — справка"
    )


# ─── /newtask ──────────────────────────────────────────────────────────────
@router.message(Command("newtask"))
async def cmd_newtask(message: Message, state: FSMContext):
    await state.set_state(TaskCreation.waiting_for_text)
    await message.answer(
        "📝 Опишите задачу текстом — AI заполнит поля автоматически.\n\n"
        "Пример: _Подготовить презентацию, отдел маркетинга, ответственный Алексей, до пятницы_\n\n"
        "Потом сможете отредактировать любое поле кнопкой.",
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
    await state.set_state(TaskCreation.confirming)
    await message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")


# ─── Редактирование поля ───────────────────────────────────────────────────
@router.callback_query(F.data.startswith("edit_"), TaskCreation.confirming)
async def edit_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.replace("edit_", "")
    label = FIELD_LABELS.get(field, field)
    await state.update_data(editing=field)
    await state.set_state(TaskCreation.editing_field)
    await callback.message.answer(f"✏️ Введите новое значение для *{label}*:", parse_mode="Markdown")
    await callback.answer()


@router.message(TaskCreation.editing_field)
async def save_edited_field(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("editing")
    parsed = data.get("parsed", {})

    # Если срок — попробуем распарсить через AI
    if field == "deadline" and message.text.strip() not in ("", "—"):
        from agent import parse_deadline
        parsed[field] = await parse_deadline(message.text.strip()) or message.text.strip()
    else:
        parsed[field] = message.text.strip() if message.text.strip() != "—" else ""

    await state.update_data(parsed=parsed)
    await state.set_state(TaskCreation.confirming)
    await message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")


# ─── Сохранение / Отмена ──────────────────────────────────────────────────
@router.callback_query(F.data == "confirm_task", TaskCreation.confirming)
async def confirm_task(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    p = data["parsed"]
    task_id = add_task(
        assignee=p.get("assignee") or "",
        department=p.get("department") or "",
        project=p.get("project") or "",
        title=p.get("title") or "Без названия",
        deadline=p.get("deadline") or "",
        comment=p.get("description") or "",
    )
    await state.clear()
    await callback.message.edit_text(f"✅ Задача #{task_id} сохранена!\n\nДозаполните пустые поля в Google Sheets.")
    await callback.answer()


@router.callback_query(F.data == "cancel_task")
async def cancel_task(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()


# ─── /tasks ────────────────────────────────────────────────────────────────
@router.message(Command("tasks"))
async def cmd_tasks(message: Message):
    tasks = get_all_tasks()
    if not tasks:
        await message.answer("📋 Задач нет. Создайте: /newtask")
        return
    lines = ["📋 *Задачи:*\n"]
    for t in tasks[-20:]:
        emoji = {"Открыта": "🔵", "В работе": "🟡", "Выполнена": "🟢"}.get(t.get("Статус", ""), "⚪")
        assignee = t.get("Ответственное лицо") or "—"
        deadline = t.get("Срок исполнения") or "—"
        lines.append(f"{emoji} [{t['ID']}] *{t.get('Задача','')}*\n   👤 {assignee} | 📅 {deadline}")
    await message.answer("\n".join(lines), parse_mode="Markdown")


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
    all_overdue = get_overdue_tasks()
    result = []
    if all_overdue:
        lines = ["⚠️ *Основная таблица:*"]
        for t in all_overdue:
            assignee = t.get("Ответственное лицо") or "—"
            lines.append(f"🔴 [{t['ID']}] *{t.get('Задача','')}*\n   👤 {assignee} | 📅 {t.get('Срок исполнения','—')}")
        result.append("\n".join(lines))
    projects = get_all_projects()
    for project in projects:
        data = get_overdue_from_project(project["SPREADSHEET_ID"], project["Название"])
        if data:
            analysis = await analyze_project_tasks(project["Название"], data["rows"])
            result.append(f"📁 *{project['Название']}:*\n{analysis}")
    if not result:
        await message.answer("🎉 Просроченных задач нет!")
    else:
        await message.answer("\n\n".join(result), parse_mode="Markdown")


# ─── /projects ─────────────────────────────────────────────────────────────
@router.message(Command("projects"))
async def cmd_projects(message: Message):
    projects = get_all_projects()
    if not projects:
        await message.answer("🗂 Проектов нет. Добавьте: /addproject")
        return
    lines = ["🗂 *Проекты:*\n"]
    for p in projects:
        lines.append(f"📁 [{p['ID']}] *{p['Название']}*")
    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─── /addproject ───────────────────────────────────────────────────────────
@router.message(Command("addproject"))
async def cmd_addproject(message: Message, state: FSMContext):
    await state.set_state(ProjectAdding.waiting_for_name)
    await message.answer("📁 Введите название проекта:")


@router.message(ProjectAdding.waiting_for_name)
async def process_project_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(ProjectAdding.waiting_for_url)
    await message.answer("🔗 Вставьте ссылку на Google таблицу:")


@router.message(ProjectAdding.waiting_for_url)
async def process_project_url(message: Message, state: FSMContext):
    url = message.text.strip()
    try:
        spreadsheet_id = url.split("/d/")[1].split("/")[0]
    except IndexError:
        await message.answer("❌ Неверная ссылка.")
        return
    data = await state.get_data()
    name = data["name"]
    await message.answer("🔍 Проверяю доступ...")
    result = get_overdue_from_project(spreadsheet_id, name)
    if result is None:
        await state.clear()
        await message.answer(
            "❌ Нет доступа!\n\nОткройте таблицу → Настройки доступа → добавьте редактором:\n"
            "`task-bot@task-bot-499810.iam.gserviceaccount.com`\n\nЗатем повторите /addproject",
            parse_mode="Markdown"
        )
        return
    project_id = add_project(name, spreadsheet_id)
    await state.clear()
    await message.answer(f"✅ Проект *{name}* подключён!", parse_mode="Markdown")


# ─── /help ─────────────────────────────────────────────────────────────────
@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "📖 *Справка:*\n\n"
        "/newtask — создать задачу (AI заполнит, вы отредактируете кнопками)\n"
        "/tasks — список задач\n"
        "/done <ID> — отметить выполненной\n"
        "/overdue — просроченные во всех проектах\n"
        "/projects — список проектов\n"
        "/addproject — подключить Google таблицу\n\n"
        "Уведомления о просрочке — каждый день в 09:00 МСК.",
        parse_mode="Markdown"
    )
