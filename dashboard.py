"""
Веб-дашборд на aiohttp — показывает задачи по проектам.
"""
from aiohttp import web
from database import get_tasks, get_projects, get_stats, update_status, get_task_comments
from datetime import datetime

routes = web.RouteTableDef()

# Цвета проектов — добавляйте свои проекты сюда
PROJECT_COLORS = {
    "board miniso": {"bg": "#FEE2E2", "text": "#DC2626", "border": "#DC2626"},
    "сверка баз": {"bg": "#DBEAFE", "text": "#1D4ED8", "border": "#1D4ED8"},
}

def get_project_color(project_name):
    key = project_name.lower().strip()
    for k, v in PROJECT_COLORS.items():
        if k in key or key in k:
            return v
    # Дефолтный цвет для остальных проектов
    return {"bg": "#F3F4F6", "text": "#374151", "border": "#6B7280"}


def task_row(t):
    today = datetime.now().strftime("%Y-%m-%d")
    overdue = t["deadline"] and t["deadline"] < today and t["status"] != "Выполнена"
    status_color = {
        "Открыта": "#3B82F6",
        "В работе": "#F59E0B",
        "Выполнена": "#10B981",
    }.get(t["status"], "#6B7280")
    row_bg = "#FFF0F0" if overdue else "white"

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
    project_badge = f"<span style='background:{pc['bg']};color:{pc['text']};border:1px solid {pc['border']}20;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;'>{t['project']}</span>"

    return f"""
    <tr style="background:{row_bg}; border-bottom:1px solid #E5E7EB;">
        <td style="padding:10px 12px; color:#6B7280; font-size:13px;">#{t['id']}</td>
        <td style="padding:10px 12px; font-weight:500;">{t['title']}</td>
        <td style="padding:10px 12px; color:#4B5563;">{t['assignee'] or '—'}</td>
        <td style="padding:10px 12px; color:#4B5563;">{t['department'] or '—'}</td>
        <td style="padding:10px 12px;">{project_badge}</td>
        <td style="padding:10px 12px; color:#4B5563;">{t['deadline'] or '—'}</td>
        <td style="padding:10px 12px;">
            <span style="background:{status_color}20; color:{status_color}; padding:3px 10px; border-radius:20px; font-size:12px; font-weight:600;">
                {t['status']}
            </span>
        </td>
        <td style="padding:10px 12px; color:#4B5563; font-size:13px;">{comment_html}</td>
    </tr>"""


def calc_stats(tasks):
    today = datetime.now().strftime("%Y-%m-%d")
    total = len(tasks)
    open_ = sum(1 for t in tasks if t["status"] == "Открыта")
    done = sum(1 for t in tasks if t["status"] == "Выполнена")
    overdue = sum(1 for t in tasks if t["status"] != "Выполнена" and t["deadline"] and t["deadline"] < today)
    return {"total": total, "open": open_, "done": done, "overdue": overdue}


@routes.get("/")
async def dashboard(request):
    projects = get_projects()
    selected = request.rel_url.query.get("project", "")
    status_filter = request.rel_url.query.get("status", "")

    tasks = get_tasks(project=selected or None, status=status_filter or None)
    stats = calc_stats(tasks)

    # Кнопки проектов с цветами
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
            transition:all 0.2s;
        ">{p['name']}</a>"""

    project_options = "".join(
        f'<option value="{p["name"]}" {"selected" if p["name"]==selected else ""}>{p["name"]}</option>'
        for p in projects
    )
    status_options = "".join(
        f'<option value="{s}" {"selected" if s==status_filter else ""}>{s}</option>'
        for s in ["Открыта", "В работе", "Выполнена"]
    )
    rows = "".join(task_row(t) for t in tasks)

    if not tasks:
        rows = '<tr><td colspan="8" style="text-align:center;padding:40px;color:#9CA3AF;">Задач нет</td></tr>'

    title = f"Проект: {selected}" if selected else "Все проекты"

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
  .project-bar {{ padding: 0 32px 16px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  .filters {{ padding: 0 32px 16px; display: flex; gap: 12px; align-items: center; }}
  select {{ padding: 8px 12px; border: 1px solid #E5E7EB; border-radius: 8px; font-size: 14px; background: white; cursor: pointer; }}
  .btn {{ padding: 8px 16px; background: #3B82F6; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; text-decoration: none; }}
  .btn-clear {{ background: #6B7280; }}
  .table-wrap {{ padding: 0 32px 32px; overflow-x: auto; }}
  table {{ width: 100%; background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); border-collapse: collapse; }}
  thead th {{ padding: 12px; text-align: left; font-size: 12px; font-weight: 600; color: #6B7280; text-transform: uppercase; letter-spacing: .05em; border-bottom: 2px solid #E5E7EB; }}
  tr:hover {{ background: #F9FAFB !important; }}
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
        <th>Проект</th><th>Срок</th><th>Статус</th><th>Комментарий сотрудника</th>
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
    raise web.HTTPFound("/")


@routes.get("/reopen/{task_id}")
async def reopen_task(request):
    task_id = int(request.match_info["task_id"])
    update_status(task_id, "Открыта")
    raise web.HTTPFound("/")


def create_app():
    app = web.Application()
    app.add_routes(routes)
    return app
    
