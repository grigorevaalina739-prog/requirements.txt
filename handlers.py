def format_multiple_preview(tasks, project, deadline, assignee):
    lines = [f"📋 *{len(tasks)} задач:*\n"]
    for i, t in enumerate(tasks, 1):
        title = t.get('title', '—')
        if len(title) > 50:
            title = title[:50] + "..."
        lines.append(f"*{i}.* {title}")
    lines.append(f"\n📁 {project} | 📅 {deadline or '—'} | 👤 {assignee or '—'}")
    lines.append("\n_Изменить или сохранить?_")
    return "\n".join(lines)
