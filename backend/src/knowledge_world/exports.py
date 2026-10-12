"""Portable, explicitly scoped business data; credentials and sessions are never selected."""

import csv
import io
from .common import dumps, public, require


LEARNING_TABLES = {
    "subjects": "subjects",
    "chapters": "chapters",
    "points": "knowledge_points",
    "materials": "materials",
    "cards": "cards",
    "plans": "daily_plans",
    "tasks": "study_tasks",
    "activities": "activities",
    "claims": "learning_claims",
    "assessments": "assessments",
    "review_schedules": "review_schedules",
    "attempts": "card_attempts",
    "reports": "study_reports",
    "timers": "timer_sessions",
}
ALL_TABLES = {
    "fixed_tasks": "fixed_tasks",
    "fixed_task_completions": "fixed_task_completions",
    "habits": "habit_plans",
    "habit_occurrences": "habit_occurrences",
    "screen_records": "screen_records",
    "commitments": "commitments",
    "inventory": "inventory_items",
    "assets": "generated_assets",
    "stories": "story_series",
    "achievements": "achievement_grants",
    "world_events": "world_events",
    "threads": "agent_threads",
    "wallet": "wallets",
    "heroes": "heroes",
    "monsters": "monsters",
    "teams": "teams",
    "home_items": "home_items",
    "game_orders": "game_orders",
    "game_events": "game_events",
    "battles": "battles",
    "occupations": "occupations",
    "reward_catalog": "reward_catalog",
    "leisure_tickets": "leisure_tickets",
    "system_actions": "system_actions",
    "system_action_revisions": "system_action_revisions",
    "system_decisions": "system_decisions",
    "system_challenges": "system_challenges",
    "system_penalty_rules": "system_penalty_rules",
    "skill_settings": "skill_settings",
    "legacy_contract_facts": "legacy_contract_facts",
}


def collect(c, scope):
    data = {}
    if scope in {"learning", "all"}:
        for name, table in LEARNING_TABLES.items():
            data[name] = [
                public(r) for r in c.all(f"SELECT * FROM {table} WHERE owner_id=:o", {"o": c.owner})
            ]
        for name, table, parent, key in [
            ("material_chunks", "material_chunks", "materials", "material_id"),
            ("evidence", "evidence_items", "activities", "activity_id"),
        ]:
            data[name] = [
                public(r)
                for r in c.all(
                    f"SELECT child.* FROM {table} child JOIN {parent} p ON p.id=child.{key} WHERE p.owner_id=:o",
                    {"o": c.owner},
                )
            ]
    if scope in {"ledger", "all"}:
        data["ledger"] = [
            public(r)
            for r in c.all("SELECT * FROM ledger_entries WHERE owner_id=:o ORDER BY sequence", {"o": c.owner})
        ]
    if scope == "all":
        for name, table in ALL_TABLES.items():
            data[name] = [
                public(r) for r in c.all(f"SELECT * FROM {table} WHERE owner_id=:o", {"o": c.owner})
            ]
        for table, parent, key in [
            ("leisure_intervals", "leisure_tickets", "ticket_id"),
            ("habit_plan_revisions", "habit_plans", "plan_id"),
            ("habit_rest_days", "habit_plans", "plan_id"),
            ("wager_acceptance_boundaries", "commitments", "contract_id"),
        ]:
            data[table] = [public(r) for r in c.all(f"SELECT child.* FROM {table} child JOIN {parent} p ON p.id=child.{key} WHERE p.owner_id=:o", {"o": c.owner})]
        data["rule_versions"] = [public(r) for r in c.all("SELECT * FROM rule_versions ORDER BY created_at,id")]
        data["game_catalogs"] = [public(r) for r in c.all("SELECT * FROM game_catalogs ORDER BY created_at,version")]
        from .backup import redact
        data["legacy_orders"] = [redact(public(r)) for r in c.all("SELECT * FROM redemptions WHERE owner_id=:o", {"o": c.owner})]
        data["messages"] = [
            public(r)
            for r in c.all(
                "SELECT m.* FROM agent_messages m JOIN agent_threads t ON t.id=m.thread_id WHERE t.owner_id=:o ORDER BY m.thread_id,m.sequence",
                {"o": c.owner},
            )
        ]
        data["story_chapters"] = [
            public(r)
            for r in c.all(
                "SELECT ch.* FROM story_chapters ch JOIN story_series s ON s.id=ch.series_id WHERE s.owner_id=:o ORDER BY ch.series_id,ch.number",
                {"o": c.owner},
            )
        ]
    return data


def export_data(c, format, scope):
    require(
        format in {"json", "md", "csv"} and scope in {"learning", "ledger", "all"},
        "INVALID_INPUT",
        "导出范围无效",
        400,
    )
    data = collect(c, scope)
    if format == "json":
        return dumps({"format": "knowledge-world.export.2", "scope": scope, **data}), "application/json"
    if format == "md":
        sections = [f"# 知识世界 · {scope} 导出"]
        for name, records in data.items():
            sections.append(f"## {name}（{len(records)} 条）")
            for row in records:
                title = row.get("title") or row.get("name") or row.get("id") or row.get("card_id", "记录")
                body = row.get("content_md") or row.get("narrative_md") or row.get("body_md")
                sections.append(
                    f"### {title}\n\n"
                    + (body + "\n\n" if body else "")
                    + "````json\n"
                    + dumps(row)
                    + "\n````"
                )
        return "\n\n".join(sections), "text/markdown"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    columns = [
        "section",
        "id",
        "business_date",
        "title",
        "learning_delta",
        "available_delta",
        "held_delta",
        "source_key",
        "data_json",
    ]
    writer.writerow(columns)
    for name, records in data.items():
        for row in records:
            values = {**row, "section": name, "data_json": dumps(row)}
            # Keep spreadsheet programs from interpreting user-authored titles as formulas.
            writer.writerow(
                [
                    "'" + value
                    if isinstance(value := values.get(key, ""), str)
                    and value.startswith(("=", "+", "-", "@", "\t", "\r"))
                    else value
                    for key in columns
                ]
            )
    return "\ufeff" + stream.getvalue(), "text/csv"
