"""The current product's authenticated routes, mounted on TransactionRoute."""
import json
from . import game_models as g, models as m
from . import game, battle, system, leisure, routines, commitments, legacy_contracts
from .common import public, require, check_version, DomainError
from .game_events import wallet_view, history


def register(router, C, response, paginate):
    from . import fixed_tasks

    @router.get('/system/fixed-tasks', response_model=m.Envelope[list[g.FixedTask]])
    def fixed_task_list(c=C):
        return response(c, fixed_tasks.catalog(c))

    @router.post('/system/fixed-tasks', response_model=m.Envelope[g.FixedTask])
    def fixed_task_create(data: g.FixedTaskEdit, c=C):
        return response(c, fixed_tasks.save(c, data), 201)

    @router.patch('/system/fixed-tasks/{identity}', response_model=m.Envelope[g.FixedTask])
    def fixed_task_edit(identity: str, data: g.FixedTaskEdit, c=C):
        return response(c, fixed_tasks.save(c, data, identity))

    @router.delete('/system/fixed-tasks/{identity}', response_model=m.Envelope[g.FixedTask])
    def fixed_task_delete(identity: str, data: m.Expected, c=C):
        return response(c, fixed_tasks.disable(c, identity, data.expected_version))

    @router.post('/system/fixed-tasks/{identity}/complete', response_model=m.Envelope[g.FixedTaskReceipt])
    def fixed_task_complete(identity: str, data: g.FixedTaskComplete, c=C):
        return response(c, fixed_tasks.complete(c, identity, data.completion_id))

    @router.get("/wallet", response_model=m.Envelope[g.PointsWallet])
    def wallet(c=C):
        return response(c, wallet_view(c))

    @router.get("/ledger", response_model=m.Envelope[m.Page[g.LedgerEntry]])
    def ledger(limit: int = 30, cursor: str | None = None, start_date: str | None = None, end_date: str | None = None, c=C):
        from .common import valid_date
        where, params = "1=1", {}
        if start_date:
            valid_date(start_date)
            where += " AND business_date>=:start"
            params["start"] = start_date
        if end_date:
            valid_date(end_date)
            where += " AND business_date<=:end"
            params["end"] = end_date
        return response(c, paginate(c, "ledger_entries", where, params, limit, cursor, order="sequence DESC"))

    @router.get("/ledger/{identity}", response_model=m.Envelope[g.LedgerEntry])
    def ledger_entry(identity: str, c=C):
        return response(c, public(c.get("ledger_entries", identity)))

    @router.get("/ledger/{identity}/source", response_model=m.Envelope[g.LedgerSource])
    def ledger_source(identity: str, c=C):
        row = c.get("ledger_entries", identity)
        table = {"activity": "activities", "system_action": "system_actions", "habit_occurrence": "habit_occurrences",
            "commitment": "commitments", "game_order": "game_orders", "leisure": "leisure_tickets", "battle": "battles",
            "redemption": "redemptions", "achievement": "achievement_grants", "fixed_task": "fixed_tasks"}.get(row["origin_type"])
        source = c.one(f"SELECT * FROM {table} WHERE id=:id", {"id": row["origin_id"]}) if table else None
        require(source is None or source.get("owner_id", c.owner) == c.owner, "RESOURCE_NOT_FOUND", "来源不存在", 404)
        if source and table == "redemptions":
            source = {k: v for k, v in source.items() if k != "provider_snapshot_json"}
        return response(c, {"ledger": public(row), "source": public(source), "read_only": True})

    @router.get("/roster", response_model=m.Envelope[g.Roster])
    def roster(c=C):
        return response(c, game.roster(c))

    @router.put("/roster/team", response_model=m.Envelope[g.Team])
    def team(data: g.TeamChange, c=C):
        return response(c, game.save_team(c, data))

    @router.post("/roster/quotes", response_model=m.Envelope[g.QuoteResult])
    def roster_quote(data: g.GameQuote, c=C):
        require(data.operation in {"hero_train", "monster_recruit", "monster_train"}, "INVALID_INPUT", "请选择培养操作", 400)
        return response(c, game.quote(c, data))

    @router.post("/roster/orders", response_model=m.Envelope[g.CommandReceipt])
    def roster_order(data: g.Purchase, c=C):
        return response(c, game.order(c, data.quote_token, {"hero_train", "monster_recruit", "monster_train"}))

    @router.get("/world/home", response_model=m.Envelope[g.Home])
    def home(c=C):
        return response(c, game.home(c))

    @router.post("/world/home/quotes", response_model=m.Envelope[g.QuoteResult])
    def home_quote(data: g.GameQuote, c=C):
        require(data.operation in {"home_buy", "home_upgrade"}, "INVALID_INPUT", "请选择家园操作", 400)
        return response(c, game.quote(c, data))

    @router.post("/world/home/orders", response_model=m.Envelope[g.CommandReceipt])
    def home_order(data: g.Purchase, c=C):
        return response(c, game.order(c, data.quote_token, {"home_buy", "home_upgrade"}))

    @router.put("/world/home/placements/{identity}", response_model=m.Envelope[g.HomeItem])
    def home_place(identity: str, data: g.Placement, c=C):
        return response(c, game.place(c, identity, data))

    @router.get("/world/map", response_model=m.Envelope[g.WorldMap])
    def world_map(c=C):
        return response(c, game.world_map(c))

    @router.get("/world/outposts/{identity}", response_model=m.Envelope[g.Outpost])
    def outpost(identity: str, c=C):
        return response(c, game.outpost(c, identity))

    @router.post("/world/battles", response_model=m.Envelope[g.Battle])
    def battle_create(data: g.BattleCreate, c=C):
        return response(c, battle.create(c, data), 202)

    @router.get("/world/battles/{identity}", response_model=m.Envelope[g.Battle])
    def battle_get(identity: str, c=C):
        return response(c, battle.view(c, identity))

    @router.get("/world/history", response_model=m.Envelope[g.HistoryPage])
    def game_history(start_date: str | None = None, end_date: str | None = None, kind: str | None = None, cursor: str | None = None, limit: int = 30, c=C):
        return response(c, history(c, start_date=start_date, end_date=end_date, kind=kind, cursor=cursor, limit=limit))

    @router.get("/world/events", response_model=m.Envelope[g.EventFeed])
    def events(after_sequence: int | None = None, c=C):
        upper = c.scalar("SELECT COALESCE(max(sequence),0) FROM game_events WHERE owner_id=:o", {"o": c.owner})
        require(after_sequence is None or after_sequence >= 0, "INVALID_INPUT", "事件序号无效", 400)
        rows = c.all("SELECT * FROM game_events WHERE owner_id=:o AND sequence>:seq ORDER BY sequence LIMIT 101", {"o": c.owner, "seq": after_sequence if after_sequence is not None else max(0, upper - 20)})
        return response(c, {"items": [public(r) for r in rows[:100]], "last_sequence": rows[min(99, len(rows)-1)]["sequence"] if rows else upper,
            "has_more": len(rows) > 100, "display_epoch": c.scalar("SELECT epoch FROM world_history_state WHERE id=1")})

    @router.get("/rewards", response_model=m.Envelope[list[g.Reward]])
    def reward_catalog(c=C):
        return response(c, leisure.catalog(c))

    @router.post("/rewards", response_model=m.Envelope[g.Reward])
    def reward_create(data: g.RewardEdit, c=C):
        return response(c, leisure.edit_reward(c, data), 201)

    @router.patch("/rewards/{identity}", response_model=m.Envelope[g.Reward])
    def reward_edit(identity: str, data: g.RewardEdit, c=C):
        return response(c, leisure.edit_reward(c, data, identity))

    @router.delete("/rewards/{identity}", response_model=m.Envelope[g.Reward])
    def reward_delete(identity: str, data: m.Expected | None = None, c=C):
        return response(c, leisure.disable_reward(c, identity, data.expected_version if data else None))

    @router.post("/rewards/quotes", response_model=m.Envelope[g.QuoteResult])
    def reward_quote(data: g.GameQuote, c=C):
        require(data.operation == "leisure", "INVALID_INPUT", "请选择休闲奖励", 400)
        return response(c, game.quote(c, data))

    @router.post("/rewards/orders", response_model=m.Envelope[g.CommandReceipt])
    def reward_order(data: g.Purchase, c=C):
        return response(c, game.order(c, data.quote_token, {"leisure"}))

    @router.get("/leisure", response_model=m.Envelope[list[g.LeisureTicket]])
    def leisure_list(c=C):
        return response(c, [leisure.view(c, r["id"]) for r in c.all("SELECT id FROM leisure_tickets WHERE owner_id=:o ORDER BY created_at DESC,id", {"o": c.owner})])

    @router.get("/leisure/{identity}", response_model=m.Envelope[g.LeisureTicket])
    def leisure_get(identity: str, c=C):
        return response(c, leisure.view(c, identity))

    @router.post("/leisure/{identity}/{action}", response_model=m.Envelope[g.LeisureTicket])
    def leisure_action(identity: str, action: str, data: m.Expected, c=C):
        return response(c, leisure.transition(c, identity, action, data.expected_version))

    @router.get("/system/context", response_model=m.Envelope[g.SystemContext])
    def system_context(c=C):
        return response(c, system.context(c))

    @router.post("/system/actions", response_model=m.Envelope[g.Action])
    def action_create(data: g.ActionCreate, c=C):
        return response(c, system.create_action(c, f"manual:{data.client_action_id}", data.content), 202)

    @router.get("/system/actions/{identity}", response_model=m.Envelope[g.Action])
    def action_get(identity: str, c=C):
        return response(c, system.action_view(c, identity))

    @router.post("/system/actions/{identity}/revisions", response_model=m.Envelope[g.Action])
    def action_revise(identity: str, data: g.ActionRevision, c=C):
        return response(c, system.revise_action(c, identity, data), 202)

    @router.post("/system/actions/{identity}/resume", response_model=m.Envelope[g.Action])
    def action_resume(identity: str, c=C):
        system.queue_assessment(c, identity)
        return response(c, system.action_view(c, identity), 202)

    @router.post("/system/decisions/{identity}/apply", response_model=m.Envelope[g.Decision])
    def decision_apply(identity: str, c=C):
        return response(c, system.apply_decision(c, identity))

    @router.post("/system/adjustments", response_model=m.Envelope[g.AdjustmentReceipt])
    def adjustment(data: g.Adjustment, c=C):
        return response(c, system.adjust(c, data))

    @router.post("/system/challenges", response_model=m.Envelope[g.Challenge])
    def challenge_propose(data: g.ChallengeProposal, c=C):
        return response(c, system.propose_challenge(c, data))

    @router.post("/system/challenges/{identity}/accept", response_model=m.Envelope[g.Challenge])
    def challenge_accept(identity: str, data: m.AcceptTerms, c=C):
        return response(c, system.accept_challenge(c, identity, data))

    @router.post("/system/challenges/{identity}/resolve", response_model=m.Envelope[g.Challenge])
    def challenge_resolve(identity: str, data: g.ChallengeResolve, c=C):
        return response(c, system.resolve_challenge(c, identity, data))

    @router.get("/system/checkin", response_model=m.Envelope[g.Checkin])
    def checkin_status(c=C):
        return response(c, routines.checkin_status(c))

    @router.post("/system/checkin", response_model=m.Envelope[g.Checkin])
    def checkin(c=C):
        return response(c, routines.checkin(c))

    @router.get("/system/checkin/settings")
    def checkin_settings(c=C):
        occurrence = routines.special_occurrence(c, "checkin", c.today)
        return response(c, routines.plan_view(c, occurrence["plan_id"]))

    @router.patch("/system/checkin/settings")
    def checkin_edit(data: g.CheckinSettings, c=C):
        require(set(data.weekdays) <= set(range(7)), "INVALID_INPUT", "星期参数无效", 400)
        occurrence = routines.special_occurrence(c, "checkin", c.today)
        row = c.get("habit_plans", occurrence["plan_id"])
        last = c.one("SELECT * FROM habit_plan_revisions WHERE plan_id=:id ORDER BY revision DESC LIMIT 1", {"id": row["id"]})
        terms = json.loads(last["terms_json"])
        terms["penalty_enabled"] = data.penalty_enabled
        return response(c, routines.revise(c, row["id"], m.HabitRevision(expected_version=data.expected_version, weekdays=data.weekdays, terms=m.HabitTerms.model_validate({k: v for k, v in terms.items() if k in m.HabitTerms.model_fields}))))

    @router.put("/system/checkin/rest-days/{day}")
    def checkin_rest(day: str, c=C):
        occurrence = routines.special_occurrence(c, "checkin", c.today)
        return response(c, routines.rest_day(c, occurrence["plan_id"], day))

    @router.delete("/system/checkin/rest-days/{day}")
    def checkin_unrest(day: str, c=C):
        occurrence = routines.special_occurrence(c, "checkin", c.today)
        return response(c, routines.rest_day(c, occurrence["plan_id"], day, remove=True))

    @router.get("/system/wagers", response_model=m.Envelope[m.Page[g.Wager]])
    def wager_list(limit: int = 30, cursor: str | None = None, c=C):
        return response(c, paginate(c, "commitments", limit=limit, cursor=cursor, transform=lambda row: commitments.detail(c, row["id"])))

    @router.post("/system/wagers", response_model=m.Envelope[g.Wager])
    def wager_propose(data: g.WagerProposal, c=C):
        return response(c, commitments.proposal(c, data), 201)

    @router.get("/system/wagers/{identity}", response_model=m.Envelope[g.Wager])
    def wager_get(identity: str, c=C):
        return response(c, commitments.detail(c, identity))

    @router.post("/system/wagers/{identity}/accept", response_model=m.Envelope[g.Wager])
    def wager_accept(identity: str, data: m.AcceptTerms, c=C):
        return response(c, commitments.accept(c, identity, data))

    @router.post("/system/wagers/{identity}/settle", response_model=m.Envelope[g.Wager])
    def wager_settle(identity: str, c=C):
        return response(c, commitments.evaluate(c, identity))

    @router.post("/system/wagers/{identity}/abandon", response_model=m.Envelope[g.Wager])
    def wager_abandon(identity: str, data: m.AcceptTerms, c=C):
        row = c.get("commitments", identity)
        require(commitments.detail(c, identity)["terms_hash"] == data.terms_hash, "TERMS_CHANGED", "请核对合约条款")
        if row["state"] in {"active", "pending_settlement"}:
            check_version(row, data.expected_version)
        return response(c, commitments.evaluate(c, identity, abandon=True))

    @router.post("/system/wagers/{identity}/facts", response_model=m.Envelope[g.LegacyFactView])
    def legacy_submit(identity: str, data: g.LegacyFact, c=C):
        return response(c, legacy_contracts.submit_fact(c, identity, data), 202)

    @router.get("/system/wagers/{identity}/facts", response_model=m.Envelope[list[g.LegacyFactView]])
    def legacy_facts(identity: str, c=C):
        row = c.get("commitments", identity)
        if row["accepted_at"] is None:
            return response(c, [])
        ids = c.all("SELECT a.id FROM activities a JOIN learning_claims cl ON cl.id=a.claim_id WHERE a.owner_id=:o AND cl.first_submitted_at>=:start AND cl.first_submitted_at<:end ORDER BY a.created_at", {"o": c.owner, "start": row["accepted_at"], "end": row["deadline_at"]})
        return response(c, [legacy_contracts.activity_detail(c, r["id"]) for r in ids])

    @router.post("/system/legacy-facts/{identity}/resume", response_model=m.Envelope[g.LegacyFactView])
    def legacy_resume(identity: str, c=C):
        legacy_contracts.resume_fact(c, identity)
        return response(c, legacy_contracts.activity_detail(c, identity), 202)

    @router.post("/system/legacy-facts/{identity}/revisions", response_model=m.Envelope[g.LegacyFactView])
    def legacy_amend(identity: str, data: g.ActionRevision, c=C):
        return response(c, legacy_contracts.amend_fact(c, identity, data), 202)

    @router.get("/system/penalty-rules", response_model=m.Envelope[list[g.PenaltyRule]])
    def penalty_rules(c=C):
        return response(c, [public(r) for r in c.all("SELECT * FROM system_penalty_rules WHERE owner_id=:o ORDER BY created_at", {"o": c.owner})])

    @router.post("/system/penalty-rules", response_model=m.Envelope[g.PenaltyRule])
    def penalty_enable(data: g.PenaltyRuleCreate, c=C):
        return response(c, system.penalty_rule(c, data))

    @router.delete("/system/penalty-rules/{identity}", response_model=m.Envelope[g.PenaltyRule])
    def penalty_disable(identity: str, c=C):
        c.get("system_penalty_rules", identity)
        c.update("system_penalty_rules", identity, disabled_at=c.now)
        return response(c, public(c.get("system_penalty_rules", identity)))

    @router.get("/settings/skills", response_model=m.Envelope[g.SkillDirectory])
    def skill_settings(c=C):
        from .agent import skill_directory
        return response(c, skill_directory(c))

    @router.patch("/settings/skills")
    def skill_change(data: g.SkillSetting, c=C):
        row = c.one("SELECT * FROM skill_settings WHERE owner_id=:o AND skill=:s", {"o": c.owner, "s": data.skill})
        check_version(row, data.expected_version)
        c.execute("UPDATE skill_settings SET enabled=:e,version=version+1 WHERE owner_id=:o AND skill=:s", {"e": int(data.enabled), "o": c.owner, "s": data.skill})
        c.change("system", "settings")
        return response(c, {"skill": data.skill, "enabled": data.enabled, "version": row["version"] + 1, "accepted_contracts_continue": True})

    @router.get("/maintenance/legacy-orders", response_model=m.Envelope[m.Page[g.LegacyOrder]])
    def legacy_orders(limit: int = 20, cursor: str | None = None, c=C):
        from .rewards import legacy_order_view
        return response(c, paginate(c, "redemptions", limit=limit, cursor=cursor, transform=lambda row: legacy_order_view(c, row["id"])))

    @router.post("/maintenance/legacy-orders/{identity}/close", response_model=m.Envelope[g.LegacyOrder])
    def legacy_order_close(identity: str, data: g.LegacyOrderClose, c=C):
        from .rewards import close_legacy_order
        return response(c, close_legacy_order(c, identity, data))

    @router.api_route("/{retired_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def retired(retired_path: str, c=C):
        removed = {"subjects", "chapters", "points", "cards", "materials", "plans", "tasks", "activities", "attempts", "reviews", "review", "timers", "monitor", "archive", "reports", "screen-time", "habits", "stories", "redemption-quotes", "redemptions", "world", "catalog", "companion"}
        if retired_path.split("/")[0] in removed:
            raise DomainError("PRODUCT_RETIRED", "此旧产品入口已退出。签到和对赌请前往系统；历史仍可从账本来源或导出查看。", 410)
        raise DomainError("RESOURCE_NOT_FOUND", "接口不存在", 404)
