"""Idempotent activation and preservation of every accepted legacy obligation."""
import json
from .common import uid, dumps, require
from .config import ROOT
from .game_catalog import catalog

TARGET = "system-core-2026-10-13.1"
# Keys a later target adds to an already activated rule set. A database on an
# older (or user-published) version gets a NEW immutable version derived from
# its own active payload, so customised caps survive and old rows stay intact.
UPGRADES = {TARGET: ("scoring_mode", "tier_criteria", "tier_signals", "max_items_per_report", "calibration_days", "max_award_per_action_scope")}


def activate(c):
    current = c.one("SELECT * FROM rule_versions WHERE is_active=1")
    if not current or "system" not in json.loads(current["payload_json"]):
        target = json.loads((ROOT / "docs/contracts/system-core-rules.target.json").read_text(encoding="utf-8"))
        require(target["version"] == TARGET, "RULES_INCOMPATIBLE", "目标规则需要新的领域适配")
        imported = {**target, "status": "activated", "activation_schema": "0011"}
        c.execute("UPDATE rule_versions SET is_active=0 WHERE is_active=1")
        if c.scalar("SELECT 1 FROM rule_versions WHERE id=:v", {"v": TARGET}):
            c.execute("UPDATE rule_versions SET is_active=1 WHERE id=:v", {"v": TARGET})
        else:
            c.insert("rule_versions", id=TARGET, payload_json=dumps(imported), is_active=1, created_at=c.now)
    upgrade(c)
    rules = c.rules()
    ensure_catalog(c, rules)
    for profile in c.all("SELECT id FROM profiles"):
        c.owner = profile["id"]
        initialize_account(c)


def upgrade(c):
    current = c.rules()
    target = json.loads((ROOT / "docs/contracts/system-core-rules.target.json").read_text(encoding="utf-8"))
    keys = UPGRADES.get(target["version"], ())
    if not keys or all(key in current["system"] for key in keys):
        return
    derived = json.loads(dumps(current))
    derived["system"].update({key: target["system"][key] for key in keys})
    derived.update(version=target["version"], derived_from=current["version"])
    if c.scalar("SELECT 1 FROM rule_versions WHERE id=:v", {"v": derived["version"]}):
        derived["version"] = target["version"] + "." + uid()[:8]
    c.execute("UPDATE rule_versions SET is_active=0 WHERE is_active=1")
    c.insert("rule_versions", id=derived["version"], payload_json=dumps(derived), is_active=1, created_at=c.now)


def ensure_catalog(c, rules):
    if not c.scalar("SELECT 1 FROM game_catalogs WHERE version=:v", {"v": rules["version"]}):
        c.insert("game_catalogs", version=rules["version"], payload_json=dumps(catalog(rules)), created_at=c.now)


def initialize_account(c):
    if c.scalar("SELECT 1 FROM core_transitions WHERE owner_id=:o", {"o": c.owner}):
        return
    rules = c.rules()
    before = {"wallet": c.get("wallets", c.owner, key="owner_id"),
        "ledger_count": c.scalar("SELECT count(*) FROM ledger_entries WHERE owner_id=:o", {"o": c.owner}),
        "contracts": c.all("SELECT id,state,terms_json,rule_version,settlement_ledger_id FROM commitments WHERE owner_id=:o", {"o": c.owner})}
    hero_id = uid()
    c.insert("heroes", id=hero_id, owner_id=c.owner, **rules["hero"]["initial_attributes"], created_at=c.now, updated_at=c.now)
    monster_ids = []
    for index in range(rules["monsters"]["starter_quantity"]):
        identity = uid()
        c.insert("monsters", id=identity, owner_id=c.owner, species_code=rules["monsters"]["starter_code"],
            grant_key=f"starter:{index}", rule_version=rules["version"], created_at=c.now, updated_at=c.now)
        monster_ids.append(identity)
    c.insert("teams", owner_id=c.owner, member_ids_json=dumps([*monster_ids, hero_id]), updated_at=c.now)
    c.insert("home_items", id=uid(), owner_id=c.owner, code=rules["home"]["starter_building_code"],
        name="旅人营地", kind="building", level=rules["home"]["initial_building_level"], footprint=3, x=-2, z=-2,
        grant_key="starter:camp", rule_version=rules["version"], created_at=c.now, updated_at=c.now)
    for item in rules["leisure"]["presets"]:
        c.insert("reward_catalog", id=uid(), owner_id=c.owner, **item, description="留一段属于自己的时间。",
                 created_at=c.now, updated_at=c.now)
    for skill in ("wager", "shiyi"):
        c.insert("skill_settings", owner_id=c.owner, skill=skill, enabled=1)
    if not c.scalar("SELECT 1 FROM habit_plans WHERE owner_id=:o AND kind='checkin' AND archived_at IS NULL", {"o": c.owner}):
        from .routines import create_plan
        from .models import HabitCreate
        create_plan(c, HabitCreate(kind="checkin", title="早起，和世界打个招呼"))
    migrate_assets(c, rules)
    migrate_events(c, rules)
    retire_jobs(c)
    c.insert("core_transitions", owner_id=c.owner, rule_version=rules["version"], before_json=dumps(before), created_at=c.now)
    from .game_events import emit
    emit(c, "initial:core", "initial_grant", "initial_grant", hero_id,
        before={}, after={"hero_id": hero_id, "monster_ids": monster_ids, "building_code": rules["home"]["starter_building_code"]},
        detail={"reason": "系统初始赠予；未转换历史学习分，未发放额外积分"})


