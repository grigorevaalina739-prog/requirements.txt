def import_from_sheet(spreadsheet_id: str, project_name: str, sheet_index: int = 0) -> dict:
    """Импортирует задачи из всех листов, каждый лист = отдельный проект."""
    try:
        client = get_sheets_client()
        ss = client.open_by_key(spreadsheet_id)
        
        total_imported = 0
        total_skipped = 0

        for ws in ss.worksheets():
            all_rows = ws.get_all_values()

            if not all_rows:
                continue

            headers = all_rows[0]
            mapping = detect_columns(headers)

            if "title" not in mapping:
                continue  # пропускаем листы без колонки с задачами

            # Название листа = название проекта
            sheet_project = ws.title
            add_project(sheet_project)

            with get_conn() as conn:
                existing = set(
                    row[0] for row in conn.execute(
                        "SELECT source_id FROM tasks WHERE source_sheet=?", (spreadsheet_id,)
                    ).fetchall()
                )

            for row_idx, row in enumerate(all_rows[1:], start=2):
                if not any(row):
                    continue

                title = row[mapping["title"]].strip() if mapping.get("title") is not None and mapping["title"] < len(row) else ""
                if not title:
                    continue

                source_id = f"{spreadsheet_id}_{ws.title}_{row_idx}"
                if source_id in existing:
                    total_skipped += 1
                    continue

                deadline = parse_date(row[mapping["deadline"]]) if mapping.get("deadline") is not None and mapping["deadline"] < len(row) else ""
                assignee = row[mapping["assignee"]].strip() if mapping.get("assignee") is not None and mapping["assignee"] < len(row) else ""
                department = row[mapping["department"]].strip() if mapping.get("department") is not None and mapping["department"] < len(row) else ""
                comment = row[mapping["comment"]].strip() if mapping.get("comment") is not None and mapping["comment"] < len(row) else ""
                status_raw = row[mapping["status"]].strip() if mapping.get("status") is not None and mapping["status"] < len(row) else ""

                status = "Открыта"
                if any(x in status_raw.lower() for x in ["выполн", "готов", "done", "complete", "закрыт"]):
                    status = "Выполнена"
                elif any(x in status_raw.lower() for x in ["работ", "process", "прогресс", "in progress"]):
                    status = "В работе"

                with get_conn() as conn:
                    conn.execute(
                        """INSERT INTO tasks 
                        (project, assignee, department, title, deadline, status, comment, source_sheet, source_id)
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                        (sheet_project, assignee, department, title, deadline, status, comment, spreadsheet_id, source_id)
                    )
                total_imported += 1

        return {"success": True, "imported": total_imported, "skipped": total_skipped}

    except Exception as e:
        logger.error(f"Ошибка импорта: {e}")
        return {"success": False, "error": str(e), "imported": 0}
