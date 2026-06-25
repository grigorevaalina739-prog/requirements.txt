"""
Веб-дашборд на aiohttp — показывает задачи по проектам.
"""
from aiohttp import web
from database import get_tasks, get_projects, get_stats, update_status, get_task_comments
from datetime import datetime, date

routes = web.RouteTableDef()

PROJECT_COLORS = {
    "board miniso": {"bg": "#FEE2E2", "text": "#DC2626", "border": "#DC2626"},
    "сверка баз": {"bg": "#DBEAFE", "text": "#1D4ED8", "border": "#1D4ED8"},
}

MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

def get_project_color(project_name):
    key = project_name.lower().strip()
    for k, v in PROJECT_COLORS.items():
        if k in key or key in k:
            return v
    return {"bg": "#F3F4F6", "text": "#374151", "border": "#6B7280"}

def format_deadline(deadline_str):
    if not deadline_str:
        return "—"
    try:
        dl = date.fromisoformat(deadline_str)
        today = date.today()
        delta = (dl - today).days
        day_str = f"{dl.day} {MONTHS_RU[dl.month]}"
        if delta < 0:
            days_over = abs(delta)
            noun = "день" if days_over % 10 == 1 and days_over % 100 != 11 else                    "дня" if 2 <= days_over % 10 <= 4 and not (12 <= days_over % 100 <= 14) else "дней"
            return f"""<div style="display:inline-flex;align-items:center;gap:6px;background:#FEE2E2;border-radius:8px;padding:4px 10px;">
<span style="color:#DC2626;font-size:16px;">●</span>
<span style="color:#DC2626;font-weight:600;font-size:13px;">Просрочено на {days_over} {noun}</span>
</div>"""
        else:
            noun = "день" if delta % 10 == 1 and delta % 100 != 11 else                    "дня" if 2 <= delta % 10 <= 4 and not (12 <= delta % 100 <= 14) else "дней"
            color = "#EF4444" if delta <= 2 else "#F59E0B" if delta <= 7 else "#10B981"
            return f"""<div style="display:inline-block;background:#F9FAFB;border-radius:8px;padding:4px 10px;">
<div style="font-weight:600;font-size:13px;color:#111827;">{day_str}</div>
<div style="font-size:11px;color:{color};font-weight:500;">Осталось {delta} {noun}</div>
</div>"""
    except Exception:
        return deadline_str

def task_row(t, project_filter="", status_filter=""):
    today = datetime.now().strftime("%Y-%m-%d")
    overdue = t["deadline"] and t["deadline"] < today and t["status"] != "Выполнена"
    status_color = {
        "Открыта": "#3B82F6",
        "В работе": "#F59E0B",
        "Выполнена": "#10B981",
    }.get(t["status"], "#6B7280")
    row_bg = "#FFF5F5" if overdue else "white"

    comments = get_task_comments(t["id"])
    if comments:
        last = comments[-1]
        if last.get("file_id"):
            comment_text = f"📎 {last['author']}: {last['file_name']}"
        else:
            comment_text = f"💬 {last['author']}: {last['text'][:80]}"
        comment_count = f" <span style='color:#9CA3AF;font-size:11px;'>({len(comments)})</span>" if len(comments) > 1 else ""
        comment_html = f"{comment_text}{comment_count}"
    else:
        comment_html = "—"

    pc = get_project_color(t["project"])
    project_badge = f"<span style='background:{pc['bg']};color:{pc['text']};border:1px solid {pc['border']}40;padding:3px 8px;border-radius:6px;font-size:11px;font-weight:600;white-space:nowrap;'>{t['project']}</span>"
    deadline_html = format_deadline(t["deadline"]) if t["status"] != "Выполнена" else f"<span style='color:#6B7280'>{t['deadline'] or '—'}</span>"

    back_url = f"/?project={project_filter}&status={status_filter}"

    if t["status"] == "Выполнена":
        action_btn = f"""<a href="/reopen/{t['id']}?back={back_url}" title="Переоткрыть" style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:6px;background:#F3F4F6;color:#6B7280;text-decoration:none;font-size:15px;" onclick="return confirm('Переоткрыть задачу?')">↩️</a>"""
    else:
        action_btn = f"""<a href="/done/{t['id']}?back={back_url}" title="Завершить" style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:6px;background:#D1FAE5;color:#059669;text-decoration:none;font-size:15px;" onclick="return confirm('Отметить как выполненную?')">✅</a>"""

    actions_html = f"""<div style="display:flex;gap:4px;align-items:center;">
    <a href="/edit/{t['id']}" title="Редактировать" style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:6px;background:#EFF6FF;color:#3B82F6;text-decoration:none;font-size:15px;">✏️</a>
    <a href="/comment/{t['id']}" title="Комментарий" style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:6px;background:#F5F3FF;color:#7C3AED;text-decoration:none;font-size:15px;">💬</a>
    {action_btn}
    <a href="/attach/{t['id']}" title="Вложения" style="display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:6px;background:#FFF7ED;color:#EA580C;text-decoration:none;font-size:15px;">📎</a>
</div>"""

    return f"""
<tr style="background:{row_bg}; border-bottom:1px solid #E5E7EB;">
    <td style="padding:10px 12px; color:#6B7280; font-size:13px; white-space:nowrap;">#{t['id']}</td>
    <td style="padding:10px 12px; font-weight:500; min-width:220px;">{t['title']}</td>
    <td style="padding:10px 12px; color:#4B5563; white-space:nowrap;">{t['assignee'] or '—'}</td>
    <td style="padding:10px 12px; color:#4B5563; white-space:nowrap;">{t['department'] or '—'}</td>
    <td style="padding:10px 12px; white-space:nowrap;">{project_badge}</td>
    <td style="padding:10px 12px; min-width:160px;">{deadline_html}</td>
    <td style="padding:10px 12px; white-space:nowrap;">
        <span style="background:{status_color}20; color:{status_color}; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600;">
            {t['status']}
        </span>
    </td>
    <td style="padding:10px 12px; color:#4B5563; font-size:13px; min-width:180px;">{comment_html}</td>
    <td class="row-actions" style="padding:10px 12px; white-space:nowrap;">{actions_html}</td>
</tr>"""

