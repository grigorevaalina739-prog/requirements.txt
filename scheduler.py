import logging
from datetime import datetime, timedelta
from aiogram import Bot
from config import NOTIFY_CHAT_ID
from database import (get_overdue_tasks, get_tasks, get_conn, update_status, get_all_users,
                      get_upcoming_meetings, mark_meeting_reminded)
from agent import generate_overdue_summary

logger = logging.getLogger(__name__)


async def check_overdue_tasks(bot: Bot):
    """Сводка просроченных задач в общий чат."""
    logger.info("Проверка просроченных задач...")
    tasks = get_overdue_tasks()
    if not tasks:
        return
    summary = await generate_overdue_summary(tasks)
    try:
        await bot.send_message(chat_id=NOTIFY_CHAT_ID, text=summary, parse_mode="Markdown")
        logger.info(f"Отправлено уведомление о {len(tasks)} просроченных задачах.")
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")


async def auto_mark_overdue(bot: Bot):
    """Автоматически меняет статус на Просрочена если дедлайн прошёл."""
    today = datetime.now().strftime("%Y-%m-%d")
    all_tasks = get_tasks()
    count = 0
    for task in all_tasks:
        if task.get("status") in ("Выполнена", "Просрочена", "Заблокирована"):
            continue
        deadline = task.get("deadline", "")
        if deadline and deadline < today:
            update_status(task["id"], "Просрочена", changed_by="Авто")
            count += 1
            # Уведомить ответственного
            assignee = task.get("assignee", "")
            if assignee:
                with get_conn() as conn:
                    rows = conn.execute("SELECT * FROM users").fetchall()
                    user = None
                    for row in rows:
                        if assignee.lower() in row["name"].lower() or row["name"].lower() in assignee.lower():
                            user = dict(row)
                            break
                if user:
                    try:
                        await bot.send_message(
                            user["telegram_id"],
                            f"🔴 *Задача #{task['id']} просрочена!*\n\n"
                            f"📌 {task['title']}\n"
                            f"📅 Срок был: {deadline}\n\n"
                            f"Напишите комментарий о причине задержки: /comment {task['id']}",
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления о просрочке: {e}")
    if count:
        logger.info(f"Автоматически помечено просроченными: {count} задач")


async def escalate_overdue(bot: Bot):
    """Эскалация руководителю если задача просрочена 3+ дней."""
    if not NOTIFY_CHAT_ID:
        return
    today = datetime.now().date()
    tasks = get_overdue_tasks()
    critical = []
    for task in tasks:
        try:
            deadline = datetime.strptime(task["deadline"], "%Y-%m-%d").date()
            days_over = (today - deadline).days
            if days_over >= 3:
                critical.append((task, days_over))
        except Exception:
            continue
    if not critical:
        return
    lines = ["⚠️ *Требуют внимания руководителя:*\n"]
    for task, days in critical:
        lines.append(
            f"🔴 *#{task['id']}* {task['title']}\n"
            f"   👤 {task['assignee'] or '—'} | просрочено на *{days} дн.*"
        )
    try:
        await bot.send_message(NOTIFY_CHAT_ID, "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка эскалации: {e}")


async def check_deadline_reminders(bot: Bot):
    """Уведомления ответственным за 1 день и в день дедлайна."""
    logger.info("Проверка дедлайнов для уведомлений...")
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    all_tasks = get_tasks()

    for task in all_tasks:
        if task.get("status") in ("Выполнена", "Просрочена"):
            continue
        assignee = task.get("assignee", "")
        deadline = task.get("deadline", "")
        if not assignee or not deadline:
            continue
        with get_conn() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
            user = None
            as_l = assignee.lower().strip()
            as_surname = as_l.split()[0] if as_l else ""
            for row in rows:
                row_name = row["name"].lower().strip()
                # Прямое совпадение
                if as_l in row_name or row_name in as_l:
                    user = dict(row)
                    break
                # По фамилии
                if len(as_surname) >= 4:
                    for word in row_name.split():
                        if as_surname in word or word in as_surname:
                            user = dict(row)
                            break
                if user:
                    break
        if not user:
            continue
        telegram_id = user["telegram_id"]
        title = task.get("title", "—")
        task_id = task.get("id")

        if deadline == tomorrow:
            try:
                await bot.send_message(
                    telegram_id,
                    f"⏰ *Завтра дедлайн!*\n\n"
                    f"📌 *#{task_id}:* {title}\n"
                    f"📅 {deadline}\n\n"
                    f"Напишите о статусе: /comment {task_id}\n"
                    f"Или отметьте выполненной: /done {task_id}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка напоминания -1 день: {e}")

        if deadline == today:
            try:
                await bot.send_message(
                    telegram_id,
                    f"🚨 *Сегодня дедлайн!*\n\n"
                    f"📌 *#{task_id}:* {title}\n\n"
                    f"Отметьте выполненной: /done {task_id}\n"
                    f"Или напишите комментарий: /comment {task_id}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка напоминания день дедлайна: {e}")


async def weekly_digest(bot: Bot):
    """Еженедельный личный дайджест каждому сотруднику — каждый понедельник."""
    logger.info("Отправка еженедельного дайджеста...")
    try:
        users = get_all_users()
    except Exception:
        return
    all_tasks = get_tasks()
    today = datetime.now().strftime("%Y-%m-%d")

    for user in users:
        name = user["name"]
        telegram_id = user["telegram_id"]
        my_tasks = [t for t in all_tasks if name.lower() in (t.get("assignee") or "").lower()]
        active = [t for t in my_tasks if t.get("status") not in ("Выполнена",)]
        if not active:
            continue
        overdue = [t for t in active if t.get("deadline") and t["deadline"] < today]
        due_soon = [t for t in active if t.get("deadline") and today <= t["deadline"] <= (
            datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d") and t not in overdue]
        other = [t for t in active if t not in overdue and t not in due_soon]

        lines = [f"📋 *Ваши задачи на неделю, {name}:*\n"]
        if overdue:
            lines.append("🔴 *Просрочены:*")
            for t in overdue[:5]:
                lines.append(f"  • #{t['id']} {t['title'][:50]} — /done {t['id']}")
        if due_soon:
            lines.append("\n⏰ *Срок на этой неделе:*")
            for t in due_soon[:5]:
                lines.append(f"  • #{t['id']} {t['title'][:50]} | 📅 {t['deadline']}")
        if other:
            lines.append(f"\n📌 *Остальные ({len(other)}):*")
            for t in other[:3]:
                lines.append(f"  • #{t['id']} {t['title'][:50]}")
        lines.append(f"\n_Всего активных: {len(active)} задач_")
        try:
            await bot.send_message(telegram_id, "\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка дайджеста для {name}: {e}")


async def morning_briefing(bot: Bot):
    """Утренний брифинг каждому сотруднику в 9:00."""
    logger.info("Отправка утреннего брифинга...")
    try:
        users = get_all_users()
    except Exception:
        return
    all_tasks = get_tasks()
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    for user in users:
        name = user["name"]
        telegram_id = user["telegram_id"]
        my_tasks = [t for t in all_tasks if name.lower() in (t.get("assignee") or "").lower()
                    and t.get("status") not in ("Выполнена",)]
        if not my_tasks:
            continue

        overdue = [t for t in my_tasks if t.get("deadline") and t["deadline"] < today]
        due_today = [t for t in my_tasks if t.get("deadline") == today]
        due_tomorrow = [t for t in my_tasks if t.get("deadline") == tomorrow]
        active = [t for t in my_tasks if t not in overdue and t not in due_today and t not in due_tomorrow]

        lines = [f"☀️ Доброе утро, *{name}*!\n"]

        if overdue:
            lines.append(f"🔴 *{len(overdue)} просроченных:*")
            for t in overdue[:3]:
                lines.append(f"  • #{t['id']} {t['title'][:45]} — /done {t['id']}")

        if due_today:
            lines.append(f"\n🚨 *{len(due_today)} срок сегодня:*")
            for t in due_today:
                lines.append(f"  • #{t['id']} {t['title'][:45]} — /done {t['id']}")

        if due_tomorrow:
            lines.append(f"\n⏰ *{len(due_tomorrow)} срок завтра:*")
            for t in due_tomorrow:
                lines.append(f"  • #{t['id']} {t['title'][:45]}")

        if active:
            lines.append(f"\n🟡 *Остальных задач: {len(active)}*")

        lines.append(f"\n_Всего активных: {len(my_tasks)}_")

        try:
            await bot.send_message(telegram_id, "\n".join(lines), parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка утреннего брифинга для {name}: {e}")


# ─── Уведомления о встречах ────────────────────────────────────────────────

def _find_user_by_name(name):
    """Ищет пользователя по имени/фамилии (как в напоминаниях по задачам)."""
    name_l = (name or "").lower().strip()
    if not name_l:
        return None
    surname = name_l.split()[0]
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users").fetchall()
    for row in rows:
        row_name = row["name"].lower().strip()
        if name_l in row_name or row_name in name_l:
            return dict(row)
    if len(surname) >= 4:
        for row in rows:
            for word in row["name"].lower().strip().split():
                if surname in word or word in surname:
                    return dict(row)
    return None


async def notify_meeting_participants(bot: Bot, meeting: dict):
    """Отправляет уведомление о создании встречи каждому участнику лично."""
    participants = [p.strip() for p in (meeting.get("participants") or "").split(",") if p.strip()]
    if not participants:
        return
    date = meeting.get("date") or "—"
    time_start = meeting.get("time_start") or ""
    time_end = meeting.get("time_end") or ""
    time_str = time_start + (f"–{time_end}" if time_end else "")
    title = meeting.get("title") or "Без темы"
    project = meeting.get("project") or ""
    desc = meeting.get("description") or ""
    all_participants = ", ".join(participants)

    text = (
        f"📅 *Назначена встреча*\n\n"
        f"📌 *Тема:* {title}\n"
        f"🗓 *Дата:* {date}"
        f"{chr(10) + '🕐 *Время:* ' + time_str if time_str else ''}\n"
        f"👥 *Участники:* {all_participants}"
        f"{chr(10) + '📁 *Проект:* ' + project if project else ''}"
        f"{chr(10) + chr(10) + '📝 ' + desc if desc else ''}"
    )
    for name in participants:
        user = _find_user_by_name(name)
        if not user:
            continue
        try:
            await bot.send_message(user["telegram_id"], text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка уведомления о встрече для {name}: {e}")


async def check_meeting_reminders(bot: Bot):
    """Проверяет встречи и шлёт участникам напоминание за 15 минут до начала."""
    now = datetime.now()
    meetings = get_upcoming_meetings()
    for m in meetings:
        date = m.get("date") or ""
        time_start = m.get("time_start") or ""
        if not date or not time_start:
            continue
        # Собираем datetime начала встречи
        try:
            start_dt = datetime.strptime(f"{date} {time_start}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        delta_min = (start_dt - now).total_seconds() / 60
        # Окно: от 0 до 15 минут до начала (проверка раз в минуту)
        if 0 <= delta_min <= 15:
            participants = [p.strip() for p in (m.get("participants") or "").split(",") if p.strip()]
            title = m.get("title") or "Без темы"
            time_str = time_start + (f"–{m['time_end']}" if m.get("time_end") else "")
            project = m.get("project") or ""
            text = (
                f"⏰ *Встреча через 15 минут!*\n\n"
                f"📌 *Тема:* {title}\n"
                f"🕐 *Время:* {time_str}"
                f"{chr(10) + '📁 *Проект:* ' + project if project else ''}\n"
                f"👥 *Участники:* {', '.join(participants)}"
            )
            for name in participants:
                user = _find_user_by_name(name)
                if not user:
                    continue
                try:
                    await bot.send_message(user["telegram_id"], text, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Ошибка напоминания о встрече для {name}: {e}")
            mark_meeting_reminded(m["id"])


async def notify_task_assignees(bot: Bot, assignees, title, project, deadline):
    """Шлёт каждому ответственному персональное уведомление о новой задаче."""
    if isinstance(assignees, str):
        assignees = [a.strip() for a in assignees.split(",") if a.strip()]
    for name in assignees:
        user = _find_user_by_name(name)
        if not user:
            logger.info(f"Не найден пользователь для уведомления о задаче: {name}")
            continue
        text = (
            f"📌 *Вам назначена задача*\n\n"
            f"📋 *Задача:* {title}\n"
            f"📁 *Проект:* {project or '—'}\n"
            f"📅 *Срок:* {deadline or '—'}"
        )
        try:
            await bot.send_message(user["telegram_id"], text, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Ошибка уведомления о задаче для {name}: {e}")