def migrate_assets(c, rules):
    def grant(code, name, kind, level, key, legacy, created_at):
        c.insert("home_items", id=uid(), owner_id=c.owner, code=code, name=name, kind=kind, level=level,
            grant_key=key, legacy_ref_json=dumps(legacy), rule_version=rules["version"], created_at=created_at, updated_at=c.now)
    for item in c.all("SELECT i.*,ca.name,ca.kind FROM inventory_items i JOIN catalog_items ca ON ca.code=i.catalog_code WHERE i.owner_id=:o AND i.state!='consumed'", {"o": c.owner}):
        mapped = {"decoration_basic": "lantern", "building_upgrade": "legacy_cottage", "seed_basic": "flower_bed"}.get(item["catalog_code"], item["catalog_code"])
        grant(mapped, item["name"], "legacy", 1, f"legacy:inventory:{item['id']}",
              {"table": "inventory_items", "id": item["id"], "state": item["state"], "placement": item["placement_json"]}, item["created_at"])
    for plot in c.all("SELECT p.*,kp.title,m.current_stage FROM world_plots p JOIN world_regions r ON r.id=p.region_id JOIN knowledge_points kp ON kp.id=p.point_id JOIN point_mastery m ON m.point_id=p.point_id WHERE r.owner_id=:o AND p.unlocked_at IS NOT NULL", {"o": c.owner}):
        grant("legacy_cottage", plot["title"] + " · 旧家园建筑", "legacy_building", max(1, min(3, plot["current_stage"] - 1)),
              f"legacy:plot:{plot['id']}", {"table": "world_plots", "id": plot["id"], "grid_x": plot["grid_x"], "grid_y": plot["grid_y"]}, plot["unlocked_at"])
    for pet in c.all("SELECT * FROM companions WHERE owner_id=:o", {"o": c.owner}):
        grant("legacy_companion", pet["name"], "companion", 1, f"legacy:companion:{pet['id']}", {"table": "companions", "id": pet["id"], "profile": json.loads(pet["profile_json"])}, pet["created_at"])
    for plant in c.all("SELECT * FROM plants WHERE owner_id=:o AND state!='harvested'", {"o": c.owner}):
        grant("flower_bed", "月光花 · 旧家园", "legacy", plant["growth_stage"] + 1,
              f"legacy:plant:{plant['id']}", {"table": "plants", "id": plant["id"]}, plant["created_at"])


def migrate_events(c, rules):
    # A single INSERT keeps a 50k-event migration bounded. Missing old presentation
    # stays NULL rather than being reconstructed from the current world.
    c.execute("""INSERT INTO game_events(id,owner_id,source_key,kind,object_id,origin_type,origin_id,
        before_json,after_json,receipt_json,rule_version,business_date,timezone_snapshot,created_at)
        SELECT e.id,e.owner_id,'legacy:world:'||e.id,'legacy_'||e.kind,e.point_id,'legacy_world',e.id,
        json_extract(e.payload_json,'$.presentation.before'), json_extract(e.payload_json,'$.presentation.after'),
        json_object('command_id',e.id,'ledger_entry_ids',json(CASE WHEN e.ledger_id IS NULL THEN '[]' ELSE json_array(e.ledger_id) END),
        'game_event_ids',json_array(e.id),'legacy',json('true'),'date_basis',CASE WHEN l.id IS NULL THEN 'utc_inferred' ELSE 'original_ledger' END,'original_payload',json(e.payload_json)),
        COALESCE(l.rule_version,:v),COALESCE(l.business_date,date(e.created_at/1000,'unixepoch')),CASE WHEN l.id IS NULL THEN 'UTC' ELSE 'legacy_unspecified' END,e.created_at
        FROM world_events e LEFT JOIN ledger_entries l ON l.id=e.ledger_id
        WHERE e.owner_id=:o ORDER BY e.rowid""",
        {"o": c.owner, "v": rules["version"]})
    # Historical timestamps remain exact. For non-ledger records the original
    # timezone was not stored; their imported business date is explicitly UTC.


def retire_jobs(c):
    from .legacy_contracts import job_is_eligible
    for job in c.all("SELECT * FROM jobs WHERE owner_id=:o AND state IN ('queued','retry_wait','running','needs_review')", {"o": c.owner}):
        if job["kind"] in {"agent_turn", "backup", "restore", "provider_test", "shiyi_check", "battle", "system_assess"}:
            continue
        if job["kind"] in {"assess", "grade"} and job_is_eligible(c, job):
            continue
        if job["kind"] == "generate":
            payload = json.loads(job["payload_json"])
            redemption = c.get("redemptions", payload["redemption_id"])
            if job["external_request_started_at"] is not None:
                c.update("jobs", job["id"], state="needs_review", lease_token=job["lease_token"] + 1,
                    last_error_json=dumps({"code": "LEGACY_EXTERNAL_RESULT_UNKNOWN", "message": "旧生成请求结果待核对，不自动重发"}))
                c.update("redemptions", redemption["id"], state="needs_review")
                continue
            from .rewards import cancel
            cancel(c, redemption["id"], redemption["version"])
        c.update("jobs", job["id"], state="cancelled", lease_token=job["lease_token"] + 1,
            last_error_json=dumps({"code": "PRODUCT_RETIRED", "message": "该独立学习/屏幕/创作流程已退出产品；历史保留"}))
