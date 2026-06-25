"""
Веб-дашборд на aiohttp — показывает задачи по проектам.
"""
from aiohttp import web
from database import get_tasks, get_projects, get_stats, update_status, get_task_comments, add_task_comment, get_task_history, log_task_change, get_meetings, add_meeting, delete_meeting, update_meeting, add_task
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

    STATUS_CONFIG = {
        "Открыта":         ("#3B82F6", "#EFF6FF"),
        "В работе":        ("#D97706", "#FFFBEB"),
        "Выполнена":       ("#059669", "#ECFDF5"),
        "На согласовании": ("#EA580C", "#FFF7ED"),
        "Просрочена":      ("#DC2626", "#FEF2F2"),
        "Заблокирована":   ("#374151", "#F3F4F6"),
    }
    sc_color, sc_bg = STATUS_CONFIG.get(t["status"], ("#6B7280", "#F9FAFB"))

    comments = get_task_comments(t["id"])
    if comments:
        last = comments[-1]
        comment_text = f"📎 {last['file_name']}" if last.get("file_id") else f"{last['text'][:60]}"
        comment_html = f'<span style="color:#475569;font-size:12px;">{comment_text}</span>'
        if len(comments) > 1:
            comment_html += f' <span style="background:#F1F5F9;color:#94A3B8;padding:1px 6px;border-radius:10px;font-size:11px;">{len(comments)}</span>'
    else:
        comment_html = '<span style="color:#CBD5E1;">—</span>'

    pc = get_project_color(t["project"])
    project_badge = f"<span style='background:{pc['bg']};color:{pc['text']};padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;white-space:nowrap;'>{t['project']}</span>"

    if t["status"] == "Выполнена":
        deadline_html = f'<span style="color:#94A3B8;font-size:13px;">{t["deadline"] or "—"}</span>'
    else:
        deadline_html = format_deadline(t["deadline"])

    assignee = t.get("assignee") or ""
    if assignee and assignee != "—":
        parts = assignee.split()
        initials = (parts[0][0] if parts else "?") + (parts[1][0] if len(parts) > 1 else "")
        av_colors = ["#3B82F6","#8B5CF6","#10B981","#F59E0B","#EF4444","#06B6D4","#EC4899"]
        av_color = av_colors[sum(ord(c) for c in assignee) % len(av_colors)]
        av_bg = av_color + "20"
        assignee_html = (
            '<div style="display:flex;align-items:center;gap:8px;">'
            f'<div style="width:28px;height:28px;border-radius:50%;background:{av_bg};color:{av_color};'
            f'font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0;">{initials}</div>'
            f'<span style="font-size:13px;color:#334155;">{assignee}</span></div>'
        )
    else:
        assignee_html = '<span style="color:#CBD5E1;">—</span>'

    back_url = f"/?project={project_filter}&status={status_filter}"
    row_border = "border-left:3px solid #e05c5c;" if overdue else "border-left:3px solid transparent;"

    tid = t['id']
    if t["status"] == "Выполнена":
        done_btn = (
            f'<a href="#" title="Переоткрыть" '
            f'style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:50%;background:#F1F5F9;color:#64748B;text-decoration:none;font-size:14px;" '
            f"onclick=\"var n=prompt('Ваше имя:');if(n){{window.location='/reopen/{tid}?back={back_url}&author='+encodeURIComponent(n)}};return false;\">↩️</a>"
        )
    else:
        done_btn = (
            f'<a href="#" title="Выполнено" '
            f'style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:50%;background:#ECFDF5;color:#059669;text-decoration:none;font-size:14px;" '
            f"onclick=\"var n=prompt('Ваше имя:');if(n){{window.location='/done/{tid}?back={back_url}&author='+encodeURIComponent(n)}};return false;\">✅</a>"
        )

    actions_html = (
        '<div style="display:flex;gap:4px;align-items:center;opacity:0;transition:opacity .15s;" class="row-actions-wrap">'
        f'<a href="/edit/{tid}" title="Редактировать" style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:50%;background:#EFF6FF;color:#3B82F6;text-decoration:none;font-size:14px;">✏️</a>'
        f'<a href="/comment/{tid}" title="Комментарий" style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border-radius:50%;background:#F5F3FF;color:#7C3AED;text-decoration:none;font-size:14px;">💬</a>'
        f'{done_btn}'
        '<div style="position:relative;display:inline-block;">'
        '<button onclick="toggleMenu(this)" style="width:32px;height:32px;border-radius:50%;background:#F1F5F9;border:none;cursor:pointer;font-size:18px;color:#64748B;display:flex;align-items:center;justify-content:center;">⋯</button>'
        '<div class="more-dropdown" style="display:none;position:absolute;right:0;top:36px;background:white;border:1px solid #E2E8F0;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,.12);z-index:100;min-width:160px;padding:6px 0;">'
        f'<a href="/attach/{tid}" style="display:flex;align-items:center;gap:10px;padding:9px 16px;color:#374151;text-decoration:none;font-size:13px;" onmouseover="this.style.background=\'#F8FAFC\'" onmouseout="this.style.background=\'\'">📎 Вложения</a>'
        f'<a href="/history/{tid}" style="display:flex;align-items:center;gap:10px;padding:9px 16px;color:#374151;text-decoration:none;font-size:13px;" onmouseover="this.style.background=\'#F8FAFC\'" onmouseout="this.style.background=\'\'">🕐 История</a>'
        '</div></div></div>'
    )

    title_short = t['title'][:90] + '…' if len(t['title']) > 90 else t['title']

    return (
        f'<tr class="task-row" style="{row_border}background:white;" '
        f'onmouseenter="this.querySelector(\'.row-actions-wrap\').style.opacity=\'1\';this.style.background=\'#F8FAFC\';" '
        f'onmouseleave="this.querySelector(\'.row-actions-wrap\').style.opacity=\'0\';this.style.background=\'white\';">'
        f'<td style="padding:14px 12px;color:#94A3B8;font-size:12px;font-weight:600;white-space:nowrap;">#{tid}</td>'
        f'<td style="padding:14px 12px;min-width:220px;max-width:320px;">'
        f'<div style="font-weight:500;font-size:14px;color:#0f172a;line-height:1.4;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;" title="{t["title"]}">{title_short}</div>'
        f'</td>'
        f'<td style="padding:14px 12px;white-space:nowrap;">{assignee_html}</td>'
        f'<td style="padding:14px 12px;white-space:nowrap;">{project_badge}</td>'
        f'<td style="padding:14px 12px;min-width:140px;">{deadline_html}</td>'
        f'<td style="padding:14px 12px;white-space:nowrap;">'
        f'<span style="display:inline-flex;align-items:center;gap:6px;background:{sc_bg};color:{sc_color};padding:5px 12px;border-radius:20px;font-size:12px;font-weight:600;">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{sc_color};flex-shrink:0;"></span>'
        f'{t["status"]}</span></td>'
        f'<td style="padding:14px 12px;font-size:13px;min-width:160px;">{comment_html}</td>'
        f'<td class="row-actions" style="padding:14px 12px;white-space:nowrap;">{actions_html}</td>'
        f'</tr>'
    )

def calc_stats(tasks):
    today = datetime.now().strftime("%Y-%m-%d")
    total = len(tasks)
    open_ = sum(1 for t in tasks if t["status"] in ("Открыта", "В работе", "На согласовании"))
    done = sum(1 for t in tasks if t["status"] == "Выполнена")
    overdue = sum(1 for t in tasks if t["status"] != "Выполнена" and t["deadline"] and t["deadline"] < today)
    percent = round((done / total * 100) if total > 0 else 0)
    return {"total": total, "open": open_, "done": done, "overdue": overdue, "percent": percent}

