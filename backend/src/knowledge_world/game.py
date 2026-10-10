"""Authoritative roster, home and quoted purchases on the existing ledger."""
import json
from copy import deepcopy
from itsdangerous import BadSignature
from .common import uid, dumps, public, require, check_version, iso, DomainError
from .economy import append
from .game_events import emit, wallet_view
from .signing import signer


def stage(level, thresholds):
    return sum(level >= threshold for threshold in thresholds)


def hero_view(c, row=None, rules=None):
    row = row or c.one("SELECT * FROM heroes WHERE owner_id=:o", {"o": c.owner})
    rules = rules or c.rules()
    h, growth = rules["hero"], rules["hero"]["growth"]
    stats = deepcopy(h["base_stats"])
    stats["hp"] += row["strength"] * growth["hp_per_strength"]
    stats["physical_attack"] += row["strength"] * growth["attack_per_strength"]
    stats["magic_attack"] += row["mana"] * growth["magic_per_mana"]
    stats["mp"] += row["mana"] * growth["mp_per_mana"]
    stats["speed"] += row["agility"] * growth["speed_per_agility"]
    stats["dodge_bps"] = min(rules["battle"]["max_dodge_bps"], row["agility"] * growth["dodge_bps_per_agility"])
    level = h["initial_level"] + row["training_steps"]
    return {"id": row["id"], "code": "hero", "name": c.profile["display_name"], "role": "hero", "level": level,
        "visual_stage": stage(level, h["visual_stage_min_levels"]), "stats": stats, "skill": h["skill"],
        "attributes": {k: row[k] for k in ("strength", "agility", "mana")}, "training_steps": row["training_steps"],
        "version": row["version"], "next_cost": h["training_base_cost"] + row["training_steps"] * h["training_cost_increment_per_step"] if row["training_steps"] < h["max_training_steps"] else None,
        "next_stage_level": next((n for n in h["visual_stage_min_levels"] if n > level), None)}


