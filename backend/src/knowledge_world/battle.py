"""Deterministic automatic PvE. No network or database access in simulate()."""
import hashlib
import json
import secrets
from copy import deepcopy
from fractions import Fraction
from .common import uid, dumps, require, public
from . import game
from .economy import append
from .game_events import emit, wallet_view

ENGINE = "auto_pve.1/sha256_counter_v1"


def simulate(snapshot, seed):
    units = deepcopy(snapshot["allies"] + snapshot["enemies"])
    rules = snapshot["battle_rules"]
    states = {u["id"]: {"hp": u["stats"]["hp"], "mp": u["stats"]["mp"], "shield": 0} for u in units}
    actions = {u["id"]: 0 for u in units}
    events, counter = [], 0
    seed_bytes = bytes.fromhex(seed)

    def living(side):
        return sorted([u for u in units if u["side"] == side and states[u["id"]]["hp"] > 0], key=lambda u: (u["position"], u["id"]))

    outcome, reason, last_round = "lost", "round_limit", 0
    finished = False
    for round_number in range(1, rules["max_rounds"] + 1):
        last_round = round_number
        order = sorted(units, key=lambda u: (-u["stats"]["speed"], 0 if u["side"] == "ally" else 1, u["position"], u["id"]))
        for actor in order:
            actor_state = states[actor["id"]]
            if actor_state["hp"] <= 0:
                continue
            opponents = living("enemy" if actor["side"] == "ally" else "ally")
            if not opponents:
                finished = True
                break
            actions[actor["id"]] += 1
            target, effect, action, power = opponents[0], "physical_damage", "attack", 10000
            skill = actor.get("skill")
            use_skill = skill and actions[actor["id"]] % skill["every_nth_action"] == 0 and actor_state["mp"] >= skill["mp_cost"]
            if use_skill:
                if skill["effect"] == "heal":
                    target = min(living(actor["side"]), key=lambda u: (Fraction(states[u["id"]]["hp"], u["stats"]["hp"]), u["position"], u["id"]))
                    use_skill = states[target["id"]]["hp"] < target["stats"]["hp"]
                elif skill["effect"] == "shield":
                    target = living(actor["side"])[0]
                    use_skill = states[target["id"]]["shield"] < target["stats"]["hp"]
                if use_skill:
                    effect, action, power = skill["effect"], skill["code"], skill.get("power_bps", 10000)
                else:
                    target = opponents[0]
            target_state = states[target["id"]]
            actor_before, target_before = deepcopy(actor_state), deepcopy(target_state)
            damage = absorbed = healing = shield_gain = 0
            dodged = False
            damage_type = None
            if use_skill:
                actor_state["mp"] -= skill["mp_cost"]
            if effect == "heal":
                healing = min(skill["amount"], target["stats"]["hp"] - target_state["hp"])
                target_state["hp"] += healing
            elif effect == "shield":
                shield_gain = min(skill["amount"], target["stats"]["hp"] - target_state["shield"])
                target_state["shield"] += shield_gain
            else:
                damage_type = "magic" if effect == "magic_damage" else "physical"
                attack = actor["stats"]["magic_attack" if damage_type == "magic" else "physical_attack"]
                defense = target["stats"]["resistance" if damage_type == "magic" else "defense"]
                raw = max(rules["minimum_damage"], attack * power // 10000 - defense)
                roll = int.from_bytes(hashlib.sha256(seed_bytes + counter.to_bytes(8, "big")).digest()[:8], "big") % 10000
                counter += 1
                dodged = roll < min(rules["max_dodge_bps"], target["stats"].get("dodge_bps", 0))
                if not dodged:
                    absorbed = min(raw, target_state["shield"])
                    target_state["shield"] -= absorbed
                    damage = min(raw - absorbed, target_state["hp"])
                    target_state["hp"] -= damage
            events.append({"sequence": len(events) + 1, "round": round_number, "actor_id": actor["id"], "target_id": target["id"],
                "action": action, "effect": effect, "damage_type": damage_type, "damage": damage, "absorbed": absorbed,
                "healing": healing, "shield_gain": shield_gain, "dodged": dodged, "died": target_state["hp"] == 0,
                "actor_before": actor_before, "actor_after": deepcopy(actor_state), "target_before": target_before, "target_after": deepcopy(target_state)})
            if not living("enemy") or not living("ally"):
                finished = True
                break
        if finished:
            outcome = "won" if not living("enemy") else "lost"
            reason = "enemy_defeated" if outcome == "won" else "team_defeated"
            break
    return {"outcome": outcome, "reason": reason, "rounds": last_round, "events": events, "final_states": states}


def create(c, data):
    previous = c.one("SELECT * FROM battles WHERE owner_id=:o AND command_key=:k", {"o": c.owner, "k": data.command_key})
    if previous:
        snap = json.loads(previous["snapshot_json"])
        require(previous["outpost_id"] == data.outpost_id and snap["team_version"] == data.team_version, "IDEMPOTENCY_CONFLICT", "战斗标识对应了不同阵容或据点")
        return view(c, previous["id"])
    site = game.outpost(c, data.outpost_id)
    require(site["status"] != "locked", "OUTPOST_LOCKED", "请先占领前置据点")
    roster = game.roster(c)
    require(roster["team"]["version"] == data.team_version, "VERSION_CONFLICT", "队伍已变化，请重新确认")
    owned = {u["id"]: u for u in [roster["hero"], *roster["monsters"]]}
    allies = [{**owned[identity], "side": "ally", "position": i} for i, identity in enumerate(roster["team"]["member_ids"])]
    enemies = [{"id": f"enemy:{i}:{u['code']}", **u, "role": "enemy", "level": 1, "version": 1, "side": "enemy", "position": i} for i, u in enumerate(site["enemies"])]
    rules, identity = c.rules(), uid()
    snapshot = {"allies": allies, "enemies": enemies, "outpost": site, "battle_rules": rules["battle"], "team_version": data.team_version}
    append(c, "purchase", "shop", f"battle:{identity}:attempt", "battle", identity,
           available=-rules["battle"]["attempt_cost_points"], economic_kind="battle_attempt", detail={"reason": "出战费用"})
    c.insert("battles", id=identity, owner_id=c.owner, outpost_id=site["id"], rule_version=rules["version"],
        catalog_version=rules["version"], seed=secrets.token_hex(16), engine_version=ENGINE, snapshot_json=dumps(snapshot),
        state="queued", command_key=data.command_key, created_at=c.now)
    from .jobs import enqueue
    job = enqueue(c, "battle", f"battle:{identity}", {"battle_id": identity})
    c.update("battles", identity, job_id=job["id"])
    c.change("battles")
    return view(c, identity)


def view(c, identity):
    return public(c.get("battles", identity))


def resolve(db, job):
    from .jobs import ensure_lease, complete_job
    identity = json.loads(job["payload_json"])["battle_id"]
    with db.transaction(owner=job["owner_id"]) as c:
        ensure_lease(c, job)
        row = c.get("battles", identity)
        if row["state"] == "resolved":
            return {"battle_id": identity, "state": "resolved"}
    require(row["engine_version"] == ENGINE, "ENGINE_UNAVAILABLE", "此战斗需要原引擎版本恢复")
    snapshot = json.loads(row["snapshot_json"])
    result = simulate(snapshot, row["seed"])
    with db.transaction(True, job["owner_id"]) as c:
        ensure_lease(c, job)
        current = c.get("battles", identity)
        if current["state"] == "resolved":
            return {"battle_id": identity, "state": "resolved"}
        occupied = c.scalar("SELECT 1 FROM occupations WHERE owner_id=:o AND outpost_id=:id", {"o": c.owner, "id": row["outpost_id"]})
        first = result["outcome"] == "won" and not occupied
        ledger_ids, event_ids, reward_item = [], [], None
        site = snapshot["outpost"]
        if first:
            c.insert("occupations", owner_id=c.owner, outpost_id=site["id"], battle_id=identity, created_at=c.now)
            entry = append(c, "achievement", "achievement", f"first-clear:{site['id']}", "battle", identity,
                available=site["reward_points"], rule_version=row["rule_version"], economic_kind="first_clear",
                detail={"reason": site["name"] + " · 首胜", "outpost_id": site["id"]})
            ledger_ids = [entry["id"]] if entry else []
            if site["trophy_code"]:
                reward_item = uid()
                c.insert("home_items", id=reward_item, owner_id=c.owner, code=site["trophy_code"], name=site["name"] + " · 纪念地标",
                    kind="trophy", footprint=2, grant_key=f"first-clear:{site['id']}", rule_version=row["rule_version"], created_at=c.now, updated_at=c.now)
            event = emit(c, f"occupation:{site['id']}", "boss_occupied" if site["is_boss"] else "outpost_occupied", "battle", identity,
                object_id=site["id"], region_id=site["region_id"], before={"occupied": False},
                after={"occupied": True, "outpost_id": site["id"], "trophy_id": reward_item}, ledger_ids=ledger_ids,
                rule_version=row["rule_version"], detail={"reason": site["name"] + " · 永久占领", "reward_points": site["reward_points"], "outpost_snapshot": site})
            event_ids.append(event["id"])
        event = emit(c, f"battle:{identity}:result", "battle_won" if result["outcome"] == "won" else "battle_lost", "battle", identity,
            region_id=site["region_id"], before={"state": "queued"},
            after={"outcome": result["outcome"], "reason": result["reason"], "first_clear": first}, ledger_ids=ledger_ids,
            rule_version=row["rule_version"], detail={"reason": site["name"], "replay_path": f"/world/battles/{identity}"})
        event_ids.append(event["id"])
        result.update(first_clear=first, reward_points=site["reward_points"] if first else 0, reward_item_id=reward_item,
            occupation_changed=first, ledger_entry_ids=ledger_ids, game_event_ids=event_ids, command_id=identity, wallet=wallet_view(c))
        c.update("battles", identity, state="resolved", result_json=dumps(result), completed_at=c.now)
        c.notify(f"battle:{identity}", "远征战报已送达", site["name"] + (" · 胜利" if result["outcome"] == "won" else " · 重整旗鼓"), f"/world/battles/{identity}")
        complete_job(c, job, {"battle_id": identity, "state": "resolved"})
        c.change("battles", "world_map", "home")
    return {"battle_id": identity, "state": "resolved"}