@routes.get("/")
async def dashboard(request):
    projects = get_projects()
    selected = request.rel_url.query.get("project", "")
    status_filter = request.rel_url.query.get("status", "")
    search_query = request.rel_url.query.get("q", "").strip().lower()

    tasks = get_tasks(project=selected or None, status=status_filter or None)
    if search_query:
        tasks = [t for t in tasks if
            search_query in str(t.get("id","")) or
            search_query in (t.get("title") or "").lower() or
            search_query in (t.get("assignee") or "").lower()
        ]
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
        for s in ["Открыта", "В работе", "Выполнена", "На согласовании", "Просрочена", "Заблокирована"]
    )
    rows = "".join(task_row(t, selected, status_filter) for t in tasks)
    search_value = search_query

    if not tasks:
        rows = '<tr><td colspan="9" style="text-align:center;padding:40px;color:#9CA3AF;">Задач нет</td></tr>'

    title = f"Проект: {selected}" if selected else "Все проекты"
    progress_color = "#10B981" if stats['percent'] == 100 else "#3B82F6"

    # Attention блок
    all_tasks_full = get_tasks()
    today_str = datetime.now().strftime("%Y-%m-%d")
    attention_items = []
    for tt in all_tasks_full:
        if tt.get("deadline") == today_str and tt.get("status") != "Выполнена":
            attention_items.append(f"⏰ Сегодня дедлайн: <b>{tt['title'][:50]}</b> ({tt.get('assignee') or '—'})")
    for tt in all_tasks_full:
        if tt.get("status") == "Просрочена":
            attention_items.append(f"🔴 Просрочена: <b>{tt['title'][:50]}</b> ({tt.get('assignee') or '—'})")
    attention_html = ""
    if attention_items:
        items_html = "".join(f'<div style="padding:10px 0;border-bottom:1px solid #FEE2E2;font-size:13px;color:#374151;">{i}</div>' for i in attention_items[:5])
        attention_html = f'''<div style="background:white;border-radius:20px;padding:24px 28px;box-shadow:0 2px 12px rgba(0,0,0,.06);border-left:4px solid #EF4444;margin-bottom:24px;">
        <div style="font-size:15px;font-weight:700;color:#0F172A;margin-bottom:12px;">⚠️ Требует внимания</div>
        {items_html}
    </div>'''

    # Статистика расширенная
    all_stats = calc_stats(all_tasks_full)
    today_deadline = sum(1 for t in all_tasks_full if t.get("deadline") == today_str and t.get("status") != "Выполнена")

    # AI summary
    if all_stats["overdue"] == 0:
        overdue_text = "Просрочек нет ✓"
    else:
        overdue_text = f"{all_stats['overdue']} просрочено"
    nearest = min((t["deadline"] for t in all_tasks_full if t.get("deadline") and t.get("deadline") > today_str and t.get("status") != "Выполнена"), default=None)
    if nearest:
        from datetime import date as ddate
        days_left = (ddate.fromisoformat(nearest) - ddate.today()).days
        nearest_text = f"До ближайшего дедлайна — {days_left} дн."
    else:
        nearest_text = "Активных дедлайнов нет"

    # compute all stats
    all_tasks_full = get_tasks()
    today_str = datetime.now().strftime("%Y-%m-%d")
    total_all = len(all_tasks_full)
    open_all  = sum(1 for t in all_tasks_full if t["status"] in ("Открыта","В работе","На согласовании"))
    done_all  = sum(1 for t in all_tasks_full if t["status"] == "Выполнена")
    over_all  = sum(1 for t in all_tasks_full if t["status"] != "Выполнена" and t.get("deadline","") and t["deadline"] < today_str)
    today_dl  = sum(1 for t in all_tasks_full if t.get("deadline") == today_str and t["status"] != "Выполнена")
    pct_all   = round(done_all/total_all*100) if total_all else 0
    health    = max(0, 100 - over_all*15 - today_dl*5)
    execution = min(100, round(done_all/total_all*100)+50) if total_all else 50
    productivity = min(100, 100 - over_all*10)
    risk_label = "Low" if over_all==0 else ("Medium" if over_all<=2 else "High")
    risk_color = "#10B981" if risk_label=="Low" else ("#F59E0B" if risk_label=="Medium" else "#EF4444")
    future_dl = sorted([t["deadline"] for t in all_tasks_full if t.get("deadline","") > today_str and t["status"] != "Выполнена"])
    if future_dl:
        try:
            days_nearest = (date.fromisoformat(future_dl[0]) - date.today()).days
            nearest_text = f"ближайший дедлайн через {days_nearest} дн."
        except Exception:
            nearest_text = ""
    else:
        nearest_text = "нет активных дедлайнов"
    hero_parts = [
        "Просрочек нет ✓" if over_all==0 else f"{over_all} просрочено",
        f"{open_all} задач в работе", f"{done_all} выполнено", nearest_text
    ]
    hero_summary = " &nbsp;·&nbsp; ".join(hero_parts)
    attention_rows = ""
    attention_count = 0
    for tt in all_tasks_full:
        if tt.get("deadline") == today_str and tt["status"] != "Выполнена":
            attention_rows += f'<div class="att-row att-urgent"><span class="att-icon">⏰</span><span class="att-text">Дедлайн сегодня: <b>{tt["title"][:55]}</b></span><span class="att-who">{tt.get("assignee") or "—"}</span></div>'
            attention_count += 1
    for tt in all_tasks_full:
        if tt.get("deadline","") and tt["deadline"] < today_str and tt["status"] != "Выполнена":
            attention_rows += f'<div class="att-row att-over"><span class="att-icon">🔴</span><span class="att-text">Просрочена: <b>{tt["title"][:55]}</b></span><span class="att-who">{tt.get("assignee") or "—"}</span></div>'
            attention_count += 1
    seen_titles = set()
    for tt in all_tasks_full:
        if tt["status"] != "Выполнена":
            if tt["title"] in seen_titles:
                continue
            cmts = get_task_comments(tt["id"])
            if not cmts:
                seen_titles.add(tt["title"])
                attention_rows += f'<div class="att-row att-info"><span class="att-icon">💬</span><span class="att-text">Нет комментариев: <b>{tt["title"][:55]}</b></span><span class="att-who">{tt.get("assignee") or "—"}</span></div>'
                attention_count += 1
                if attention_count >= 8:
                    break
    if not attention_rows:
        attention_rows = '<div class="att-empty"><span style="font-size:24px;">✅</span><p>Критичных задач нет. Все процессы под контролем.</p></div>'
    workload = {}
    for tt in all_tasks_full:
        if tt["status"] not in ("Выполнена",) and tt.get("assignee"):
            workload[tt["assignee"]] = workload.get(tt["assignee"], 0) + 1
    workload_sorted = sorted(workload.items(), key=lambda x: -x[1])[:5]
    upcoming = sorted([t for t in all_tasks_full if t.get("deadline","") >= today_str and t["status"] != "Выполнена"], key=lambda x: x.get("deadline",""))[:5]
    project_pills = ""
    for p in projects:
        pc = get_project_color(p["name"])
        is_active = p["name"] == selected
        if is_active:
            project_pills += f'<a href="/?project={p["name"]}" class="pill pill-active" style="background:{pc["text"]};color:white;border-color:{pc["text"]};">{p["name"]}</a>'
        else:
            project_pills += f'<a href="/?project={p["name"]}" class="pill" style="color:{pc["text"]};border-color:{pc["border"]}40;">{p["name"]}</a>'
    st_open = sum(1 for t in tasks if t["status"] == "Открыта")
    st_work = sum(1 for t in tasks if t["status"] == "В работе")
    st_done = sum(1 for t in tasks if t["status"] == "Выполнена")
    st_over = sum(1 for t in tasks if t["status"] != "Выполнена" and t.get("deadline","") and t["deadline"] < today_str)
    if over_all == 0 and today_dl == 0:
        ai_text = f"Система стабильна. Просрочек нет. {open_all} задач активны. Следующий дедлайн: {future_dl[0] if future_dl else 'не указан'}."
    elif over_all > 0:
        ai_text = f"Требуется внимание: {over_all} задач просрочено. {done_all} из {total_all} выполнено. Рекомендую провести ревью."
    else:
        ai_text = f"Сегодня {today_dl} задач с дедлайном. {open_all} в работе. Риск: {risk_label}."
    workload_html = "".join(
        f'<div class="workload-row"><div class="wl-name">{name.split()[0]}</div><div class="wl-bar-bg"><div class="wl-bar-fill" style="width:{min(100,cnt*20)}%;"></div></div><div class="wl-count">{cnt}</div></div>'
        for name, cnt in workload_sorted
    ) if workload_sorted else '<div style="font-size:12px;color:var(--muted);">Нет данных</div>'
    upcoming_html = ""
    seen_dl = set()
    for t in upcoming:
        key = t["title"][:40]
        if key in seen_dl:
            continue
        seen_dl.add(key)
        try:
            mon = MONTHS_RU.get(int(t["deadline"][5:7]), "")[:3]
            day = t["deadline"][8:]
        except Exception:
            mon = ""; day = "—"
        short_title = t["title"][:32] + ("…" if len(t["title"]) > 32 else "")
        assignee = (t.get("assignee") or "—").split()[0] if t.get("assignee") else "—"
        upcoming_html += (
            f'<div class="sb-dl" style="display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.05);">' +
            f'<div class="dl-date" style="min-width:34px;height:34px;background:rgba(59,130,246,.1);border-radius:8px;display:flex;flex-direction:column;align-items:center;justify-content:center;flex-shrink:0;">' +
            f'<div style="font-size:13px;font-weight:800;color:#3b82f6;line-height:1;">{day}</div>' +
            f'<div style="font-size:9px;color:#64748b;">{mon}</div></div>' +
            f'<div style="min-width:0;flex:1;">' +
            f'<div style="font-size:12px;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="{t["title"]}">{short_title}</div>' +
            f'<div style="font-size:11px;color:#64748b;margin-top:1px;">{assignee}</div>' +
            f'</div></div>'
        )
    if not upcoming_html:
        upcoming_html = '<div style="font-size:12px;color:var(--muted);">Нет предстоящих дедлайнов</div>'
    pill_all_class = "pill pill-active" if not selected else "pill"
    empty_row = '<tr><td colspan="8"><div class="empty-state"><div style="font-size:40px;margin-bottom:12px;">📭</div><p>Нет задач по выбранным фильтрам</p></div></td></tr>'
    health_label = "Отлично" if health >= 90 else ("Хорошо" if health >= 70 else "Под угрозой")
    health_c = "#10B981" if health >= 80 else ("#F59E0B" if health >= 60 else "#EF4444")

    html = (
        "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n"
        "<meta charset=\"UTF-8\">\n<meta name=\"viewport\" content=\"width=device-width,initial-scale=1.0\">\n"
        "<title>Executive Command Center</title>\n"
        "<style>\n"
        ":root{--bg:#f4f6fb;--surface:#ffffff;--surface2:#f8faff;--accent:#4f7ef7;--accent2:#6366f1;--red:#e05c5c;--emerald:#16a37a;--amber:#d97706;--purple:#7c3aed;--muted:#64748b;--text:#0f172a;--text2:#475569;--border:#e2e8f0;--shadow:0 1px 3px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.04);}\n"
        "*{box-sizing:border-box;margin:0;padding:0;}\n"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}\n"
        ".topbar{background:rgba(15,22,41,.96);backdrop-filter:blur(20px);border-bottom:1px solid rgba(148,163,184,.1);padding:0 32px;height:60px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;}\n"
        ".topbar-brand{display:flex;align-items:center;gap:12px;}\n"
        ".logo{width:32px;height:32px;background:linear-gradient(135deg,#4f8ef7,#8b78f0);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;}\n"
        ".topbar-brand h1{font-size:14px;font-weight:700;letter-spacing:.5px;color:var(--text);}\n"
        ".topbar-brand p{font-size:11px;color:var(--muted);margin-top:1px;}\n"
        ".topbar-right{display:flex;align-items:center;gap:8px;}\n"
        ".tb-btn{padding:6px 14px;border-radius:20px;font-size:12px;font-weight:600;text-decoration:none;cursor:pointer;border:none;transition:all .2s;letter-spacing:.3px;}\n"
        ".tb-ghost{color:var(--muted);background:transparent;border:1px solid var(--border);}\n"
        ".tb-ghost:hover{color:var(--text);background:var(--surface2);}\n"
        ".tb-blue{color:white;background:var(--accent);}\n"
        ".tb-blue:hover{background:#2563eb;}\n"
        ".hero{position:relative;overflow:hidden;padding:36px 32px;background:linear-gradient(135deg,#0f1629 0%,#162448 60%,#0f1629 100%);border-bottom:1px solid var(--border);}\n"
        ".hero::before{content:\'\';position:absolute;top:-80px;right:-40px;width:320px;height:320px;background:radial-gradient(circle,rgba(79,142,247,.08) 0%,transparent 70%);pointer-events:none;}\n"
        ".hero::after{content:\'\';position:absolute;bottom:-60px;left:35%;width:400px;height:260px;background:radial-gradient(circle,rgba(59,130,246,.07) 0%,transparent 70%);pointer-events:none;}\n"
        ".redline{position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,#4f8ef7 40%,#8b78f0 60%,transparent);}\n"
        ".hero-inner{position:relative;z-index:1;display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap;}\n"
        ".eyebrow{font-size:10px;font-weight:700;letter-spacing:2px;color:#ef4444;text-transform:uppercase;margin-bottom:6px;}\n"
        ".hero-h2{font-size:26px;font-weight:800;letter-spacing:-1px;background:linear-gradient(135deg,#fff 60%,#94a3b8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;}\n"
        ".hero-sub{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.8;}\n"
        ".scores{display:flex;gap:10px;flex-wrap:wrap;}\n"
        ".score{background:rgba(26,37,64,.9);border:1px solid rgba(148,163,184,.12);border-radius:14px;padding:12px 16px;text-align:center;min-width:80px;transition:transform .2s;}\n"
        ".score:hover{transform:translateY(-2px);}\n"
        ".score .val{font-size:20px;font-weight:800;color:white;}\n"
        ".score .lbl{font-size:10px;color:rgba(255,255,255,.7);margin-top:2px;letter-spacing:.4px;}\n"
        ".ai-card{margin:20px 32px;background:rgba(79,142,247,.05);border:1px solid rgba(79,142,247,.15);border-radius:14px;padding:16px 20px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;}\n"
        ".ai-icon{width:38px;height:38px;background:linear-gradient(135deg,#4f8ef7,#8b78f0);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0;}\n"
        ".ai-text{flex:1;font-size:13px;color:#374151;line-height:1.5;}\n"
        ".ai-text strong{color:#1e3a8a;}\n"
        ".ai-acts{display:flex;gap:7px;flex-wrap:wrap;}\n"
        ".ai-btn{padding:5px 12px;border-radius:20px;font-size:11px;font-weight:500;cursor:pointer;border:1px solid #bfdbfe;background:white;color:#1d4ed8;text-decoration:none;transition:all .15s;}\n"
        ".ai-btn:hover{background:#eff6ff;border-color:#93c5fd;}\n"
        ".page{display:grid;grid-template-columns:1fr 280px;gap:0;}\n"
        ".content{padding:22px 32px;}\n"
        ".sidebar{padding:22px 16px 22px 0;border-left:1px solid var(--border);}\n"
        ".kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:20px;}\n"
        ".kpi{background:rgba(26,37,64,.8);border:1px solid rgba(148,163,184,.1);border-radius:14px;padding:16px;position:relative;overflow:hidden;transition:transform .2s,border-color .2s,box-shadow .2s;cursor:default;}\n"
        ".kpi:hover{transform:translateY(-3px);border-color:#93c5fd;box-shadow:0 8px 24px rgba(79,126,247,.12);}\n"
        ".kpi-top{position:absolute;top:0;left:0;right:0;height:2px;}\n"
        ".kpi-icon{font-size:18px;margin-bottom:8px;}\n"
        ".kpi-num{font-size:28px;font-weight:800;letter-spacing:-1px;line-height:1;}\n"
        ".kpi-label{font-size:11px;color:#64748b;margin-top:3px;font-weight:500;}\n"
        ".kpi-sub{font-size:10px;color:#94a3b8;margin-top:6px;padding-top:6px;border-top:1px solid #f1f5f9;opacity:.9;}\n"
        ".prog-card{background:white;border:1px solid var(--border);box-shadow:var(--shadow);border-radius:14px;padding:18px 20px;margin-bottom:18px;}\n"
        ".prog-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;}\n"
        ".prog-title{font-size:13px;font-weight:600;color:var(--text);}\n"
        ".prog-insight{font-size:11px;color:var(--muted);margin-top:3px;}\n"
        ".prog-pct{font-size:26px;font-weight:800;color:var(--accent);}\n"
        ".bar-bg{background:#e2e8f0;border-radius:999px;height:7px;overflow:hidden;margin-bottom:10px;}\n"
        ".bar-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,#4f8ef7,#7b6cf6,#8b78f0);animation:fb .8s ease;}\n"
        "@keyframes fb{from{width:0%}}\n"
        ".sdots{display:flex;gap:14px;flex-wrap:wrap;}\n"
        ".sdot{display:flex;align-items:center;gap:5px;font-size:11px;color:#64748b;}\n"
        ".sdot-c{width:7px;height:7px;border-radius:50%;flex-shrink:0;}\n"
        ".att-card{background:white;border:1px solid var(--border);box-shadow:var(--shadow);border-radius:14px;padding:16px;margin-bottom:18px;}\n"
        ".att-title{font-size:13px;font-weight:700;color:var(--text);margin-bottom:10px;display:flex;align-items:center;gap:8px;}\n"
        ".att-row{display:flex;align-items:center;gap:9px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:12px;}\n"
        ".att-row:last-child{border-bottom:none;}\n"
        ".att-icon{font-size:13px;flex-shrink:0;}\n"
        ".att-text{flex:1;color:#374151;}\n"
        ".att-text b{color:#0f172a;}\n"
        ".att-who{font-size:11px;color:#94a3b8;white-space:nowrap;}\n"
        ".att-urgent,.att-over{border-left:2px solid #ef4444;padding-left:9px;margin-left:-9px;}\n"
        ".att-info{border-left:2px solid #3b82f6;padding-left:9px;margin-left:-9px;}\n"
        ".att-empty{text-align:center;padding:18px;color:#94a3b8;font-size:13px;}\n"
        ".att-empty p{margin-top:6px;}\n"
        ".ctrl-bar{background:white;border:1px solid var(--border);box-shadow:var(--shadow);border-radius:12px;padding:10px 14px;margin-bottom:14px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;}\n"
        ".pill{padding:5px 13px;border-radius:20px;font-size:12px;font-weight:500;text-decoration:none;border:1px solid var(--border);color:var(--muted);background:var(--surface2);transition:all .15s;white-space:nowrap;}\n"
        ".pill:hover{color:var(--text);border-color:#93c5fd;background:#eff6ff;}\n"
        ".pill-active{background:#1d4ed8!important;color:white!important;border-color:#1d4ed8!important;}\n"
        ".srch{position:relative;flex:1;min-width:180px;}\n"
        ".srch input{width:100%;padding:7px 12px 7px 32px;border:1px solid var(--border);border-radius:20px;font-size:12px;background:rgba(15,22,41,.8);color:#e8edf5;outline:none;transition:all .15s;}\n"
        ".srch input::placeholder{color:var(--muted);}\n"
        ".srch input:focus{border-color:rgba(79,142,247,.4);background:rgba(79,142,247,.05);}\n"
        ".srch-ico{position:absolute;left:10px;top:50%;transform:translateY(-50%);font-size:12px;opacity:.5;}\n"
        "select{padding:6px 11px;border:1px solid var(--border);border-radius:20px;font-size:12px;background:rgba(15,22,41,.8);color:#e8edf5;cursor:pointer;outline:none;}\n"
        "select option{background:white;color:#0f172a;}\n"
        ".btn-reset{padding:6px 13px;background:transparent;color:var(--muted);border:1px solid var(--border);border-radius:20px;font-size:12px;cursor:pointer;text-decoration:none;transition:all .15s;}\n"
        ".btn-reset:hover{color:var(--text);background:var(--surface2);}\n"
        ".tbl-wrap{background:white;border:1px solid var(--border);border-radius:14px;overflow:hidden;box-shadow:var(--shadow);}\n"
        ".tbl-wrap table{width:100%;border-collapse:collapse;}\n"
        ".tbl-wrap thead th{padding:10px 13px;font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;background:#f8fafc;border-bottom:1px solid rgba(255,255,255,.08);white-space:nowrap;position:sticky;top:60px;z-index:10;}\n"
        ".task-row{border-bottom:1px solid #f1f5f9;transition:background .1s;background:white !important;}\n"
        ".task-row:hover{background:#f8faff !important;}\n"
        ".task-row td{padding:13px;vertical-align:middle;color:#1e293b !important;}\n"
        ".act-btn{width:30px;height:30px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:13px;text-decoration:none;border:none;cursor:pointer;transition:all .15s;background:#f1f5f9;}\n"
        ".row-acts{display:flex;gap:3px;opacity:0;transition:opacity .15s;}\n"
        ".task-row:hover .row-acts{opacity:1;}\n"
        ".empty-st{text-align:center;padding:50px;color:#94a3b8;}\n"
        ".sb-sec{margin-bottom:18px;padding:0 10px;}\n"
        ".sb-title{font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;margin-bottom:10px;}\n"
        ".sb-dl{display:flex;align-items:center;gap:9px;padding:7px 0;border-bottom:1px solid #f1f5f9;}\n"
        ".sb-dl:last-child{border-bottom:none;}\n"
        ".dl-date{width:34px;height:34px;background:#eff6ff;border-radius:8px;display:flex;flex-direction:column;align-items:center;justify-content:center;flex-shrink:0;}\n"
        ".dl-day{font-size:13px;font-weight:800;color:#1d4ed8;line-height:1;}\n"
        ".dl-mon{font-size:9px;color:var(--muted);}\n"
        ".dl-info .tl{font-size:12px;color:#334155;line-height:1.3;}\n"
        ".dl-info .wh{font-size:11px;color:#94a3b8;margin-top:1px;}\n"
        ".wl-row{display:flex;align-items:center;gap:7px;margin-bottom:7px;}\n"
        ".wl-name{font-size:11px;color:#475569;width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex-shrink:0;}\n"
        ".wl-bg{flex:1;background:#e2e8f0;border-radius:999px;height:4px;overflow:hidden;}\n"
        ".wl-fill{height:100%;background:linear-gradient(90deg,#4f8ef7,#8b78f0);border-radius:999px;}\n"
        ".wl-cnt{font-size:11px;color:#94a3b8;width:16px;text-align:right;}\n"
        ".qa-btn{padding:8px 13px;border-radius:10px;font-size:12px;font-weight:500;text-decoration:none;border:1px solid var(--border);color:#475569;background:var(--surface2);transition:all .15s;display:flex;align-items:center;gap:7px;margin-bottom:5px;}\n"
        ".qa-btn:hover{background:#eff6ff;color:#1d4ed8;border-color:#93c5fd;}\n"
        ".cmd-ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:1000;align-items:flex-start;justify-content:center;padding-top:14vh;}\n"
        ".cmd-ov.open{display:flex;}\n"
        ".cmd-box{background:#1a2540;border:1px solid rgba(148,163,184,.15);border-radius:16px;width:540px;max-width:95vw;overflow:hidden;box-shadow:0 20px 60px rgba(0,0,0,.6);}\n"
        ".cmd-inp{width:100%;padding:15px 18px;background:transparent;border:none;border-bottom:1px solid var(--border);color:var(--text);font-size:14px;outline:none;}\n"
        ".cmd-inp::placeholder{color:#94a3b8;}\n"
        ".cmd-items{padding:6px;}\n"
        ".cmd-item{display:flex;align-items:center;gap:11px;padding:9px 11px;border-radius:8px;cursor:pointer;font-size:13px;color:#374151;transition:background .1s;}\n"
        ".cmd-item:hover{background:#eff6ff;color:#1d4ed8;}\n"
        ".more-dropdown{display:none;position:absolute;right:0;top:34px;background:#1a2540;border:1px solid rgba(148,163,184,.15);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.5);z-index:100;min-width:150px;padding:5px 0;}\n"
        ".more-dropdown a{display:flex;align-items:center;gap:9px;padding:8px 14px;color:#374151;text-decoration:none;font-size:12px;}\n"
        ".more-dropdown a:hover{background:#f8fafc;color:#1d4ed8;}\n"
        "@media(max-width:1050px){.page{grid-template-columns:1fr;}.sidebar{display:none;}}\n"
        "@media(max-width:680px){.hero-inner{flex-direction:column;}.scores{justify-content:center;}.content{padding:14px;}.kpi-grid{grid-template-columns:repeat(2,1fr);}.topbar{padding:0 14px;}.topbar-brand p{display:none;}.tbl-wrap table thead{display:none;}.task-row{display:block;margin:6px;border-radius:10px;border:1px solid var(--border);}.task-row td{display:flex;justify-content:space-between;align-items:center;padding:7px 11px;border-bottom:1px solid rgba(255,255,255,.04);}}\n"
        "</style>\n"
        "</head>\n<body>\n"
    )

    # topbar
    html += (
        "<div class=\"topbar\">\n"
        "  <div class=\"topbar-brand\"><div class=\"logo\">⚡</div><div>"
        "<h1>EXECUTIVE COMMAND CENTER</h1>"
        "<p>Контроль задач, сроков и исполнения</p>"
        "</div></div>\n"
        "  <div class=\"topbar-right\">"
        "<a href=\"/calendar\" class=\"tb-btn tb-ghost\">📅 Календарь</a>"
        "<a href=\"/newtask\" class=\"tb-btn tb-blue\">+ Задача</a>"
        "<button class=\"tb-btn tb-ghost\" onclick=\"openCmd()\" title=\"Ctrl+K\">⌘K</button>"
        "</div>\n</div>\n"
    )

    # hero
    html += (
        "<div class=\"hero\"><div class=\"redline\"></div>\n"
        "<div class=\"hero-inner\">\n"
        "  <div>\n"
        f"    <div class=\"eyebrow\" style=\"color:rgba(255,255,255,.8);\">Command Center · Live</div>\n"
        f"    <div class=\"hero-h2\">Компания под контролем</div>\n"
        f"    <div class=\"hero-sub\" style=\"color:rgba(255,255,255,.85);\">{hero_summary}</div>\n"
        "  </div>\n"
        "  <div class=\"scores\">\n"
        f"    <div class=\"score\"><div class=\"val\" style=\"color:{health_c};\">{health}%</div><div class=\"lbl\">Health</div></div>\n"
        f"    <div class=\"score\"><div class=\"val\" style=\"color:#3b82f6;\">{execution}%</div><div class=\"lbl\">Execution</div></div>\n"
        f"    <div class=\"score\"><div class=\"val\" style=\"color:#8b5cf6;\">{productivity}%</div><div class=\"lbl\">Productivity</div></div>\n"
        f"    <div class=\"score\"><div class=\"val\" style=\"color:{risk_color};\">{risk_label}</div><div class=\"lbl\">Risk</div></div>\n"
        "  </div>\n"
        "</div>\n</div>\n"
    )

    # ai card
    html += (
        "<div class=\"ai-card\">\n"
        "  <div class=\"ai-icon\">🤖</div>\n"
        f"  <div class=\"ai-text\"><strong>AI Executive:</strong> {ai_text}</div>\n"
        "  <div class=\"ai-acts\">"
        "<a href=\"/?status=Просрочена\" class=\"ai-btn\">⚠️ Внимание</a>"
        "<a href=\"/\" class=\"ai-btn\">📊 Отчет</a>"
        "</div>\n</div>\n"
    )

    # page layout
    html += "<div class=\"page\">\n<div class=\"content\">\n"

    # kpi
    kpi_items = [
        ("linear-gradient(90deg,#3b82f6,#6366f1)", "📋", str(total_all), "white", "Всего задач", "Все проекты"),
        ("linear-gradient(90deg,#f59e0b,#f97316)", "⚡", str(open_all), "#f59e0b", "В работе", "Активных"),
        ("linear-gradient(90deg,#10b981,#06b6d4)", "✅", str(done_all), "#10b981", "Выполнено", f"{pct_all}% прогресс"),
        ("linear-gradient(90deg,#ef4444,#dc2626)", "🔴", str(over_all), "#ef4444", "Просрочено", "Всё ок" if over_all==0 else "Внимание!"),
        ("linear-gradient(90deg,#8b5cf6,#a78bfa)", "📅", str(today_dl), "#8b5cf6", "Дедлайн сегодня", "Нет срочных" if today_dl==0 else "Срочно!"),
        ("linear-gradient(90deg,#06b6d4,#3b82f6)", "💎", f"{health}%", "#06b6d4", "Health Score", health_label),
    ]
    html += "<div class=\"kpi-grid\">\n"
    for grad, icon, num, color, label, sub in kpi_items:
        html += f"  <div class=\"kpi\"><div class=\"kpi-top\" style=\"background:{grad};\"></div><div class=\"kpi-icon\">{icon}</div><div class=\"kpi-num\" style=\"color:{color};\">{num}</div><div class=\"kpi-label\">{label}</div><div class=\"kpi-sub\">{sub}</div></div>\n"
    html += "</div>\n"

    # progress
    html += (
        "<div class=\"prog-card\">\n"
        "  <div class=\"prog-head\">\n"
        f"    <div><div class=\"prog-title\">📊 Прогресс: {title}</div>"
        f"<div class=\"prog-insight\">Выполнено {st_done} из {stats['total']} задач{'.' if over_all==0 else f'. Просрочено: {over_all}.'}</div></div>\n"
        f"    <div class=\"prog-pct\">{stats['percent']}%</div>\n"
        "  </div>\n"
        f"  <div class=\"bar-bg\"><div class=\"bar-fill\" style=\"width:{stats['percent']}%;\"></div></div>\n"
        "  <div class=\"sdots\">\n"
        f"    <div class=\"sdot\"><div class=\"sdot-c\" style=\"background:#3b82f6;\"></div>Открыто: {st_open}</div>\n"
        f"    <div class=\"sdot\"><div class=\"sdot-c\" style=\"background:#f59e0b;\"></div>В работе: {st_work}</div>\n"
        f"    <div class=\"sdot\"><div class=\"sdot-c\" style=\"background:#10b981;\"></div>Выполнено: {st_done}</div>\n"
        f"    <div class=\"sdot\"><div class=\"sdot-c\" style=\"background:#ef4444;\"></div>Просрочено: {st_over}</div>\n"
        "  </div>\n</div>\n"
    )

    # controls
    all_pill = "pill pill-active" if not selected else "pill"
    html += (
        "<div class=\"ctrl-bar\">\n"
        f"  <a href=\"/\" class=\"{all_pill}\">Все проекты</a>\n"
        f"  {project_pills}\n"
        "  <form method=\"get\" style=\"display:contents;\">\n"
        f"    <input type=\"hidden\" name=\"project\" value=\"{selected}\">\n"
        f"    <input type=\"hidden\" name=\"status\" value=\"{status_filter}\">\n"
        "    <div class=\"srch\"><span class=\"srch-ico\">🔍</span>"
        f"<input type=\"text\" name=\"q\" value=\"{search_value}\" placeholder=\"Поиск по ID, названию, ответственному...\" oninput=\"clearTimeout(this._t);this._t=setTimeout(()=>this.form.submit(),400)\"></div>\n"
        "  </form>\n"
        "  <form method=\"get\" style=\"display:contents;\">\n"
        f"    <input type=\"hidden\" name=\"project\" value=\"{selected}\">\n"
        f"    <input type=\"hidden\" name=\"q\" value=\"{search_value}\">\n"
        f"    <select name=\"status\" onchange=\"this.form.submit()\"><option value=\"\">Все статусы</option>{status_options}</select>\n"
        "  </form>\n"
        "  <a href=\"/\" class=\"btn-reset\">Сбросить</a>\n"
        "</div>\n"
    )

    # table
    table_body = rows if rows else '<tr><td colspan="8"><div class="empty-st"><div style="font-size:36px;margin-bottom:10px;">📭</div><p>Нет задач по выбранным фильтрам</p></div></td></tr>'
    html += (
        "<div class=\"tbl-wrap\">\n<table>\n"
        "<thead><tr><th>ID</th><th>Задача</th><th>Ответственный</th><th>Проект</th>"
        "<th>Срок</th><th>Статус</th><th>Комментарии</th><th>Действия</th></tr></thead>\n"
        f"<tbody>{table_body}</tbody>\n</table>\n</div>\n"
    )

    # attention (moved below table)
    html += (
        "<div class=\"att-card\" style=\"margin-top:18px;\">\n"
        f"  <div class=\"att-title\">⚠️ Требует внимания "
        f"<span style=\"background:rgba(239,68,68,.15);color:#ef4444;padding:2px 8px;border-radius:10px;font-size:10px;\">{attention_count}</span></div>\n"
        f"  {attention_rows}\n"
        "</div>\n"
    )

    html += "</div>\n"  # /content

    # sidebar
    html += (
        "<div class=\"sidebar\">\n"
        "<div class=\"sb-sec\"><div class=\"sb-title\">Ближайшие дедлайны</div>\n"
        f"{upcoming_html}</div>\n"
        "<div class=\"sb-sec\"><div class=\"sb-title\">Нагрузка команды</div>\n"
        f"{workload_html}</div>\n"
        "<div class=\"sb-sec\"><div class=\"sb-title\">Быстрые действия</div>\n"
        "<a href=\"/newtask\" class=\"qa-btn\">➕ Создать задачу</a>\n"
        "<a href=\"/calendar\" class=\"qa-btn\">📅 Календарь</a>\n"
        "<a href=\"/?status=Просрочена\" class=\"qa-btn\">🔴 Просроченные</a>\n"
        "<a href=\"/?status=Открыта\" class=\"qa-btn\">🔵 Открытые</a>\n"
        "</div>\n</div>\n"
    )

    html += "</div>\n"  # /page

    # command palette
    html += (
        "<div class=\"cmd-ov\" id=\"cmdOv\" onclick=\"if(event.target===this)closeCmd()\">\n"
        "  <div class=\"cmd-box\">\n"
        "    <input class=\"cmd-inp\" id=\"cmdIn\" placeholder=\"Поиск задач, действий...\" oninput=\"filterCmd(this.value)\" autocomplete=\"off\">\n"
        "    <div class=\"cmd-items\" id=\"cmdIt\">\n"
        "      <div class=\"cmd-item\" onclick=\"location='/'\" >📋 Все задачи</div>\n"
        "      <div class=\"cmd-item\" onclick=\"location='/newtask'\" >➕ Создать задачу</div>\n"
        "      <div class=\"cmd-item\" onclick=\"location='/calendar'\" >📅 Открыть календарь</div>\n"
        "      <div class=\"cmd-item\" onclick=\"location='/?status=Просрочена'\" >🔴 Просроченные задачи</div>\n"
        "      <div class=\"cmd-item\" onclick=\"location='/?status=Открыта'\" >🔵 Открытые задачи</div>\n"
        "      <div class=\"cmd-item\" onclick=\"location='/?status=Выполнена'\" >✅ Выполненные</div>\n"
        "    </div>\n  </div>\n</div>\n"
    )

    html += (
        "<script>\n"
        "function openCmd(){document.getElementById('cmdOv').classList.add('open');document.getElementById('cmdIn').focus();}\n"
        "function closeCmd(){document.getElementById('cmdOv').classList.remove('open');}\n"
        "document.addEventListener('keydown',function(e){if((e.ctrlKey||e.metaKey)&&e.key==='k'){e.preventDefault();openCmd();}if(e.key==='Escape')closeCmd();});\n"
        "function filterCmd(v){document.querySelectorAll('#cmdIt .cmd-item').forEach(function(el){el.style.display=v&&!el.textContent.toLowerCase().includes(v.toLowerCase())?'none':'';});}\n"
        "function toggleMenu(btn){var m=btn.nextElementSibling;document.querySelectorAll('.more-dropdown').forEach(function(d){if(d!==m)d.style.display='none';});m.style.display=m.style.display==='block'?'none':'block';event.stopPropagation();}\n"
        "document.addEventListener('click',function(){document.querySelectorAll('.more-dropdown').forEach(function(m){m.style.display='none';});});\n"
        "</script>\n</body>\n</html>"
    )

    return web.Response(text=html, content_type="text/html")