def monster_view(c, row, rules=None):
    rules = rules or c.rules()
    m = rules["monsters"]
    species = next(s for s in m["species"] if s["code"] == row["species_code"])
    factor = 10000 + (row["level"] - 1) * m["stat_growth_bps_per_level"]
    stats = {k: v * factor // 10000 for k, v in species["stats"].items()}
    stats["dodge_bps"] = 0
    skill = deepcopy(species["skill"])
    if "amount" in skill:
        skill["amount"] = skill["amount"] * factor // 10000
    return {"id": row["id"], "code": species["code"], "name": species["name"], "role": species["role"],
        "level": row["level"], "visual_stage": stage(row["level"], m["visual_stage_min_levels"]),
        "stats": stats, "skill": skill, "version": row["version"],
        "next_cost": m["upgrade_base_cost"] + (row["level"] - 1) * m["upgrade_cost_increment_per_level"] if row["level"] < m["max_level"] else None,
        "next_stage_level": next((n for n in m["visual_stage_min_levels"] if n > row["level"]), None)}


def roster(c):
    rules = c.rules()
    team = c.get("teams", c.owner, key="owner_id")
    return {"hero": hero_view(c), "monsters": [monster_view(c, r) for r in c.all("SELECT * FROM monsters WHERE owner_id=:o ORDER BY created_at,id", {"o": c.owner})],
            "species": rules["monsters"]["species"], "team": {"member_ids": json.loads(team["member_ids_json"]), "version": team["version"]},
            "max_deployed": rules["monsters"]["max_deployed"], "rule_version": rules["version"]}


def save_team(c, data):
    row = c.get("teams", c.owner, key="owner_id")
    check_version(row, data.expected_version)
    hero = c.scalar("SELECT id FROM heroes WHERE owner_id=:o", {"o": c.owner})
    ids = data.member_ids
    require(len(ids) == len(set(ids)) and ids.count(hero) == 1, "INVALID_TEAM", "角色必须恰好出场一次，同一实例不能重复")
    require(len(ids) <= 1 + c.rules()["monsters"]["max_deployed"], "INVALID_TEAM", "队伍人数超过上限")
    for identity in ids:
        if identity != hero:
            c.get("monsters", identity)
    before = {"member_ids": json.loads(row["member_ids_json"]), "version": row["version"]}
    c.update("teams", c.owner, key="owner_id", member_ids_json=dumps(ids), version=row["version"] + 1, updated_at=c.now)
    after = {"member_ids": ids, "version": row["version"] + 1}
    emit(c, f"team:{after['version']}", "team_changed", "team", c.owner, before=before, after=after)
    c.change("roster")
    return after


def home(c):
    return {"items": [public(r) for r in c.all("SELECT * FROM home_items WHERE owner_id=:o ORDER BY created_at,id", {"o": c.owner})],
        "catalog": c.rules()["home"]["decoration_presets"], "roster": roster(c),
        "occupations": [r["outpost_id"] for r in c.all("SELECT outpost_id FROM occupations WHERE owner_id=:o", {"o": c.owner})],
        "display_epoch": c.scalar("SELECT epoch FROM world_history_state WHERE id=1"), "grid_min": -12, "grid_max": 12,
        "rule_version": c.rules()["version"]}


def place(c, identity, data):
    row = c.get("home_items", identity)
    check_version(row, data.expected_version)
    require((data.x is None) == (data.z is None), "INVALID_PLACEMENT", "位置需要完整坐标", 400)
    if data.x is not None:
        size = row["footprint"]
        require(-12 <= data.x <= 12 - size and -12 <= data.z <= 12 - size, "INVALID_PLACEMENT", "位置超出家园边界")
        for other in c.all("SELECT * FROM home_items WHERE owner_id=:o AND id!=:id AND x IS NOT NULL", {"o": c.owner, "id": identity}):
            overlap = data.x < other["x"] + other["footprint"] and other["x"] < data.x + size and data.z < other["z"] + other["footprint"] and other["z"] < data.z + size
            require(not overlap, "PLACEMENT_OCCUPIED", "此处与已有物件重叠")
    before = public(row)
    c.update("home_items", identity, x=data.x, z=data.z, rotation=data.rotation, version=row["version"] + 1, updated_at=c.now)
    after = public(c.get("home_items", identity))
    emit(c, f"placement:{identity}:{after['version']}", "home_placed", "home_item", identity, before=before, after=after)
    return after


def quote_state(c, data):
    rules = c.rules()
    op = data.operation
    if op == "hero_train":
        row = c.one("SELECT * FROM heroes WHERE owner_id=:o", {"o": c.owner})
        require(data.attribute in {"strength", "agility", "mana"}, "INVALID_INPUT", "请选择训练属性", 400)
        require(row["training_steps"] < rules["hero"]["max_training_steps"], "LEVEL_LIMIT", "角色训练已达上限")
        before = hero_view(c, row)
        row[data.attribute] += rules["hero"]["attribute_gain_per_training"]
        row["training_steps"] += 1
        row["version"] += 1
        return "角色训练", before["next_cost"], before, hero_view(c, row)
    if op == "monster_recruit":
        species = next((s for s in rules["monsters"]["species"] if s["code"] == data.target_id), None)
        require(species is not None, "RESOURCE_NOT_FOUND", "物种不存在", 404)
        return species["name"] + " · 招募", species["recruit_cost"], {}, {"species_code": data.target_id, "level": 1}
    if op == "monster_train":
        row = c.get("monsters", data.target_id)
        require(row["level"] < rules["monsters"]["max_level"], "LEVEL_LIMIT", "魔兽已达等级上限")
        before = monster_view(c, row)
        row["level"] += 1
        row["version"] += 1
        return before["name"] + " · 强化", before["next_cost"], before, monster_view(c, row)
    if op == "home_buy":
        item = next((s for s in rules["home"]["decoration_presets"] if s["code"] == data.target_id), None)
        require(item is not None, "RESOURCE_NOT_FOUND", "家园物件不存在", 404)
        return item["name"], item["price_points"], {}, {"code": item["code"], "name": item["name"], "level": 1}
    if op == "home_upgrade":
        row = c.get("home_items", data.target_id)
        h = rules["home"]
        require(row["kind"] == "building" and row["level"] < h["max_building_level"], "LEVEL_LIMIT", "此建筑无法继续升级")
        before = public(row)
        cost = h["upgrade_base_cost"] + (row["level"] - h["initial_building_level"]) * h["upgrade_cost_increment_per_level"]
        return "营地升级", cost, before, {**before, "level": row["level"] + 1, "version": row["version"] + 1}
    if op == "leisure":
        row = c.get("reward_catalog", data.target_id)
        require(row["enabled"], "ACTION_NOT_ALLOWED", "奖励已停用")
        return row["name"], row["price_points"], public(row), {"state": "reserved", "duration_seconds": row["duration_minutes"] * 60}
    raise DomainError("INVALID_INPUT", "不支持的报价操作", 400)


def quote(c, data):
    name, price, before, after = quote_state(c, data)
    terms = {"kind": "game_quote", "owner": c.owner, "nonce": uid(), "input": data.model_dump(),
        "name": name, "price": price, "before": before, "after": after, "rule_version": c.rules()["version"],
        "issued_at": c.now, "expires_at": c.now + 600000}
    return {"quote_token": signer(c.db.settings).dumps(terms), "quote_id": terms["nonce"], "operation": data.operation,
            "name": name, "price_points": price, "before": before, "after": after,
            "rule_version": terms["rule_version"], "expires_at": iso(terms["expires_at"])}


def order(c, token, allowed=None):
    from .game_models import GameQuote
    try:
        terms = signer(c.db.settings).loads(token)
    except BadSignature:
        raise DomainError("QUOTE_EXPIRED", "报价签名无效，请重新获取")
    require(terms.get("kind") == "game_quote" and terms.get("owner") == c.owner, "RESOURCE_NOT_FOUND", "报价不存在", 404)
    data = GameQuote.model_validate(terms["input"])
    require(allowed is None or data.operation in allowed, "INVALID_INPUT", "报价类型不符合此操作", 400)
    old = c.one("SELECT * FROM game_orders WHERE owner_id=:o AND quote_nonce=:n", {"o": c.owner, "n": terms["nonce"]})
    if old:
        return json.loads(old["receipt_json"])
    require(terms["issued_at"] <= c.now < terms["expires_at"], "QUOTE_EXPIRED", "报价已过期，请刷新")
    require(terms["rule_version"] == c.rules()["version"], "QUOTE_CHANGED", "规则已更新，请刷新报价")
    name, price, before, after = quote_state(c, data)
    require((name, price, before, after) == (terms["name"], terms["price"], terms["before"], terms["after"]), "QUOTE_CHANGED", "对象或价格已变化，请刷新报价")
    identity = uid()
    op = data.operation
    if op == "leisure":
        from .leisure import reserve
        result = reserve(c, identity, terms)
    else:
        entry = append(c, "purchase", "shop", f"game-order:{identity}", "game_order", identity,
            available=-price, economic_kind=op, detail={"operation": op, "reason": name, "price_points": price})
        entity_id = data.target_id
        if op == "hero_train":
            entity_id = after["id"]
            c.update("heroes", entity_id, **after["attributes"], training_steps=after["training_steps"], version=after["version"], updated_at=c.now)
        elif op == "monster_recruit":
            entity_id = uid()
            c.insert("monsters", id=entity_id, owner_id=c.owner, species_code=data.target_id, grant_key=f"order:{identity}", rule_version=terms["rule_version"], created_at=c.now, updated_at=c.now)
            after = monster_view(c, c.get("monsters", entity_id))
        elif op == "monster_train":
            c.update("monsters", entity_id, level=after["level"], version=after["version"], updated_at=c.now)
        elif op == "home_buy":
            entity_id = uid()
            c.insert("home_items", id=entity_id, owner_id=c.owner, code=data.target_id, name=name, kind="decoration", grant_key=f"order:{identity}", rule_version=terms["rule_version"], created_at=c.now, updated_at=c.now)
            after = public(c.get("home_items", entity_id))
        elif op == "home_upgrade":
            c.update("home_items", entity_id, level=after["level"], version=after["version"], updated_at=c.now)
            after = public(c.get("home_items", entity_id))
        event = emit(c, f"order:{identity}", op, "game_order", identity, object_id=entity_id,
            before=before, after=after, ledger_ids=[entry["id"]] if entry else [], detail={"reason": name, "price_points": price})
        result = {"command_id": identity, "operation": op, "entity_id": entity_id, "entity_version": after["version"],
            "price_points": price, "before": before, "after": after, "ledger_entry_ids": [entry["id"]] if entry else [],
            "game_event_ids": [event["id"]], "wallet": wallet_view(c), "rule_version": terms["rule_version"]}
    c.insert("game_orders", id=identity, owner_id=c.owner, quote_nonce=terms["nonce"], operation=op,
        target_id=result["entity_id"], price_points=price, rule_version=terms["rule_version"], receipt_json=dumps(result), created_at=c.now)
    c.change("roster", "home", "rewards", "leisure")
    return result


def world_map(c):
    version = c.rules()["version"]
    directory = json.loads(c.get("game_catalogs", version, key="version", owned=False)["payload_json"])
    occupied = {r["outpost_id"] for r in c.all("SELECT outpost_id FROM occupations WHERE owner_id=:o", {"o": c.owner})}
    for site in directory["outposts"]:
        site["status"] = "occupied" if site["id"] in occupied else "available" if set(site["prerequisites"]) <= occupied else "locked"
    return {"version": version, "regions": directory["regions"], "outposts": directory["outposts"], "team": roster(c)["team"]}


def outpost(c, identity):
    site = next((s for s in world_map(c)["outposts"] if s["id"] == identity), None)
    require(site is not None, "RESOURCE_NOT_FOUND", "据点不存在", 404)
    return site