def calc_stats(tasks):
    today = datetime.now().strftime("%Y-%m-%d")
    total = len(tasks)
    open_ = sum(1 for t in tasks if t["status"] == "Открыта")
    done = sum(1 for t in tasks if t["status"] == "Выполнена")
    overdue = sum(1 for t in tasks if t["status"] != "Выполнена" and t["deadline"] and t["deadline"] < today)
    percent = round((done / total * 100) if total > 0 else 0)
    return {"total": total, "open": open_, "done": done, "overdue": overdue, "percent": percent}

@routes.get("/")
async def dashboard(request):
    projects = get_projects()
    selected = request.rel_url.query.get("project", "")
    status_filter = request.rel_url.query.get("status", "")

    tasks = get_tasks(project=selected or None, status=status_filter or None)
    stats = calc_stats(tasks)

    project_buttons = ""
    for p in projects:
        pc = get_project_color(p["name"])
        is_active = p["name"] == selected
        border = f"3px solid {pc['border']}" if is_active else f"2px solid {pc['border']}40"
        bg = pc["bg"] if is_active else "white"
        project_buttons += f"""
<a href="/?project={p['name']}" style="
    display:inline-block;
    padding:8px 16px;
    background:{bg};
    color:{pc['text']};
    border:{border};
    border-radius:8px;
    font-size:14px;
    font-weight:600;
    text-decoration:none;
">{p['name']}</a>"""

    status_options = "".join(
        f'<option value="{s}" {"selected" if s==status_filter else ""}>{s}</option>'
        for s in ["Открыта", "В работе", "Выполнена"]
    )
    rows = "".join(task_row(t, selected, status_filter) for t in tasks)

    if not tasks:
        rows = '<tr><td colspan="9" style="text-align:center;padding:40px;color:#9CA3AF;">Задач нет</td></tr>'

    title = f"Проект: {selected}" if selected else "Все проекты"
    progress_color = "#10B981" if stats['percent'] == 100 else "#3B82F6"

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Task Dashboard</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F9FAFB; color: #111827; }}
.header {{ background: #1E293B; color: white; padding: 20px 32px; display: flex; align-items: center; gap: 12px; }}
.header h1 {{ font-size: 20px; font-weight: 700; }}
.header span {{ opacity: 0.6; font-size: 13px; }}
.stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; padding: 24px 32px; }}
.stat {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.stat .num {{ font-size: 32px; font-weight: 700; }}
.stat .label {{ font-size: 13px; color: #6B7280; margin-top: 4px; }}
.progress-section {{ padding: 0 32px 24px; }}
.progress-card {{ background: white; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.progress-title {{ font-size: 14px; font-weight: 600; color: #374151; margin-bottom: 12px; }}
.progress-bar-wrap {{ display: flex; align-items: center; gap: 12px; }}
.progress-bar-bg {{ flex: 1; background: #E5E7EB; border-radius: 999px; height: 14px; overflow: hidden; }}
.progress-bar-fill {{ height: 100%; border-radius: 999px; transition: width .4s ease; }}
.progress-percent {{ font-size: 18px; font-weight: 700; color: #111827; min-width: 52px; text-align: right; }}
.progress-sub {{ font-size: 12px; color: #6B7280; margin-top: 8px; }}
.project-bar {{ padding: 0 32px 16px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
.filters {{ padding: 0 32px 16px; display: flex; gap: 12px; align-items: center; }}
select {{ padding: 8px 12px; border: 1px solid #E5E7EB; border-radius: 8px; font-size: 14px; background: white; cursor: pointer; }}
.btn {{ padding: 8px 16px; background: #3B82F6; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; text-decoration: none; }}
.btn-clear {{ background: #6B7280; }}
.table-wrap {{ padding: 0 32px 32px; overflow-x: auto; }}
table {{ width: 100%; background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); border-collapse: collapse; table-layout: auto; }}
thead th {{ padding: 12px; text-align: left; font-size: 12px; font-weight: 600; color: #6B7280; text-transform: uppercase; letter-spacing: .05em; border-bottom: 2px solid #E5E7EB; white-space: nowrap; }}
tr:hover td {{ background: #F9FAFB; }}
.row-actions a {{ opacity: 0.7; transition: opacity .15s, transform .15s; }}
.row-actions a:hover {{ opacity: 1 !important; transform: scale(1.1); }}
</style>
</head>
<body>
<div class="header">
    <div>
        <h1>📋 Task Dashboard</h1>
        <span>{title}</span>
    </div>
</div>

<div class="stats">
    <div class="stat"><div class="num" style="color:#1E293B">{stats['total']}</div><div class="label">Всего задач</div></div>
    <div class="stat"><div class="num" style="color:#3B82F6">{stats['open']}</div><div class="label">Открытых</div></div>
    <div class="stat"><div class="num" style="color:#10B981">{stats['done']}</div><div class="label">Выполненных</div></div>
    <div class="stat"><div class="num" style="color:#EF4444">{stats['overdue']}</div><div class="label">Просроченных 🔴</div></div>
</div>

<div class="progress-section">
    <div class="progress-card">
        <div class="progress-title">📊 Прогресс проекта</div>
        <div class="progress-bar-wrap">
            <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width:{stats['percent']}%; background:{progress_color};"></div>
            </div>
            <div class="progress-percent">{stats['percent']}%</div>
        </div>
        <div class="progress-sub">Выполнено {stats['done']} из {stats['total']} задач</div>
    </div>
</div>

<div class="project-bar">
    <a href="/" style="display:inline-block;padding:8px 16px;background:{'#1E293B' if not selected else 'white'};color:{'white' if not selected else '#6B7280'};border:2px solid {'#1E293B' if not selected else '#E5E7EB'};border-radius:8px;font-size:14px;font-weight:600;text-decoration:none;">Все проекты</a>
    {project_buttons}
</div>

<div class="filters">
    <form method="get" style="display:flex;gap:12px;align-items:center;">
        <input type="hidden" name="project" value="{selected}">
        <select name="status" onchange="this.form.submit()">
            <option value="">Все статусы</option>{status_options}
        </select>
        <a href="/" class="btn btn-clear">Сбросить</a>
    </form>
</div>

<div class="table-wrap">
    <table>
        <thead>
            <tr>
                <th>ID</th><th>Задача</th><th>Ответственный</th><th>Отдел</th>
                <th>Проект</th><th>Срок</th><th>Статус</th><th>Комментарий</th><th>Действия</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
</div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")

@routes.get("/done/{task_id}")
async def mark_done(request):
    task_id = int(request.match_info["task_id"])
    update_status(task_id, "Выполнена")
    back = request.rel_url.query.get("back", "/")
    raise web.HTTPFound(back)

@routes.get("/reopen/{task_id}")
async def reopen_task(request):
    task_id = int(request.match_info["task_id"])
    update_status(task_id, "Открыта")
    back = request.rel_url.query.get("back", "/")
    raise web.HTTPFound(back)

def create_app():
    app = web.Application()
    app.add_routes(routes)
    return app
