from datetime import datetime
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import (add_task, get_tasks, update_status, get_projects,
                      add_project, get_overdue_tasks, get_stats,
                      register_user, get_user_by_name, get_conn,
                      add_task_comment, get_task_comments,
                      get_task_history, log_task_change, get_managers,
                      trash_task, get_trashed_tasks, restore_from_trash,
                      get_task, get_all_users, complete_task_by_employee,
                      confirm_task_by_director, return_task_for_rework)

logger = logging.getLogger(__name__)
router = Router()


class TaskCreation(StatesGroup):
    waiting_for_text = State()
    editing_field = State()
    choosing_project = State()
    choosing_assignee = State()
    confirming = State()
    confirming_multiple = State()
    correcting_field_multiple = State()
    editing_one_of_multiple = State()
    editing_one_field = State()


class ProjectAdding(StatesGroup):
    waiting_for_name = State()


class TaskEditing(StatesGroup):
    choosing_field = State()
    editing_field = State()
    choosing_project = State()


class TaskCommenting(StatesGroup):
    waiting_for_comment = State()
    waiting_for_file = State()


class TaskCompletionReport(StatesGroup):
    waiting_for_report = State()


class ReworkComment(StatesGroup):
    waiting_for_comment = State()


FIELD_LABELS = {
    "title": "Задача",
    "assignee": "Ответственный",
    "department": "Отдел",
    "project": "Проект",
    "deadline": "Срок",
    "comment": "Комментарий",
}


ADMINS_FULL_ACCESS = ("Камалов", "Абдуллах")  # видят ВСЕ задачи (активные и просроченные), а не только свои


def sees_all_tasks(name):
    """True, если сотрудник имеет полный доступ ко всем задачам."""
    n = (name or "").lower()
    return any(a.lower() in n for a in ADMINS_FULL_ACCESS)


def is_my_task(task, name):
    """True, если задача назначена данному пользователю.
    Учитывает несколько ответственных через запятую и сравнивает по фамилии точно."""
    if not name or not name.strip():
        return False
    assignee = (task.get("assignee") or "").lower()
    if not assignee:
        return False
    name_l = name.lower().strip()
    my_surname = name_l.split()[0]
    # Разбиваем список ответственных (может быть несколько через запятую)
    for p in [x.strip() for x in assignee.split(",") if x.strip()]:
        # точное вхождение полного имени в любую сторону
        if name_l in p or p in name_l:
            return True
        # сравнение по фамилии как первому слову
        p_words = p.split()
        if p_words and my_surname == p_words[0]:
            return True
    return False


def format_overdue_grouped(tasks):
    """Читаемый список просроченных задач для руководителя.

    Формат каждой задачи:
        🔴 #ID Название задачи
        📁 Проект
        👤 Ответственный
        📅 Дедлайн (просрочено N дн.)
    Задачи разделены горизонтальной линией.
    """
    if not tasks:
        return ["✅ Просроченных задач нет!"]

    today = datetime.now()
    sep = "━━━━━━━━━━━━━━━━━━━━━━"

    # Сортируем по давности просрочки: сначала самые старые
    def overdue_days(t):
        dl = t.get("deadline") or ""
        try:
            return (today - datetime.strptime(dl, "%Y-%m-%d")).days
        except ValueError:
            return -1

    tasks_sorted = sorted(tasks, key=overdue_days, reverse=True)

    lines = [f"⚠️ *ПРОСРОЧЕННЫЕ ЗАДАЧИ — {len(tasks)}*", sep]
    for t in tasks_sorted:
        title = t.get("title") or "Без названия"
        proj = t.get("project") or "Без проекта"
        who = t.get("assignee") or "—"
        dl = t.get("deadline") or "—"

        days = overdue_days(t)
        if days > 0:
            overdue_note = f" _(просрочено {days} {_days_word(days)})_"
        else:
            overdue_note = ""

        lines.append(f"🔴 *#{t['id']} {title}*")
        lines.append(f"📁 {proj}")
        lines.append(f"👤 {who}")
        lines.append(f"📅 {dl}{overdue_note}")
        lines.append(sep)

    return lines


