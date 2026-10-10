"""Original PvE content, persisted with its rules version before it is used."""
from copy import deepcopy


def enemy(code, name, hp, attack, defense, speed, *, magic=0, resistance=4, mp=30, skill=None):
    return {"code": code, "name": name, "stats": {"hp": hp, "physical_attack": attack,
        "magic_attack": magic, "defense": defense, "resistance": resistance, "speed": speed, "mp": mp,
        "dodge_bps": 0}, "skill": skill, "visual_stage": 1}


def catalog(rules):
    magic = {"code": "ember_bolt", "effect": "magic_damage", "mp_cost": 8, "every_nth_action": 3}
    shield = {"code": "stone_guard", "effect": "shield", "amount": 35, "mp_cost": 6, "every_nth_action": 3}
    heal = {"code": "starlight_heal", "effect": "heal", "amount": 40, "mp_cost": 8, "every_nth_action": 3}
    regions = [
        {"id": "mist_forest", "name": "雾隐森林", "description": "沿着萤火与旧木桥，找回森林深处的暖灯。", "theme": "mist_forest",
         "sites": [
             ("fern_gate", "蕨叶隘口", "林雾中的第一座瞭望台", [enemy("bramble", "荆棘守卫", 85, 16, 3, 6)]),
             ("old_bridge", "旧桥营地", "守住河流交汇处的通路", [enemy("boar", "岩背野猪", 150, 26, 8, 8), enemy("wisp", "迷雾灵", 90, 15, 3, 11, magic=23, skill=magic)]),
             ("ancient_stag", "古树王庭", "森林首领 · 枝角守望者", [enemy("forest_boss", "枝角守望者", 390, 37, 10, 10, magic=37, mp=60, skill=magic), enemy("bramble", "荆棘守卫", 105, 20, 5, 7)]),
         ]},
        {"id": "frost_ridge", "name": "霜脊山岭", "description": "山风卷过冰湖，石阶通向一座仍在发光的钟塔。", "theme": "frost_ridge",
         "sites": [
             ("snow_pass", "雪松哨站", "两名守卫扼守的山口", [enemy("ice_guard", "霜甲卫士", 260, 34, 13, 9, skill=shield), enemy("ice_wolf", "冰原猎狼", 180, 36, 8, 17)]),
             ("frozen_lake", "冻湖渡口", "先突破前排，再接近治疗者", [enemy("ice_guard", "霜甲卫士", 300, 40, 16, 10, skill=shield), enemy("snow_oracle", "雪灯祭司", 170, 18, 7, 14, magic=40, mp=64, skill=heal), enemy("ice_wolf", "冰原猎狼", 180, 35, 8, 16)]),
             ("frost_crown", "霜冠钟塔", "山岭首领 · 霜冠巨灵", [enemy("frost_boss", "霜冠巨灵", 640, 50, 18, 12, magic=48, resistance=15, mp=72, skill=magic), enemy("ice_wolf", "冰原猎狼", 200, 36, 10, 16)]),
         ]},
        {"id": "ancient_ruins", "name": "星落遗迹", "description": "失落的星仪仍在缓缓转动，终点是一座等待点亮的城。", "theme": "ancient_ruins",
         "sites": [
             ("sunken_gate", "沉星之门", "护盾与法术的古老防线", [enemy("ruin_guard", "青铜守卫", 380, 43, 20, 12, skill=shield), enemy("ruin_mage", "星尘术士", 220, 25, 8, 17, magic=53, resistance=18, mp=72, skill=magic)]),
             ("star_observatory", "无声观星台", "治疗者守护着两座石像", [enemy("ruin_guard", "青铜守卫", 400, 47, 20, 13, skill=shield), enemy("ruin_guard", "青铜守卫", 330, 40, 17, 11), enemy("ruin_oracle", "星灯司祭", 240, 25, 10, 18, magic=52, resistance=20, mp=88, skill=heal)]),
             ("dawn_core", "黎明之核", "遗迹首领 · 永夜执政官", [enemy("ruin_boss", "永夜执政官", 1000, 67, 22, 17, magic=63, resistance=18, mp=96, skill=magic), enemy("ruin_mage", "星尘术士", 220, 30, 10, 15, magic=40, mp=40, skill=magic)]),
         ]},
    ]
    outposts, previous = [], None
    for region_index, region in enumerate(regions):
        for index, (identity, name, description, enemies) in enumerate(region.pop("sites")):
            boss = index == 2
            outposts.append({"id": identity, "name": name, "description": description, "region_id": region["id"],
                "theme": region["theme"], "is_boss": boss, "prerequisites": [previous] if previous else [],
                "enemies": deepcopy(enemies), "position": {"x": region_index * 10 + index * 3, "z": [-2, 2, 0][index]},
                "reward_points": rules["battle"]["first_clear_points"]["boss" if boss else "outpost"],
                "trophy_code": f"trophy_{region['id']}" if boss else None})
            previous = identity
    return {"version": rules["version"], "regions": regions, "outposts": outposts,
            "license": "Original project content; no commercial game assets included."}