@routes.get("/done/{task_id}")
async def mark_done(request):
    task_id = int(request.match_info["task_id"])
    author = request.rel_url.query.get("author", "Дашборд")
    update_status(task_id, "Выполнена", changed_by=author)
    back = request.rel_url.query.get("back", "/")
    raise web.HTTPFound(back)

@routes.get("/reopen/{task_id}")
async def reopen_task(request):
    task_id = int(request.match_info["task_id"])
    author = request.rel_url.query.get("author", "Дашборд")
    update_status(task_id, "Открыта", changed_by=author)
    back = request.rel_url.query.get("back", "/")
    raise web.HTTPFound(back)



# ─── Страница создания задачи ───────────────────────────────────────────────
@routes.get("/newtask")
async def newtask_page(request):
    projects = get_projects()
    project_options = "".join(f'<option value="{p["name"]}">{p["name"]}</option>' for p in projects)
    managers = ["Абдуллах Н.","Камалов Н.","Кострыкин И.","Яманова Э.","Аскарова М.",
                "Кульбаева Б.","Мырзағали Е.","Елемес Е.","Оспанова А.","Луданная Л.",
                "Маркелова И.","Мустафина А.","Куниязов З."]
    manager_options = "".join(f'<option value="{m}">{m}</option>' for m in managers)
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Новая задача</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1629;color:#e8edf5;min-height:100vh;}}
.topbar{{background:rgba(10,15,30,.96);border-bottom:1px solid rgba(255,255,255,.08);padding:0 32px;height:60px;display:flex;align-items:center;gap:16px;}}
.topbar a{{color:rgba(255,255,255,.6);text-decoration:none;font-size:13px;}}
.topbar h1{{font-size:15px;font-weight:700;color:white;}}
.wrap{{max-width:560px;margin:40px auto;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:20px;padding:32px;}}
label{{display:block;font-size:12px;font-weight:600;color:#94a3b8;margin-bottom:6px;margin-top:18px;text-transform:uppercase;letter-spacing:.05em;}}
input,select,textarea{{width:100%;padding:10px 14px;border:1px solid rgba(255,255,255,.1);border-radius:10px;font-size:14px;font-family:inherit;background:rgba(255,255,255,.06);color:#f1f5f9;outline:none;transition:all .15s;}}
input:focus,select:focus,textarea:focus{{border-color:rgba(59,130,246,.5);background:rgba(59,130,246,.06);}}
select option{{background:#1e293b;}}
textarea{{height:80px;resize:vertical;}}
.btns{{display:flex;gap:10px;margin-top:24px;}}
.btn-save{{padding:11px 24px;background:#3b82f6;color:white;border:none;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;transition:all .2s;}}
.btn-save:hover{{background:#2563eb;transform:translateY(-1px);}}
.btn-cancel{{padding:11px 24px;background:rgba(255,255,255,.06);color:#94a3b8;border:1px solid rgba(255,255,255,.1);border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;transition:all .2s;}}
.btn-cancel:hover{{background:rgba(255,255,255,.1);color:white;}}
</style>
</head>
<body>
<div class="topbar">
  <a href="/">← Назад</a>
  <h1>➕ Новая задача</h1>
</div>
<div class="wrap">
  <form method="post" action="/newtask">
    <label>Название задачи *</label>
    <input type="text" name="title" required placeholder="Что нужно сделать?">
    <label>Ответственный</label>
    <select name="assignee"><option value="">— Выберите —</option>{manager_options}</select>
    <label>Проект</label>
    <select name="project"><option value="Общие">Общие</option>{project_options}</select>
    <label>Срок</label>
    <input type="date" name="deadline">
    <label>Отдел</label>
    <input type="text" name="department" placeholder="Например: Бухгалтерия">
    <label>Комментарий</label>
    <textarea name="comment" placeholder="Дополнительная информация..."></textarea>
    <div class="btns">
      <button type="submit" class="btn-save">💾 Создать задачу</button>
      <a href="/" class="btn-cancel">Отмена</a>
    </div>
  </form>
</div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


@routes.post("/newtask")
async def newtask_save(request):
    data = await request.post()
    title = data.get("title","").strip()
    if not title:
        raise web.HTTPFound("/newtask")
    add_task(
        project=data.get("project","Общие"),
        assignee=data.get("assignee",""),
        department=data.get("department",""),
        title=title,
        deadline=data.get("deadline",""),
        comment=data.get("comment",""),
    )
    raise web.HTTPFound("/")


def create_app():
    app = web.Application()
    app.add_routes(routes)
    return app

# ─── Страница редактирования задачи ────────────────────────────────────────
@routes.get("/edit/{task_id}")
async def edit_task_page(request):
    task_id = int(request.match_info["task_id"])
    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise web.HTTPFound("/")
    back = request.rel_url.query.get("back", "/")
    projects = get_projects()
    project_options = "".join(
        f'<option value="{p["name"]}" {"selected" if p["name"] == task["project"] else ""}>{p["name"]}</option>'
        for p in projects
    )
    status_options = "".join(
        f'<option value="{s}" {"selected" if s == task["status"] else ""}>{s}</option>'
        for s in ["Открыта", "В работе", "Выполнена", "На согласовании", "Просрочена", "Заблокирована"]
    )
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Редактировать задачу #{task_id}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F9FAFB; color: #111827; }}
.header {{ background: #1E293B; color: white; padding: 20px 32px; }}
.header h1 {{ font-size: 20px; font-weight: 700; }}
.form-wrap {{ max-width: 600px; margin: 32px auto; background: white; border-radius: 12px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
label {{ display: block; font-size: 13px; font-weight: 600; color: #374151; margin-bottom: 6px; margin-top: 16px; }}
input, select, textarea {{ width: 100%; padding: 10px 12px; border: 1px solid #E5E7EB; border-radius: 8px; font-size: 14px; font-family: inherit; }}
textarea {{ height: 80px; resize: vertical; }}
.btns {{ display: flex; gap: 12px; margin-top: 24px; }}
.btn-save {{ padding: 10px 24px; background: #3B82F6; color: white; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; }}
.btn-cancel {{ padding: 10px 24px; background: #F3F4F6; color: #374151; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; }}
</style>
</head>
<body>
<div class="header"><h1>✏️ Редактировать задачу #{task_id}</h1></div>
<div class="form-wrap">
  <form method="post" action="/edit/{task_id}?back={back}">
    <label>Задача</label>
    <input type="text" name="title" value="{task['title'] or ''}" required>
    <label>Ответственный</label>
    <input type="text" name="assignee" value="{task['assignee'] or ''}">
    <label>Отдел</label>
    <input type="text" name="department" value="{task['department'] or ''}">
    <label>Проект</label>
    <select name="project">{project_options}</select>
    <label>Срок</label>
    <input type="date" name="deadline" value="{task['deadline'] or ''}">
    <label>Статус</label>
    <select name="status">{status_options}</select>
    <label>Комментарий</label>
    <textarea name="comment">{task['comment'] or ''}</textarea>
    <label>Ваше имя (для истории)</label>
    <input type="text" name="editor_name" placeholder="Введите ваше имя" required>
    <div class="btns">
      <button type="submit" class="btn-save">💾 Сохранить</button>
      <a href="{back}" class="btn-cancel">Отмена</a>
    </div>
  </form>
</div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


@routes.post("/edit/{task_id}")
async def edit_task_save(request):
    task_id = int(request.match_info["task_id"])
    back = request.rel_url.query.get("back", "/")
    data = await request.post()
    from database import get_conn
    from database import get_conn
    author = data.get("editor_name", "Дашборд")
    tasks_list = get_tasks()
    old_task = next((t for t in tasks_list if t["id"] == task_id), {})
    fields = {"title": "title", "assignee": "assignee", "department": "department",
              "project": "project", "deadline": "deadline", "status": "status", "comment": "comment"}
    with get_conn() as conn:
        conn.execute(
            "UPDATE tasks SET title=?, assignee=?, department=?, project=?, deadline=?, status=?, comment=? WHERE id=?",
            (
                data.get("title", ""),
                data.get("assignee", ""),
                data.get("department", ""),
                data.get("project", ""),
                data.get("deadline", ""),
                data.get("status", "Открыта"),
                data.get("comment", ""),
                task_id,
            )
        )
        for key, db_key in fields.items():
            new_val = data.get(key, "")
            old_val = str(old_task.get(db_key) or "")
            if new_val != old_val:
                conn.execute(
                    "INSERT INTO task_history (task_id, changed_by, field, old_value, new_value) VALUES (?,?,?,?,?)",
                    (task_id, author, key, old_val, new_val)
                )
    raise web.HTTPFound(back)


# ─── Страница комментария ───────────────────────────────────────────────────
@routes.get("/comment/{task_id}")
async def comment_task_page(request):
    task_id = int(request.match_info["task_id"])
    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise web.HTTPFound("/")
    back = request.rel_url.query.get("back", "/")
    comments = get_task_comments(task_id)
    comments_html = ""
    for c in comments:
        time = c.get("created_at", "")[:16]
        if c.get("file_id"):
            comments_html += f'<div class="comment"><span class="author">📎 {c["author"]}</span><span class="time">{time}</span><div>{c["file_name"]} {c.get("text","")}</div></div>'
        else:
            comments_html += f'<div class="comment"><span class="author">💬 {c["author"]}</span><span class="time">{time}</span><div>{c.get("text","")}</div></div>'
    if not comments_html:
        comments_html = '<div style="color:#9CA3AF;font-size:13px;">Комментариев пока нет</div>'
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Комментарии к задаче #{task_id}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F9FAFB; color: #111827; }}
.header {{ background: #1E293B; color: white; padding: 20px 32px; }}
.header h1 {{ font-size: 20px; font-weight: 700; }}
.header p {{ opacity: 0.7; font-size: 13px; margin-top: 4px; }}
.wrap {{ max-width: 600px; margin: 32px auto; }}
.card {{ background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 16px; }}
.comment {{ padding: 12px 0; border-bottom: 1px solid #F3F4F6; }}
.comment:last-child {{ border-bottom: none; }}
.author {{ font-weight: 600; font-size: 13px; color: #374151; }}
.time {{ font-size: 11px; color: #9CA3AF; margin-left: 8px; }}
textarea {{ width: 100%; padding: 10px 12px; border: 1px solid #E5E7EB; border-radius: 8px; font-size: 14px; font-family: inherit; height: 100px; resize: vertical; margin-top: 12px; }}
input[type=text] {{ width: 100%; padding: 10px 12px; border: 1px solid #E5E7EB; border-radius: 8px; font-size: 14px; margin-top: 8px; }}
label {{ font-size: 13px; font-weight: 600; color: #374151; }}
.btns {{ display: flex; gap: 12px; margin-top: 16px; }}
.btn-save {{ padding: 10px 24px; background: #7C3AED; color: white; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; }}
.btn-cancel {{ padding: 10px 24px; background: #F3F4F6; color: #374151; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; }}
</style>
</head>
<body>
<div class="header">
  <h1>💬 Комментарии к задаче #{task_id}</h1>
  <p>{task['title']}</p>
</div>
<div class="wrap">
  <div class="card">
    <strong>История комментариев</strong>
    <div style="margin-top:12px;">{comments_html}</div>
  </div>
  <div class="card">
    <form method="post" action="/comment/{task_id}?back={back}">
      <label>Автор</label>
      <input type="text" name="author" placeholder="Ваше имя" required>
      <label style="margin-top:12px;display:block;">Комментарий</label>
      <textarea name="text" placeholder="Напишите комментарий..." required></textarea>
      <div class="btns">
        <button type="submit" class="btn-save">💬 Отправить</button>
        <a href="{back}" class="btn-cancel">Отмена</a>
      </div>
    </form>
  </div>
</div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


@routes.post("/comment/{task_id}")
async def comment_task_save(request):
    task_id = int(request.match_info["task_id"])
    back = request.rel_url.query.get("back", "/")
    data = await request.post()
    author = data.get("author", "Аноним")
    text = data.get("text", "").strip()
    if text:
        add_task_comment(task_id=task_id, author=author, text=text)
    raise web.HTTPFound(f"/comment/{task_id}?back={back}")


# ─── Страница вложений ──────────────────────────────────────────────────────
@routes.get("/attach/{task_id}")
async def attach_task_page(request):
    task_id = int(request.match_info["task_id"])
    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise web.HTTPFound("/")
    back = request.rel_url.query.get("back", "/")
    comments = get_task_comments(task_id)
    files = [c for c in comments if c.get("file_id")]
    files_html = ""
    for f in files:
        time = f.get("created_at", "")[:16]
        files_html += f'<div class="file-item">📎 <strong>{f["file_name"]}</strong> — {f["author"]} <span style="color:#9CA3AF;font-size:11px;">{time}</span></div>'
    if not files_html:
        files_html = '<div style="color:#9CA3AF;font-size:13px;">Вложений пока нет. Добавить вложения можно через Telegram-бота.</div>'
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Вложения задачи #{task_id}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F9FAFB; color: #111827; }}
.header {{ background: #1E293B; color: white; padding: 20px 32px; }}
.header h1 {{ font-size: 20px; font-weight: 700; }}
.header p {{ opacity: 0.7; font-size: 13px; margin-top: 4px; }}
.wrap {{ max-width: 600px; margin: 32px auto; }}
.card {{ background: white; border-radius: 12px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.file-item {{ padding: 12px 0; border-bottom: 1px solid #F3F4F6; font-size: 14px; }}
.file-item:last-child {{ border-bottom: none; }}
.btn-back {{ display: inline-block; margin-top: 16px; padding: 10px 24px; background: #F3F4F6; color: #374151; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 600; }}
.note {{ margin-top: 16px; padding: 12px; background: #FFF7ED; border-radius: 8px; font-size: 13px; color: #92400E; }}
</style>
</head>
<body>
<div class="header">
  <h1>📎 Вложения задачи #{task_id}</h1>
  <p>{task['title']}</p>
</div>
<div class="wrap">
  <div class="card">
    <strong>Файлы</strong>
    <div style="margin-top:12px;">{files_html}</div>
  </div>
  <div class="note">💡 Чтобы прикрепить файл — напишите боту в Telegram: /mytasks и выберите задачу #{task_id}</div>
  <a href="{back}" class="btn-back">← Назад</a>
</div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")



# ─── История изменений задачи ───────────────────────────────────────────────
@routes.get("/history/{task_id}")
async def task_history_page(request):
    task_id = int(request.match_info["task_id"])
    tasks = get_tasks()
    task = next((t for t in tasks if t["id"] == task_id), None)
    if not task:
        raise web.HTTPFound("/")
    back = request.rel_url.query.get("back", "/")
    history = get_task_history(task_id)

    field_labels = {"status": "Статус", "title": "Задача", "assignee": "Ответственный",
                    "department": "Отдел", "project": "Проект", "deadline": "Срок", "comment": "Комментарий"}
    status_colors = {"Выполнена": "#10B981", "Открыта": "#3B82F6", "В работе": "#F59E0B", "На согласовании": "#F97316", "Просрочена": "#EF4444", "Заблокирована": "#1F2937"}

    rows_html = ""
    for h in history:
        field = h.get("field", "")
        label = field_labels.get(field, field)
        old_v = h.get("old_value") or "—"
        new_v = h.get("new_value") or "—"
        color = status_colors.get(new_v, "#6B7280")
        time = h.get("changed_at", "")[:16]
        rows_html += f"""<tr>
            <td style="padding:12px;color:#6B7280;font-size:13px;white-space:nowrap;">{time}</td>
            <td style="padding:12px;font-weight:600;">{h.get("changed_by","—")}</td>
            <td style="padding:12px;color:#6B7280;">{label}</td>
            <td style="padding:12px;color:#9CA3AF;font-size:13px;">{old_v}</td>
            <td style="padding:12px;">
                <span style="background:{color}20;color:{color};padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;">{new_v}</span>
            </td>
        </tr>"""

    if not rows_html:
        rows_html = '<tr><td colspan="5" style="text-align:center;padding:40px;color:#9CA3AF;">История изменений пуста</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>История задачи #{task_id}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F9FAFB; color: #111827; }}
.header {{ background: #1E293B; color: white; padding: 20px 32px; }}
.header h1 {{ font-size: 20px; font-weight: 700; }}
.header p {{ opacity: 0.7; font-size: 13px; margin-top: 4px; }}
.wrap {{ padding: 32px; }}
table {{ width: 100%; background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); border-collapse: collapse; }}
thead th {{ padding: 12px; text-align: left; font-size: 12px; font-weight: 600; color: #6B7280; text-transform: uppercase; letter-spacing:.05em; border-bottom: 2px solid #E5E7EB; }}
tr {{ transition: transform .15s ease, box-shadow .15s ease; }}
tr:hover td {{ background: #EFF6FF; }}
tr:hover {{ transform: scaleY(1.02); box-shadow: 0 4px 12px rgba(0,0,0,0.08); position: relative; z-index: 1; }}
.btn-back {{ display:inline-block;margin-top:16px;padding:10px 24px;background:#F3F4F6;color:#374151;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600; }}
</style>
</head>
<body>
<div class="header">
  <h1>🕐 История изменений #{task_id}</h1>
  <p>{task['title']}</p>
</div>
<div class="wrap">
  <table>
    <thead><tr><th>Дата и время</th><th>Кто изменил</th><th>Поле</th><th>Было</th><th>Стало</th></tr></thead>
    <tbody>{rows_html}</tbody>
  </table>
  <a href="{back}" class="btn-back">← Назад</a>
</div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")



# ─── Календарь встреч ──────────────────────────────────────────────────────
@routes.get("/calendar")
async def calendar_page(request):
    from datetime import datetime, timedelta
    import calendar as cal

    now = datetime.now()
    year = int(request.rel_url.query.get("year", now.year))
    month = int(request.rel_url.query.get("month", now.month))
    selected_project = request.rel_url.query.get("project", "")

    month_str = f"{year}-{month:02d}"
    meetings = get_meetings(month=month_str, project=selected_project or None)
    projects = get_projects()

    # Группируем встречи по дате
    by_date = {}
    for m in meetings:
        by_date.setdefault(m["date"], []).append(m)

    # Предыдущий и следующий месяц
    first_day = datetime(year, month, 1)
    prev = first_day - timedelta(days=1)
    next_m = first_day + timedelta(days=32)
    prev_url = f"/calendar?year={prev.year}&month={prev.month}"
    next_url = f"/calendar?year={next_m.year}&month={next_m.month}"

    month_names = ["","Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
    month_name = month_names[month]

    # Строим сетку календаря
    cal.setfirstweekday(0)
    weeks = cal.monthcalendar(year, month)
    day_names = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]

    header_cells = "".join(f'<th style="padding:8px;text-align:center;font-size:12px;color:#6B7280;font-weight:600;">{d}</th>' for d in day_names)

    grid_rows = ""
    for week in weeks:
        row = ""
        for day in week:
            if day == 0:
                row += '<td style="padding:4px;background:#F9FAFB;border:1px solid #F3F4F6;"></td>'
            else:
                date_str = f"{year}-{month:02d}-{day:02d}"
                day_meetings = by_date.get(date_str, [])
                is_today = date_str == now.strftime("%Y-%m-%d")
                bg = "#EFF6FF" if is_today else "white"
                border = "2px solid #3B82F6" if is_today else "1px solid #F3F4F6"
                dots = ""
                for dm in day_meetings[:3]:
                    color = "#3B82F6"
                    dots += f'<div style="font-size:10px;background:{color}15;color:{color};border-radius:3px;padding:1px 4px;margin-top:2px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;cursor:pointer;" onclick="openMeeting({dm["id"]})">{dm["time_start"] or ""} {dm["title"][:20]}</div>'
                if len(day_meetings) > 3:
                    dots += f'<div style="font-size:10px;color:#9CA3AF;">+{len(day_meetings)-3} ещё</div>'
                row += f'''<td style="padding:6px;background:{bg};border:{border};vertical-align:top;min-height:80px;cursor:pointer;" onclick="showAddForm('{date_str}')">
                    <div style="font-weight:600;font-size:13px;color:{"#3B82F6" if is_today else "#374151"};">{day}</div>
                    {dots}
                </td>'''
        grid_rows += f"<tr>{row}</tr>"

    # Список встреч текущего месяца
    meetings_list = ""
    for m in meetings:
        proj_badge = f'<span style="background:#EFF6FF;color:#3B82F6;padding:2px 8px;border-radius:10px;font-size:11px;">{m["project"]}</span>' if m.get("project") else ""
        time_str = f'{m["time_start"]}' + (f' – {m["time_end"]}' if m.get("time_end") else "")
        meetings_list += f'''<div style="display:flex;gap:12px;align-items:flex-start;padding:12px;border-bottom:1px solid #F3F4F6;">
            <div style="min-width:50px;text-align:center;background:#EFF6FF;border-radius:8px;padding:6px;">
                <div style="font-size:18px;font-weight:700;color:#3B82F6;">{m["date"][8:]}</div>
                <div style="font-size:10px;color:#6B7280;">{month_names[int(m["date"][5:7])][:3]}</div>
            </div>
            <div style="flex:1;">
                <div style="font-weight:600;font-size:14px;">{m["title"]}</div>
                <div style="font-size:12px;color:#6B7280;margin-top:2px;">
                    {"🕐 " + time_str if time_str else ""} {"👥 " + m["participants"] if m.get("participants") else ""} {proj_badge}
                </div>
                {f'<div style="font-size:12px;color:#9CA3AF;margin-top:4px;">{m["description"]}</div>' if m.get("description") else ""}
            </div>
            <div style="display:flex;gap:6px;">
                <a href="/calendar/edit/{m["id"]}?back=/calendar?year={year}%26month={month}" style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:6px;background:#FFF;border:1px solid #E5E7EB;text-decoration:none;font-size:14px;">✏️</a>
                <a href="/calendar/delete/{m["id"]}?back=/calendar?year={year}%26month={month}" onclick="return confirm('Удалить встречу?')" style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:6px;background:#FFF;border:1px solid #E5E7EB;text-decoration:none;font-size:14px;">🗑</a>
            </div>
        </div>'''

    if not meetings_list:
        meetings_list = '<div style="text-align:center;padding:32px;color:#9CA3AF;">Встреч в этом месяце нет</div>'

    project_options = '<option value="">Все проекты</option>' + "".join(
        f'<option value="{p["name"]}" {"selected" if p["name"]==selected_project else ""}>{p["name"]}</option>'
        for p in projects
    )
    project_options_form = "".join(f'<option value="{p["name"]}">{p["name"]}</option>' for p in projects)
    participants_list = ",".join([
        "Абдуллах Н.","Камалов Н.","Кострыкин И.","Яманова Э.","Аскарова М.",
        "Кульбаева Б.","Мырзағали Е.","Елемес Е.","Оспанова А.","Луданная Л.",
        "Маркелова И.","Мустафина А.","Куниязов З."
    ])

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Календарь встреч</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:#F9FAFB; color:#111827; }}
.header {{ background:#1E293B; color:white; padding:16px 32px; display:flex; align-items:center; gap:24px; }}
.header h1 {{ font-size:18px; font-weight:700; }}
.wrap {{ display:grid; grid-template-columns:1fr 320px; gap:24px; padding:24px 32px; }}
.card {{ background:white; border-radius:12px; box-shadow:0 1px 3px rgba(0,0,0,.08); overflow:hidden; }}
table {{ width:100%; border-collapse:collapse; }}
.modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.4); z-index:100; align-items:center; justify-content:center; }}
.modal.open {{ display:flex; }}
.modal-box {{ background:white; border-radius:16px; padding:28px; width:480px; max-width:95vw; }}
.modal-box h2 {{ font-size:18px; font-weight:700; margin-bottom:20px; }}
label {{ display:block; font-size:13px; font-weight:600; color:#374151; margin-bottom:6px; margin-top:14px; }}
input,select,textarea {{ width:100%; padding:9px 12px; border:1px solid #E5E7EB; border-radius:8px; font-size:14px; font-family:inherit; }}
textarea {{ height:70px; resize:vertical; }}
.btns {{ display:flex; gap:10px; margin-top:20px; }}
.btn-primary {{ padding:10px 20px; background:#3B82F6; color:white; border:none; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; }}
.btn-cancel {{ padding:10px 20px; background:#F3F4F6; color:#374151; border:none; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer; }}
@media(max-width:900px) {{ .wrap {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="header">
  <a href="/" style="color:rgba(255,255,255,0.7);text-decoration:none;font-size:13px;">← Дашборд</a>
  <h1>📅 Календарь встреч</h1>
  <select onchange="location='?year={year}&month={month}&project='+this.value" style="background:rgba(255,255,255,0.1);color:white;border:1px solid rgba(255,255,255,0.3);border-radius:8px;padding:6px 10px;font-size:13px;margin-left:auto;">
    {project_options}
  </select>
</div>

<div class="wrap">
  <div>
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #F3F4F6;">
        <a href="{prev_url}" style="text-decoration:none;color:#374151;font-size:20px;padding:4px 10px;border-radius:6px;background:#F9FAFB;">‹</a>
        <span style="font-size:17px;font-weight:700;">{month_name} {year}</span>
        <a href="{next_url}" style="text-decoration:none;color:#374151;font-size:20px;padding:4px 10px;border-radius:6px;background:#F9FAFB;">›</a>
      </div>
      <table>
        <thead><tr>{header_cells}</tr></thead>
        <tbody>{grid_rows}</tbody>
      </table>
    </div>
    <div style="margin-top:8px;font-size:12px;color:#9CA3AF;text-align:center;">Нажмите на день чтобы добавить встречу</div>
  </div>

  <div>
    <div class="card" style="margin-bottom:16px;">
      <div style="padding:16px 20px;border-bottom:1px solid #F3F4F6;display:flex;align-items:center;justify-content:space-between;">
        <strong style="font-size:15px;">Встречи в {month_name}</strong>
        <button onclick="showAddForm('{now.strftime('%Y-%m-%d')}')" style="padding:7px 14px;background:#3B82F6;color:white;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">+ Добавить</button>
      </div>
      {meetings_list}
    </div>
  </div>
</div>

<!-- Модальное окно добавления встречи -->
<div class="modal" id="addModal">
  <div class="modal-box">
    <h2>📅 Новая встреча</h2>
    <form method="post" action="/calendar/add?back=/calendar?year={year}%26month={month}">
      <label>Название встречи *</label>
      <input type="text" name="title" id="meetingTitle" required placeholder="Например: Еженедельный борд">
      <label>Дата *</label>
      <input type="date" name="date" id="meetingDate" required>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
        <div><label>Начало</label><input type="time" name="time_start"></div>
        <div><label>Конец</label><input type="time" name="time_end"></div>
      </div>
      <label>Проект</label>
      <select name="project"><option value="">Без проекта</option>{project_options_form}</select>
      <label>Участники</label>
      <input type="text" name="participants" placeholder="Маркелова И., Луданная Л." list="managers-list">
      <datalist id="managers-list">{"".join(f'<option value="{p}">' for p in participants_list.split(","))}</datalist>
      <label>Описание / повестка</label>
      <textarea name="description" placeholder="Что обсуждаем..."></textarea>
      <div class="btns">
        <button type="submit" class="btn-primary">💾 Сохранить</button>
        <button type="button" class="btn-cancel" onclick="closeModal()">Отмена</button>
      </div>
    </form>
  </div>
</div>

<script>
function showAddForm(date) {{
  document.getElementById('meetingDate').value = date;
  document.getElementById('addModal').classList.add('open');
}}
function closeModal() {{
  document.getElementById('addModal').classList.remove('open');
}}
function openMeeting(id) {{
  event.stopPropagation();
  window.location = '/calendar/edit/' + id + '?back=/calendar?year={year}%26month={month}';
}}
document.getElementById('addModal').addEventListener('click', function(e) {{
  if(e.target === this) closeModal();
}});
</script>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


@routes.post("/calendar/add")
async def calendar_add(request):
    back = request.rel_url.query.get("back", "/calendar")
    data = await request.post()
    add_meeting(
        title=data.get("title","").strip(),
        project=data.get("project",""),
        date=data.get("date",""),
        time_start=data.get("time_start",""),
        time_end=data.get("time_end",""),
        participants=data.get("participants",""),
        description=data.get("description","")
    )
    raise web.HTTPFound(back)


@routes.get("/calendar/delete/{meeting_id}")
async def calendar_delete(request):
    meeting_id = int(request.match_info["meeting_id"])
    delete_meeting(meeting_id)
    back = request.rel_url.query.get("back", "/calendar")
    raise web.HTTPFound(back)


@routes.get("/calendar/edit/{meeting_id}")
async def calendar_edit_page(request):
    from database import get_conn
    meeting_id = int(request.match_info["meeting_id"])
    back = request.rel_url.query.get("back", "/calendar")
    projects = get_projects()
    with get_conn() as conn:
        m = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not m:
        raise web.HTTPFound("/calendar")
    m = dict(m)
    project_options = "".join(
        f'<option value="{p["name"]}" {"selected" if p["name"]==m.get("project") else ""}>{p["name"]}</option>'
        for p in projects
    )
    participants_list = "Абдуллах Н.,Камалов Н.,Кострыкин И.,Яманова Э.,Аскарова М.,Кульбаева Б.,Мырзағали Е.,Елемес Е.,Оспанова А.,Луданная Л.,Маркелова И.,Мустафина А.,Куниязов З."
    html = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>Редактировать встречу</title>
<style>* {{box-sizing:border-box;margin:0;padding:0;}} body {{font-family:-apple-system,sans-serif;background:#F9FAFB;color:#111827;}} .header {{background:#1E293B;color:white;padding:16px 32px;}} .wrap {{max-width:520px;margin:32px auto;background:white;border-radius:12px;padding:32px;box-shadow:0 1px 3px rgba(0,0,0,.08);}} label {{display:block;font-size:13px;font-weight:600;color:#374151;margin-bottom:6px;margin-top:14px;}} input,select,textarea {{width:100%;padding:9px 12px;border:1px solid #E5E7EB;border-radius:8px;font-size:14px;}} textarea {{height:70px;resize:vertical;}} .btns {{display:flex;gap:10px;margin-top:20px;}} .btn-primary {{padding:10px 20px;background:#3B82F6;color:white;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;}} .btn-cancel {{padding:10px 20px;background:#F3F4F6;color:#374151;border:none;border-radius:8px;font-size:14px;font-weight:600;text-decoration:none;display:inline-flex;align-items:center;}}</style>
</head>
<body>
<div class="header"><h1 style="font-size:18px;">✏️ Редактировать встречу</h1></div>
<div class="wrap">
  <form method="post" action="/calendar/edit/{meeting_id}?back={back}">
    <label>Название *</label>
    <input type="text" name="title" value="{m.get('title','')}" required>
    <label>Дата *</label>
    <input type="date" name="date" value="{m.get('date','')}">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
      <div><label>Начало</label><input type="time" name="time_start" value="{m.get('time_start','')}"></div>
      <div><label>Конец</label><input type="time" name="time_end" value="{m.get('time_end','')}"></div>
    </div>
    <label>Проект</label>
    <select name="project"><option value="">Без проекта</option>{project_options}</select>
    <label>Участники</label>
    <input type="text" name="participants" value="{m.get('participants','')}" list="managers-list">
    <datalist id="managers-list">{"".join(f'<option value="{p}">' for p in participants_list.split(","))}</datalist>
    <label>Описание / повестка</label>
    <textarea name="description">{m.get('description','')}</textarea>
    <div class="btns">
      <button type="submit" class="btn-primary">💾 Сохранить</button>
      <a href="{back}" class="btn-cancel">Отмена</a>
    </div>
  </form>
</div>
</body></html>"""
    return web.Response(text=html, content_type="text/html")


@routes.post("/calendar/edit/{meeting_id}")
async def calendar_edit_save(request):
    meeting_id = int(request.match_info["meeting_id"])
    back = request.rel_url.query.get("back", "/calendar")
    data = await request.post()
    update_meeting(
        meeting_id=meeting_id,
        title=data.get("title","").strip(),
        project=data.get("project",""),
        date=data.get("date",""),
        time_start=data.get("time_start",""),
        time_end=data.get("time_end",""),
        participants=data.get("participants",""),
        description=data.get("description","")
    )
    raise web.HTTPFound(back)