def _days_word(n):
    """Склонение слова «день» для числа."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return "дн."
    last = n % 10
    if last == 1:
        return "день"
    if 2 <= last <= 4:
        return "дня"
    return "дн."


async def _send_long(target, lines, header_kept=True):
    """Отправляет длинный список, разбивая на части ~3500 символов (лимит Telegram 4096)."""
    chunk = []
    size = 0
    for line in lines:
        if size + len(line) > 3500 and chunk:
            await target.answer("\n".join(chunk), parse_mode="Markdown")
            chunk = []
            size = 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        await target.answer("\n".join(chunk), parse_mode="Markdown")

# Список руководителей теперь хранится в БД (таблица managers).
# Изменения через веб-дашборд /managers сразу отражаются в боте.


def managers_keyboard():
    """Клавиатура выбора ответственного из списка руководителей."""
    buttons = []
    row = []
    for i, name in enumerate(get_managers()):
        row.append(InlineKeyboardButton(text=name, callback_data=f"mgr_{i}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✏️ Ввести вручную", callback_data="mgr_manual")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def notify_assignee(bot: Bot, assignee: str, title: str, project: str, deadline: str, task_id: int = 0):
    """Уведомляет всех ответственных (поддерживает несколько через запятую)."""
    if not assignee:
        return
    assignees = [a.strip() for a in assignee.split(",") if a.strip()]
    for name in assignees:
        user = get_user_by_name(name)
        if not user:
            continue
        try:
            done_hint = f"\n\n/done {task_id} — отметить выполненной" if task_id else ""
            await bot.send_message(
                user["telegram_id"],
                f"📌 *Вам назначена задача!*\n\n"
                f"📋 *Задача:* {title}\n"
                f"📁 *Проект:* {project or '—'}\n"
                f"📅 *Срок:* {deadline or '—'}"
                f"{done_hint}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления {name}: {e}")


def task_keyboard(parsed):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, создать", callback_data="confirm_task")],
        [InlineKeyboardButton(text="✏️ Изменить", callback_data="edit_task_open")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task")],
    ])


def task_edit_keyboard(parsed):
    def btn(key, label):
        v = parsed.get(key) or "—"
        if len(v) > 22: v = v[:22] + "…"
        return InlineKeyboardButton(text=f"✏️ {label}: {v}", callback_data=f"edit_{key}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("title", "Название")],
        [btn("assignee", "Ответственный")],
        [btn("project", "Проект")],
        [btn("deadline", "Срок")],
        [btn("department", "Отдел")],
        [InlineKeyboardButton(text="✅ Сохранить", callback_data="confirm_task"),
         InlineKeyboardButton(text="◀️ Назад", callback_data="edit_task_back")],
    ])


def edit_task_keyboard(task_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Изменить задачу", callback_data=f"etask_title_{task_id}")],
        [InlineKeyboardButton(text="👤 Изменить ответственного", callback_data=f"etask_assignee_{task_id}")],
        [InlineKeyboardButton(text="🏢 Изменить отдел", callback_data=f"etask_department_{task_id}")],
        [InlineKeyboardButton(text="📅 Изменить срок", callback_data=f"etask_deadline_{task_id}")],
        [InlineKeyboardButton(text="📁 Изменить проект", callback_data=f"etask_project_{task_id}")],
        [InlineKeyboardButton(text="💬 Изменить комментарий", callback_data=f"etask_comment_{task_id}")],
        [InlineKeyboardButton(text="🗑 Удалить задачу", callback_data=f"etask_delete_{task_id}")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_task")],
    ])


def mytask_keyboard(task_id, status=None):
    buttons = []
    if status not in ("На проверке", "Выполнена", "Архив", "Корзина"):
        buttons.append([InlineKeyboardButton(text="✅ Завершить задачу", callback_data=f"empdone_{task_id}")])
    buttons += [
        [InlineKeyboardButton(text="💬 Написать комментарий", callback_data=f"addcomment_{task_id}")],
        [InlineKeyboardButton(text="📎 Прикрепить файл", callback_data=f"addfile_{task_id}")],
        [InlineKeyboardButton(text="📋 История комментариев", callback_data=f"viewcomments_{task_id}")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="cancel_task")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
    deadline = parsed.get("deadline") or "—"
    assignee = parsed.get("assignee") or "—"
    project = parsed.get("project") or "—"
    desc = parsed.get("description") or ""
    lines = [
        f"📋 *Задача распознана:*\n",
        f"📌 *{parsed.get('title') or '—'}*",
    ]
    if desc and desc != parsed.get("title"):
        lines.append(f"\n_{desc[:150]}_")
    lines += [
        f"\n👤 Ответственный: {assignee}",
        f"📅 Срок: {deadline}",
        f"📁 Проект: {project}",
        f"\n✅ *Всё верно?*"
    ]
    return "\n".join(lines)


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
    status = t.get('status') or '—'
    status_note = ""
    if status == "На проверке":
        status_note = "\n⏳ _Ожидает подтверждения директора_"
    elif status == "На доработке":
        status_note = "\n↩️ _Возвращена на доработку_"
    return (
        f"📋 *Задача #{t['id']}:*\n\n"
        f"📌 {t.get('title') or '—'}\n"
        f"📁 *Проект:* {t.get('project') or '—'}\n"
        f"📅 *Срок:* {t.get('deadline') or '—'}\n"
        f"🔵 *Статус:* {status}{status_note}\n"
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


# ─── /start ─────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM users WHERE telegram_id=?", (message.from_user.id,)).fetchone()

    if existing:
        await _show_main_menu(message, existing["name"])
        await _send_my_tasks(message, existing["name"])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"reg_{i}")]
            for i, name in enumerate(get_managers())
        ] + [[InlineKeyboardButton(text="✏️ Ввести своё имя", callback_data="reg_manual")]])
        await message.answer(
            "👋 Добро пожаловать!\n\nВыберите своё имя из списка чтобы зарегистрироваться:",
            reply_markup=keyboard
        )


async def _show_main_menu(message, name: str):
    menu = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Новая задача", callback_data="menu_newtask")],
        [InlineKeyboardButton(text="📋 Мои задачи", callback_data="menu_mytasks"),
         InlineKeyboardButton(text="📊 Дашборд", callback_data="menu_dashboard")],
        [InlineKeyboardButton(text="✅ Выполненные", callback_data="menu_done"),
         InlineKeyboardButton(text="⚠️ Просроченные", callback_data="menu_overdue")],
        [InlineKeyboardButton(text="📎 Прикрепить файл", callback_data="menu_attach")],
        [InlineKeyboardButton(text="📁 Проекты", callback_data="menu_projects"),
         InlineKeyboardButton(text="🆕 Новый проект", callback_data="menu_newproject")],
    ])
    await message.answer(
        f"👋 Добро пожаловать, *{name}*!\n\nЧто хотите сделать?",
        reply_markup=menu,
        parse_mode="Markdown"
    )


async def _send_my_tasks(message, name: str):
    all_tasks = get_tasks()
    seen, active = set(), []
    full = sees_all_tasks(name)
    for t in all_tasks:
        mine = True if full else is_my_task(t, name)
        if mine and t.get("status") not in ("Выполнена",) and t["title"] not in seen:
            seen.add(t["title"])
            active.append(t)
    if not active:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    header = "Все активные задачи" if full else "Ваши активные задачи"
    lines = [f"📋 *{header} ({len(active)}):*\n"]
    for t in active:
        dl = t.get("deadline") or "—"
        flag = " 🔴 *ПРОСРОЧЕНА*" if dl != "—" and dl < today else ""
        lines.append(f"• *#{t['id']}* {t['title'][:50]}{flag}\n  📅 {dl} | /done {t['id']}")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@router.callback_query(F.data.startswith("reg_"))
async def handle_registration(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    choice = callback.data.replace("reg_", "")
    if choice == "manual":
        await state.set_state(TaskCreation.editing_field)
        await state.update_data(editing="reg_name")
        await callback.message.answer("✏️ Введите ваше имя (например: Луданная Л.):")
        return
    try:
        idx = int(choice)
        name = get_managers()[idx]
    except (ValueError, IndexError):
        name = choice
    register_user(callback.from_user.id, name)
    await callback.message.answer(f"✅ Вы зарегистрированы как *{name}*!", parse_mode="Markdown")
    await _show_main_menu(callback.message, name)
    await _send_my_tasks(callback.message, name)

@router.callback_query(F.data.startswith("menu_"))
async def handle_menu(callback: CallbackQuery, state: FSMContext):
    action = callback.data.replace("menu_", "")
    await callback.answer()
    if action == "newtask":
        await state.set_state(TaskCreation.waiting_for_text)
        await callback.message.answer("📝 Опишите задачу — кому, что и к какому сроку:")
    elif action == "mytasks":
        with get_conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (callback.from_user.id,)).fetchone()
        if not user:
            await callback.message.answer("❌ Вы не зарегистрированы. Напишите /start")
            return
        name = user["name"]
        all_tasks = get_tasks()
        if sees_all_tasks(name):
            my_tasks = [t for t in all_tasks if t.get("status") != "Выполнена"]
            header = "📋 *Все активные задачи*"
        else:
            my_tasks = [t for t in all_tasks if is_my_task(t, name)
                        and t.get("status") != "Выполнена"]
            header = f"📋 *Ваши задачи, {name}*"
        if not my_tasks:
            await callback.message.answer("✅ Активных задач нет!")
            return
        # Отправляем каждую задачу отдельным сообщением с кнопками
        await callback.message.answer(f"{header}:")
        for t in my_tasks[:10]:
            emoji = {"Открыта": "🔵", "В работе": "🟡", "Выполнена": "🟢", "На проверке": "🟣", "На доработке": "🟠"}.get(t.get("status", ""), "⚪")
            await callback.message.answer(
                f"{emoji} {format_my_task(t)}",
                reply_markup=mytask_keyboard(t["id"], t.get("status")),
                parse_mode="Markdown"
            )
    elif action == "dashboard":
        from config import RAILWAY_PUBLIC_DOMAIN
        url = f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN else "Дашборд недоступен"
        await callback.message.answer(
            f"📊 *Дашборд:*\n{url}",
            parse_mode="Markdown"
        )
    elif action == "done":
        with get_conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (callback.from_user.id,)).fetchone()
        if not user:
            await callback.message.answer("❌ Вы не зарегистрированы. Напишите /start")
            return
        name = user["name"]
        all_tasks = get_tasks()
        if sees_all_tasks(name):
            done_tasks = [t for t in all_tasks if t.get("status") == "Выполнена"]
            header = "✅ *Все выполненные задачи:*\n"
        else:
            done_tasks = [t for t in all_tasks if is_my_task(t, name)
                          and t.get("status") == "Выполнена"]
            header = f"✅ *Выполненные задачи, {name}:*\n"
        if not done_tasks:
            await callback.message.answer("Выполненных задач пока нет.")
            return
        lines = [header]
        for t in done_tasks[-10:]:
            lines.append(f"✅ *#{t['id']}* {t['title'][:50]} | 👤 {t.get('assignee') or '—'}")
        await _send_long(callback.message, lines)
    elif action == "overdue":
        with get_conn() as conn:
            user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (callback.from_user.id,)).fetchone()
        if not user:
            await callback.message.answer("❌ Вы не зарегистрированы. Напишите /start")
            return
        name = user["name"]
        if sees_all_tasks(name):
            tasks = get_overdue_tasks()
        else:
            tasks = [t for t in get_overdue_tasks() if is_my_task(t, name)]
        if not tasks:
            await callback.message.answer("✅ Просроченных задач нет!")
            return
        lines = format_overdue_grouped(tasks)
        await _send_long(callback.message, lines)
    elif action == "attach":
        projects = get_projects()
        if not projects:
            await callback.message.answer("📁 Проектов пока нет.")
            await callback.answer()
            return
        buttons = [[InlineKeyboardButton(text=f"📁 {p['name']}", callback_data=f"attach_proj_{p['name']}")] for p in projects]
        buttons.append([InlineKeyboardButton(text="📋 Все задачи", callback_data="attach_proj_ALL")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task")])
        await callback.message.answer(
            "📎 Выберите проект:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
    elif action == "projects":
        projects = get_projects()
        if not projects:
            await callback.message.answer("Проектов пока нет. Нажмите 🆕 Новый проект.")
            return
        lines = ["📁 *Проекты:*\n"]
        for p in projects:
            lines.append(f"• {p['name']}")
        await callback.message.answer("\n".join(lines), parse_mode="Markdown")
    elif action == "newproject":
        await state.set_state(ProjectAdding.waiting_for_name)
        await callback.message.answer("📁 Введите название нового проекта:")


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    from config import RAILWAY_PUBLIC_DOMAIN
    url = f"https://{RAILWAY_PUBLIC_DOMAIN}" if RAILWAY_PUBLIC_DOMAIN else "http://localhost:8080"
    await message.answer(f"📊 [Открыть дашборд]({url})", parse_mode="Markdown")


# ─── /register ─────────────────────────────────────────────────────────────
@router.message(Command("register"))
async def cmd_register(message: Message):
    """Регистрация всегда через выбор фамилии из списка сотрудников —
    это гарантирует связку с задачами, даже если в Telegram у человека
    указано другое имя/ник."""
    managers = get_managers()
    parts = message.text.split(maxsplit=1)
    typed = parts[1].strip() if len(parts) >= 2 else ""

    # Если ввели текст — пробуем сопоставить его с реальным сотрудником по фамилии
    if typed:
        typed_l = typed.lower()
        typed_surname = typed_l.split()[0] if typed_l.split() else ""
        match = None
        for m in managers:
            m_l = m.lower()
            if typed_l in m_l or m_l in typed_l or (typed_surname and typed_surname == m_l.split()[0]):
                match = m
                break
        if match:
            register_user(message.from_user.id, match)
            await message.answer(
                f"✅ Зарегистрированы как *{match}*!\n"
                f"Уведомления будут приходить сюда.",
                parse_mode="Markdown"
            )
            return
        # Совпадения нет — не сохраняем произвольный текст, просим выбрать кнопкой
        await message.answer(
            f"⚠️ Не нашёл сотрудника «{typed}» в списке.\n"
            f"Пожалуйста, выберите свою фамилию из списка ниже:"
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"reg_{i}")]
        for i, name in enumerate(managers)
    ])
    await message.answer(
        "👤 Выберите своё имя из списка чтобы зарегистрироваться:",
        reply_markup=keyboard
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
    if sees_all_tasks(name):
        my_tasks = all_tasks
    else:
        my_tasks = [t for t in all_tasks if is_my_task(t, name)]
    if not my_tasks:
        await message.answer(f"📋 У вас нет задач, *{name}*.", parse_mode="Markdown")
        return
    for t in my_tasks[:10]:
        emoji = {"Открыта": "🔵", "В работе": "🟡", "Выполнена": "🟢", "На проверке": "🟣", "На доработке": "🟠"}.get(t.get("status", ""), "⚪")
        await message.answer(
            f"{emoji} {format_my_task(t)}",
            reply_markup=mytask_keyboard(t["id"], t.get("status")),
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
    
    # Если сообщение пустое — просим повторить
    if not message.text or not message.text.strip():
        await message.answer("❌ Напишите комментарий (не пустое сообщение)")
        return
    
    with get_conn() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE telegram_id=?",
            (message.from_user.id,)
        ).fetchone()
    author = user["name"] if user else message.from_user.first_name or "Неизвестно"
    add_task_comment(task_id=task_id, author=author, text=message.text.strip())
    
    # Очищаем состояние и закрываем режим
    await state.clear()
    await message.answer(f"✅ Комментарий к задаче #{task_id} сохранён!")


# ─── Файл к задаче ──────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("addfile_"))
async def add_file_start(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("addfile_", ""))
    await state.update_data(commenting_task_id=task_id)
    await state.set_state(TaskCommenting.waiting_for_file)
    await callback.message.answer("📎 Отправьте файл или фото:")
    await callback.answer()




# ─── Выбор задачи для прикрепления файла ────────────────────────────────────
@router.callback_query(F.data.startswith("attach_pick_"))
async def attach_pick_task(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("attach_pick_", ""))
    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        await callback.answer("Задача не найдена")
        return
    await state.update_data(commenting_task_id=task_id)
    await state.set_state(TaskCommenting.waiting_for_file)
    title = task["title"][:60] + "..." if len(task["title"]) > 60 else task["title"]
    await callback.message.edit_text(
        f"📎 Прикрепляем файл к задаче *#{task_id}:*\n_{title}_\n\nОтправьте файл, фото или видео:",
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(TaskCommenting.waiting_for_file)
async def save_file(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("commenting_task_id")
    if not task_id:
        await message.answer("❌ Задача не выбрана. Используйте /attach для прикрепления файла.")
        await state.clear()
        return
    
    # Если это пустое текстовое сообщение без файла — ничего не делаем
    if not message.document and not message.photo and not message.video:
        await message.answer("❌ Поддерживаются файлы, фото и видео.")
        return
    
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
    
    # Сохраняем файл
    add_task_comment(task_id=task_id, author=author, text=caption, file_id=file_id, file_name=file_name, file_type=file_type)
    
    # Очищаем состояние и закрываем режим
    await state.clear()
    
    from config import RAILWAY_PUBLIC_DOMAIN
    dash_url = f"https://{RAILWAY_PUBLIC_DOMAIN}/attach/{task_id}" if RAILWAY_PUBLIC_DOMAIN else ""
    link = f"\n[Посмотреть в дашборде]({dash_url})" if dash_url else ""
    await message.answer(
        f"✅ *{file_name}* прикреплён к задаче *#{task_id}*!{link}",
        parse_mode="Markdown",
        disable_web_page_preview=True
    )


# ─── История комментариев ───────────────────────────────────────────────────
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
            lines.append(f"💬 *{c['author']}* [{time}]: {c.get('text', '')}")
    await callback.message.answer("\n".join(lines), parse_mode="Markdown")
    await callback.answer()


# ─── Редактирование задач ДО сохранения ─────────────────────────────────────
@router.callback_query(F.data == "edit_tasks_list", TaskCreation.confirming_multiple)
async def edit_tasks_list(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    tasks = data["multiple_tasks"]
    await state.update_data(editing_task_idx=0)
    await state.set_state(TaskCreation.editing_one_of_multiple)
    await callback.message.answer(
        format_one_of_multiple(tasks[0], 0, len(tasks)),
        reply_markup=edit_one_of_multiple_keyboard(0),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("eom_"), TaskCreation.editing_one_of_multiple)
async def eom_choose_field(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    action = parts[1]
    data = await state.get_data()
    tasks = data["multiple_tasks"]
    task_idx = data.get("editing_task_idx", 0)

    if action == "done":
        next_idx = task_idx + 1
        if next_idx < len(tasks):
            await state.update_data(editing_task_idx=next_idx)
            await callback.message.answer(
                format_one_of_multiple(tasks[next_idx], next_idx, len(tasks)),
                reply_markup=edit_one_of_multiple_keyboard(next_idx),
                parse_mode="Markdown"
            )
        else:
            await show_multiple_preview(callback, state)
        await callback.answer()
        return

    await state.update_data(eom_field=action, editing_task_idx=task_idx)
    await state.set_state(TaskCreation.editing_one_field)
    labels = {
        "title": "новое название задачи",
        "assignee": "ответственного",
        "deadline": "срок (например: 30.06.2026)",
    }
    await callback.message.answer(f"✏️ Введите {labels.get(action, action)}:")
    await callback.answer()


@router.message(TaskCreation.editing_one_field)
async def eom_save_field(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("eom_field")
    task_idx = data.get("editing_task_idx", 0)
    tasks = data["multiple_tasks"]
    value = message.text.strip()
    if field == "deadline":
        value = await parse_deadline(value) or value
    tasks[task_idx][field] = value
    await state.update_data(multiple_tasks=tasks)
    await state.set_state(TaskCreation.editing_one_of_multiple)
    await message.answer(
        format_one_of_multiple(tasks[task_idx], task_idx, len(tasks)),
        reply_markup=edit_one_of_multiple_keyboard(task_idx),
        parse_mode="Markdown"
    )


# ─── /editall ────────────────────────────────────────────────────────────────
@router.message(Command("editall"))
async def cmd_editall(message: Message, state: FSMContext):
    projects = get_projects()
    if not projects:
        await message.answer("📋 Задач нет. /newtask")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📁 {p['name']}", callback_data=f"editall_{i}")] for i, p in enumerate(projects)
    ])
    await message.answer("📁 Выберите проект для редактирования:", reply_markup=kb)

@router.callback_query(F.data.startswith("editall_"))
async def editall_choose_project(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.replace("editall_", ""))
    projects = get_projects()
    try:
        project = projects[idx]["name"]
    except IndexError:
        await callback.answer()
        return
    tasks = get_tasks(project=project)
    if not tasks:
        await callback.message.answer(f"📋 В *{project}* задач нет.", parse_mode="Markdown")
        await callback.answer()
        return
    await callback.message.answer(f"✏️ *Задачи проекта {project}:*\n\nНажмите на задачу чтобы редактировать:", parse_mode="Markdown")
    for t in tasks[:20]:
        emoji = {"Открыта": "🔵", "В работе": "🟡", "Выполнена": "🟢"}.get(t.get("status", ""), "⚪")
        title = t['title'][:50] + "..." if len(t['title']) > 50 else t['title']
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"quickedit_{t['id']}")]
        ])
        await callback.message.answer(
            f"{emoji} *#{t['id']}* {title}\n👤 {t['assignee'] or '—'} | 📅 {t['deadline'] or '—'}",
            reply_markup=kb,
            parse_mode="Markdown"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("quickedit_"))
async def quickedit_task(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("quickedit_", ""))
    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        await callback.message.answer(f"❌ Задача #{task_id} не найдена.")
        await callback.answer()
        return
    await state.update_data(editing_task_id=task_id)
    await state.set_state(TaskEditing.choosing_field)
    await callback.message.answer(
        format_existing_task(task),
        reply_markup=edit_task_keyboard(task_id),
        parse_mode="Markdown"
    )
    await callback.answer()


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

    if field == "delete":
        trash_task(int(task_id))
        await state.clear()
        await callback.message.edit_text(f"🗑 Задача #{task_id} перемещена в корзину.\nВосстановить: /trash")
        await callback.answer()
        return

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
        "department": "отдел",
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



# ─── /attach <ID> — прикрепить файл к задаче напрямую ──────────────────────
@router.message(Command("attach"))
async def cmd_attach(message: Message, state: FSMContext):
    parts = message.text.split()
    tasks = get_tasks()
    # Если ID указан — прикрепляем сразу
    if len(parts) >= 2 and parts[1].isdigit():
        task_id = int(parts[1])
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return
        await state.update_data(commenting_task_id=task_id)
        await state.set_state(TaskCommenting.waiting_for_file)
        title = task["title"][:60] + "..." if len(task["title"]) > 60 else task["title"]
        await message.answer(
            f"📎 Прикрепляем файл к задаче *#{task_id}:*\n_{title}_\n\nОтправьте файл, фото или видео:",
            parse_mode="Markdown"
        )
        return
    # Показываем список проектов
    projects = get_projects()
    if not projects:
        await message.answer("📁 Проектов пока нет.")
        return
    buttons = [[InlineKeyboardButton(text=f"📁 {p['name']}", callback_data=f"attach_proj_{p['name']}")] for p in projects]
    buttons.append([InlineKeyboardButton(text="📋 Все задачи", callback_data="attach_proj_ALL")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task")])
    await message.answer(
        "📎 Выберите проект:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# ─── /comment <ID> — добавить комментарий к задаче напрямую ─────────────────
@router.message(Command("comment"))
async def cmd_comment(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "💬 Укажите ID задачи:\n"
            "Например: /comment 15\n\n"
            "ID задачи можно найти в дашборде или командой /tasks"
        )
        return
    task_id = int(parts[1])
    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        await message.answer(f"❌ Задача #{task_id} не найдена.")
        return
    await state.update_data(commenting_task_id=task_id)
    await state.set_state(TaskCommenting.waiting_for_comment)
    title = task["title"][:60] + "..." if len(task["title"]) > 60 else task["title"]
    await message.answer(
        f"💬 Комментарий к задаче *#{task_id}*:\n_{title}_\n\nНапишите ваш комментарий:",
        parse_mode="Markdown"
    )


# ─── /delete — переместить в корзину ────────────────────────────────────────
@router.message(Command("delete"))
async def cmd_delete(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Укажите ID задачи: /delete 5")
        return
    task_id = int(parts[1])
    with get_conn() as conn:
        exists = conn.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not exists:
        await message.answer(f"❌ Задача #{task_id} не найдена.")
        return
    trash_task(task_id)
    await message.answer(f"🗑 Задача #{task_id} перемещена в корзину.\nВосстановить: /trash")


# ─── /trash — корзина: показать и восстановить ──────────────────────────────
@router.message(Command("trash"))
async def cmd_trash(message: Message):
    parts = message.text.split()
    # /trash restore <id> — восстановить задачу
    if len(parts) >= 3 and parts[1] == "restore" and parts[2].isdigit():
        task_id = int(parts[2])
        restore_from_trash(task_id)
        await message.answer(f"↩️ Задача #{task_id} восстановлена (статус «Открыта»).")
        return
    # /trash — список задач в корзине
    tasks = get_trashed_tasks()
    if not tasks:
        await message.answer("🗑 Корзина пуста.")
        return
    lines = ["🗑 *Корзина:*\n"]
    for t in tasks[:30]:
        lines.append(
            f"#{t['id']} {t['title'][:50]}\n"
            f"   📁 {t.get('project') or '—'} | 👤 {t.get('assignee') or '—'}\n"
            f"   ↩️ Восстановить: /trash restore {t['id']}"
        )
    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─── /newtask ────────────────────────────────────────────────────────────────
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


# ─── Выбор проекта ───────────────────────────────────────────────────────────
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


# ─── Кнопки изменения ────────────────────────────────────────────────────────
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
    await state.set_state(TaskCreation.choosing_assignee)
    await callback.message.answer("👤 Выберите ответственного:", reply_markup=managers_keyboard())
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


# ─── Сохранение нескольких задач ─────────────────────────────────────────────
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
        await notify_assignee(callback.bot, final_assignee, title, project, final_deadline, task_id)
        saved += 1
    await state.clear()
    await callback.message.edit_text(
        f"✅ Сохранено *{saved} задач* в проект *{project}*!",
        parse_mode="Markdown"
    )
    await callback.answer()


# ─── Редактирование одной задачи (при создании) ─────────────────────────────
@router.callback_query(F.data == "edit_task_open", TaskCreation.confirming)
async def open_edit_form(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    parsed = data.get("parsed", {})
    await callback.message.edit_text(format_task_text(parsed), reply_markup=task_edit_keyboard(parsed), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "edit_task_back", TaskCreation.confirming)
async def back_to_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    parsed = data.get("parsed", {})
    await callback.message.edit_text(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")
    await callback.answer()


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
    if field == "assignee":
        await state.update_data(editing=field)
        await state.set_state(TaskCreation.choosing_assignee)
        await callback.message.answer("👤 Выберите ответственного:", reply_markup=managers_keyboard())
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
    await notify_assignee(callback.bot, assignee, title, project, deadline, task_id)
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


# ─── /tasks ──────────────────────────────────────────────────────────────────
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
    await callback.message.answer(f"📁 *{project}:*", parse_mode="Markdown")
    for t in tasks[:15]:
        emoji = {"Открыта": "🔵", "В работе": "🟡", "Выполнена": "🟢"}.get(t.get("status", ""), "⚪")
        title = t['title'][:50] + "..." if len(t['title']) > 50 else t['title']
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"quickedit_{t['id']}")]
        ])
        await callback.message.answer(
            f"{emoji} *#{t['id']}* {title}\n👤 {t['assignee'] or '—'} | 📅 {t['deadline'] or '—'}",
            reply_markup=kb,
            parse_mode="Markdown"
        )
    await callback.answer()


# ─── /done ───────────────────────────────────────────────────────────────────
@router.message(Command("done"))
async def cmd_done(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Укажите ID: /done 5")
        return
    task_id = int(parts[1])
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (message.from_user.id,)).fetchone()
    author = user["name"] if user else (message.from_user.first_name or "Неизвестно")
    update_status(task_id, "Выполнена", changed_by=author)
    await message.answer(f"✅ Задача #{task_id} выполнена! Записано: {author}")


# ─── Двухэтапное завершение задачи: сотрудник → проверка директора ─────────
@router.callback_query(F.data.startswith("empdone_"))
async def employee_complete_start(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("empdone_", ""))
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (callback.from_user.id,)).fetchone()
    if not user:
        await callback.answer("Вы не зарегистрированы. Напишите /start", show_alert=True)
        return
    name = user["name"]
    task = get_task(task_id)
    if not task:
        await callback.answer("Задача не найдена.", show_alert=True)
        return
    if not is_my_task(task, name):
        await callback.answer("Это не ваша задача.", show_alert=True)
        return
    if task.get("status") in ("На проверке", "Выполнена", "Архив", "Корзина"):
        await callback.answer("Задача уже отправлена на проверку или завершена.", show_alert=True)
        return
    await state.update_data(completing_task_id=task_id)
    await state.set_state(TaskCompletionReport.waiting_for_report)
    await callback.message.answer(
        f"✅ *Завершение задачи #{task_id}:* {task['title'][:80]}\n\n"
        f"Напишите комментарий о выполненной работе — можно приложить файл, фото или ссылку одним сообщением:",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(TaskCompletionReport.waiting_for_report)
async def employee_complete_save(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("completing_task_id")
    if not task_id:
        await state.clear()
        return
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (message.from_user.id,)).fetchone()
    author = user["name"] if user else (message.from_user.first_name or "Неизвестно")

    task = get_task(task_id)
    if not task or task.get("status") in ("На проверке", "Выполнена", "Архив", "Корзина"):
        await message.answer("⚠️ Задача уже обработана.")
        await state.clear()
        return

    file_id = file_name = file_type = ""
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

    report_text = (message.text or message.caption or "").strip()
    add_task_comment(
        task_id=task_id, author=author,
        text=f"✅ Отчёт о выполнении: {report_text}" if report_text else "✅ Отчёт о выполнении",
        file_id=file_id, file_name=file_name, file_type=file_type
    )
    complete_task_by_employee(task_id, author)
    await state.clear()

    await message.answer(
        f"✅ Задача *#{task_id}* отправлена на проверку директору.",
        parse_mode="Markdown"
    )

    # Уведомляем директора(ов) — с кнопками подтверждения/возврата
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить выполнение", callback_data=f"dirconfirm_{task_id}")],
        [InlineKeyboardButton(text="↩️ Вернуть на доработку", callback_data=f"dirrework_{task_id}")],
    ])
    attach_note = f"\n📎 Приложен файл: {file_name}" if file_id else ""
    director_text = (
        f"📋 *Сотрудник завершил задачу и отправил её на проверку*\n\n"
        f"📌 *Задача:* {task['title']}\n"
        f"📁 *Проект:* {task.get('project') or '—'}\n"
        f"👤 *Ответственный:* {author}\n"
        f"📅 *Дата завершения:* {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"💬 *Комментарий:* {report_text or '—'}"
        f"{attach_note}"
    )
    try:
        directors = [u for u in get_all_users() if sees_all_tasks(u["name"])]
    except Exception:
        directors = []
    for u in directors:
        try:
            if file_id and file_type == "photo":
                await message.bot.send_photo(u["telegram_id"], file_id, caption=director_text, reply_markup=kb, parse_mode="Markdown")
            elif file_id and file_type == "video":
                await message.bot.send_video(u["telegram_id"], file_id, caption=director_text, reply_markup=kb, parse_mode="Markdown")
            elif file_id:
                await message.bot.send_document(u["telegram_id"], file_id, caption=director_text, reply_markup=kb, parse_mode="Markdown")
            else:
                await message.bot.send_message(u["telegram_id"], director_text, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка уведомления директора {u['name']}: {e}")


@router.callback_query(F.data.startswith("dirconfirm_"))
async def director_confirm(callback: CallbackQuery):
    task_id = int(callback.data.replace("dirconfirm_", ""))
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (callback.from_user.id,)).fetchone()
    name = user["name"] if user else ""
    if not sees_all_tasks(name):
        await callback.answer("Только директор может подтверждать выполнение.", show_alert=True)
        return
    task = get_task(task_id)
    if not task or task.get("status") != "На проверке":
        await callback.answer("Задача уже обработана.", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    confirm_task_by_director(task_id, name)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer("Подтверждено")
    await callback.message.answer(f"✅ Задача #{task_id} подтверждена и перемещена в архив.")

    assignee = task.get("assignee") or ""
    for nm in [a.strip() for a in assignee.split(",") if a.strip()]:
        u = get_user_by_name(nm)
        if u:
            try:
                await callback.bot.send_message(
                    u["telegram_id"],
                    f"✅ Директор *{name}* подтвердил выполнение задачи *#{task_id}*: {task['title'][:80]}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления сотрудника о подтверждении: {e}")


@router.callback_query(F.data.startswith("dirrework_"))
async def director_rework_start(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("dirrework_", ""))
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (callback.from_user.id,)).fetchone()
    name = user["name"] if user else ""
    if not sees_all_tasks(name):
        await callback.answer("Только директор может возвращать задачу на доработку.", show_alert=True)
        return
    task = get_task(task_id)
    if not task or task.get("status") != "На проверке":
        await callback.answer("Задача уже обработана.", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await state.update_data(rework_task_id=task_id, rework_director=name)
    await state.set_state(ReworkComment.waiting_for_comment)
    await callback.message.answer(f"✏️ Укажите комментарий — что нужно доработать в задаче #{task_id} (обязательно):")
    await callback.answer()


@router.message(ReworkComment.waiting_for_comment)
async def director_rework_save(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get("rework_task_id")
    director_name = data.get("rework_director", "")
    comment = (message.text or "").strip()
    if not task_id:
        await state.clear()
        return
    if not comment:
        await message.answer("⚠️ Комментарий обязателен. Напишите, что нужно доработать:")
        return
    task = get_task(task_id)
    if not task or task.get("status") != "На проверке":
        await message.answer("⚠️ Задача уже обработана.")
        await state.clear()
        return
    return_task_for_rework(task_id, comment, director_name)
    await state.clear()
    await message.answer(f"↩️ Задача #{task_id} возвращена на доработку.")

    assignee = task.get("assignee") or ""
    for nm in [a.strip() for a in assignee.split(",") if a.strip()]:
        u = get_user_by_name(nm)
        if u:
            try:
                await message.bot.send_message(
                    u["telegram_id"],
                    f"↩️ *Задача #{task_id} возвращена на доработку*\n\n"
                    f"📌 {task['title'][:80]}\n\n"
                    f"💬 *Комментарий директора:* {comment}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления сотрудника о доработке: {e}")


# ─── /overdue ────────────────────────────────────────────────────────────────
@router.message(Command("overdue"))
async def cmd_overdue(message: Message):
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (message.from_user.id,)).fetchone()
    if not user:
        await message.answer("❌ Вы не зарегистрированы. Напишите /start")
        return
    name = user["name"]
    if sees_all_tasks(name):
        tasks = get_overdue_tasks()
    else:
        tasks = [t for t in get_overdue_tasks() if is_my_task(t, name)]
    if not tasks:
        await message.answer("🎉 Просроченных задач нет!")
        return
    lines = format_overdue_grouped(tasks)
    await _send_long(message, lines)


# ─── /projects ────────────────────────────────────────────────────────────────
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


# ─── /newproject ────────────────────────────────────────────────────────────
@router.message(Command("newproject"))
async def cmd_newproject(message: Message, state: FSMContext):
    await state.set_state(ProjectAdding.waiting_for_name)
    await message.answer("📁 Введите название проекта:")


# ─── Добавление проекта (FSM) ────────────────────────────────────────────────
@router.message(ProjectAdding.waiting_for_name)
async def process_project_name(message: Message, state: FSMContext):
    name = message.text.strip()
    add_project(name)
    await state.clear()
    await message.answer(f"✅ Проект *{name}* создан!", parse_mode="Markdown")


# ─── Универсальный обработчик — любой текст создаёт задачу ──────────────────
# Срабатывает только когда нет активного FSM состояния и это не команда
@router.message(F.text, ~F.text.startswith("/"))
async def universal_task_creator(message: Message, state: FSMContext):
    """Любое текстовое сообщение без команды → создаёт задачу через AI."""
    current_state = await state.get_state()
    if current_state is not None:
        # Если есть активный FSM — не перехватываем
        return

    # Если ещё не зарегистрирован — не авторегистрируем под именем из Telegram-профиля
    # (это ломает связку с задачами). Просим выбрать фамилию из списка.
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (message.from_user.id,)).fetchone()
    if not user:
        managers = get_managers()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"reg_{i}")]
            for i, name in enumerate(managers)
        ])
        await message.answer(
            "👤 Сначала нужно зарегистрироваться.\nВыберите своё имя из списка:",
            reply_markup=keyboard
        )
        return

    # Парсим задачу через AI
    thinking_msg = await message.answer("🤖 Распознаю задачу...")
    today = datetime.now().strftime("%Y-%m-%d")
    result = await parse_task_with_ai(message.text, today)

    if not result:
        await thinking_msg.delete()
        await message.answer(
            "❌ Не удалось распознать задачу.\n\n"
            "Попробуйте написать по-другому, например:\n"
            "_Маркелова — подготовить отчёт по складу до 30 июня_\n"
            "_Кострыкину исправить баг на сайте срочно_",
            parse_mode="Markdown"
        )
        return

    await thinking_msg.delete()

    # Несколько задач
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
                f"📋 Нашёл *{len(tasks)} задач*. В какой проект добавить?",
                reply_markup=projects_keyboard(projects),
                parse_mode="Markdown"
            )
        else:
            await state.update_data(selected_project="Общие")
            await show_multiple_preview(message, state)
        return

    # Одна задача — если всё заполнено, сохраняем сразу без подтверждения
    parsed = result
    project = parsed.get("project", "")
    projects = get_projects()

    # Сразу показываем карточку — без промежуточных вопросов
    await state.update_data(parsed=parsed)
    await state.set_state(TaskCreation.confirming)
    await message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")



# ─── Выбор ответственного из списка руководителей ───────────────────────────
@router.callback_query(F.data.startswith("mgr_"), TaskCreation.choosing_assignee)
async def choose_manager(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    parsed = data.get("parsed", {})
    projects = get_projects()

    if callback.data == "mgr_manual":
        await state.set_state(TaskCreation.editing_field)
        await state.update_data(editing="assignee")
        await callback.message.answer("✏️ Введите имя ответственного:")
        await callback.answer()
        return

    idx = int(callback.data.replace("mgr_", ""))
    assignee = get_managers()[idx]
    parsed["assignee"] = assignee
    editing = data.get("editing")
    await state.update_data(parsed=parsed, editing=None)

    # Если пришли из редактирования поля (кнопка в форме подтверждения)
    if editing == "assignee":
        await state.set_state(TaskCreation.confirming)
        await callback.message.answer(format_task_text(parsed), reply_markup=task_keyboard(parsed), parse_mode="Markdown")
        await callback.answer()
        return

    # Если пришли из correcting_field_multiple (несколько задач)
    if data.get("correcting") == "assignee":
        await state.update_data(selected_assignee=assignee, correcting=None)
        await show_multiple_preview(callback, state, edit=True)
        await callback.answer()
        return

    # Если проект не распознан — спрашиваем проект
    if not parsed.get("project") and projects:
        await state.set_state(TaskCreation.choosing_project)
        await callback.message.edit_text(
            f"📌 *{parsed.get('title', '—')}*\n"
            f"👤 {assignee} | 📅 {parsed.get('deadline') or '—'}\n\n"
            "📁 В какой проект?",
            reply_markup=projects_keyboard(projects),
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    # Сохраняем задачу сразу
    project = parsed.get("project") or "Общие"
    task_id = add_task(
        project=project,
        assignee=assignee,
        department=parsed.get("department") or "",
        title=parsed.get("title") or "Без названия",
        deadline=parsed.get("deadline") or "",
        comment=parsed.get("description") or "",
    )
    await notify_assignee(callback.bot, assignee, parsed.get("title") or "", project, parsed.get("deadline") or "", task_id)
    await state.clear()
    await callback.message.edit_text(
        f"✅ *Задача #{task_id} создана!*\n\n"
        f"📌 {parsed.get('title')}\n"
        f"👤 {assignee} | 📁 {project} | 📅 {parsed.get('deadline') or '—'}\n\n"
        f"_Используйте /done {task_id} когда выполните_",
        parse_mode="Markdown"
    )
    await callback.answer()


# ─── /assignees — показать список руководителей ─────────────────────────────
@router.message(Command("assignees"))
async def cmd_assignees(message: Message):
    lines = ["👥 *Список руководителей:*\n"]
    for i, name in enumerate(get_managers(), 1):
        lines.append(f"{i}. {name}")
    await message.answer("\n".join(lines), parse_mode="Markdown")


# ─── /deleteuser — удалить пользователя из базы ─────────────────────────────
@router.message(Command("deleteuser"))
async def cmd_delete_user(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Укажите имя: /deleteuser Фамилия")
        return
    name = parts[1].strip()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users").fetchall()
        found = [dict(r) for r in rows if name.lower() in r["name"].lower()]
        if not found:
            await message.answer(f"❌ Пользователь *{name}* не найден.", parse_mode="Markdown")
            return
        for user in found:
            conn.execute("DELETE FROM users WHERE telegram_id=?", (user["telegram_id"],))
        names = ", ".join(u["name"] for u in found)
    await message.answer(f"✅ Удалено: *{names}*", parse_mode="Markdown")




# ─── Выбор проекта для прикрепления файла ────────────────────────────────────
@router.callback_query(F.data.startswith("attach_proj_"))
async def attach_select_project(callback: CallbackQuery, state: FSMContext):
    proj = callback.data.replace("attach_proj_", "")
    tasks = get_tasks()
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (callback.from_user.id,)).fetchone()
    my_name = user["name"] if user else ""

    active = [t for t in tasks if t["status"] != "Выполнена"]
    if proj != "ALL":
        active = [t for t in active if t.get("project") == proj]

    if my_name:
        my_tasks = [t for t in active if my_name.split()[0].lower() in (t.get("assignee") or "").lower()]
        other_tasks = [t for t in active if t not in my_tasks]
        show_tasks = my_tasks + other_tasks
    else:
        show_tasks = active

    if not show_tasks:
        await callback.message.edit_text(
            "📋 В этом проекте нет активных задач.",
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    buttons = []
    for t in show_tasks[:20]:
        short = t["title"][:40] + "…" if len(t["title"]) > 40 else t["title"]
        who = " (" + t["assignee"].split()[0] + ")" if t.get("assignee") else ""
        buttons.append([InlineKeyboardButton(
            text=f"#{t['id']} {short}{who}",
            callback_data=f"attach_pick_{t['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="menu_attach")])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_task")])

    proj_label = "всех проектов" if proj == "ALL" else proj
    await callback.message.edit_text(
        f"📎 Задачи проекта {proj_label}:\nВыберите задачу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=None
    )
    await callback.answer()
