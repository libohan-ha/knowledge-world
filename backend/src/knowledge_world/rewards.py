"""Read-only legacy orders and explicit closure; no generation or new orders."""
from .common import require, check_version, public
from .economy import append


def legacy_order_view(c, identity):
    row = c.get("redemptions", identity)
    item = c.get("catalog_items", row["catalog_code"], key="code", owned=False)
    asset = c.one("SELECT id FROM generated_assets WHERE owner_id=:o AND redemption_id=:id", {"o": c.owner, "id": identity})
    return {
        "id": identity, "name": item["name"], "state": row["state"], "version": row["version"],
        "price_points": row["price_coins"], "rule_version": row["rule_version"],
        "created_at": public(row)["created_at"], "asset_id": asset["id"] if asset else None,
        "ledger_entry_ids": [r["id"] for r in c.all("SELECT id FROM ledger_entries WHERE owner_id=:o AND origin_type='redemption' AND origin_id=:id ORDER BY sequence", {"o": c.owner, "id": identity})],
        "can_close": row["state"] in {"reserved", "running", "needs_review"},
    }


def close_legacy_order(c, identity, data):
    row = c.get("redemptions", identity)
    check_version(row, data.expected_version)
    require(row["state"] in {"reserved", "running", "needs_review"}, "ACTION_NOT_ALLOWED", "此旧订单已结束")
    c.audit("legacy_order.close", "redemption", identity, {"reason": data.reason, "supplier_refund_claimed": False})
    cancel(c, identity, row["version"])
    c.change("wallet", "settings")
    return legacy_order_view(c, identity)


def redemption_detail(c, identity):
    row = c.get("redemptions", identity)
    view = public(row)
    view.pop("provider_snapshot", None)
    view["terms_snapshot"].pop("owner_id", None)
    asset = c.one("SELECT * FROM generated_assets WHERE redemption_id=:id", {"id": identity})
    job = c.one(
        "SELECT * FROM jobs WHERE json_extract(payload_json,'$.redemption_id')=:id ORDER BY created_at DESC LIMIT 1",
        {"id": identity},
    )
    return {
        **view,
        "asset": public(asset),
        "job_id": job["id"] if job else None,
        "receipts": [
            public(r)
            for r in c.all(
                "SELECT * FROM ledger_entries WHERE owner_id=:o AND origin_type='redemption' AND origin_id=:id ORDER BY sequence",
                {"o": c.owner, "id": identity},
            )
        ],
    }


def fail(c, identity, attempt, reason, cancelled=False):
    row = c.get("redemptions", identity)
    if row["attempt_number"] != attempt or row["state"] in {"succeeded", "failed", "cancelled"}:
        return
    append(
        c,
        "redemption_refund",
        "shop",
        f"redemption:{identity}:attempt:{attempt}:settlement",
        "redemption",
        identity,
        available=row["price_coins"],
        held=-row["price_coins"],
        rule_version=row["rule_version"],
        detail={"reason": reason, "attempt": attempt, "supplier_refund_claimed": False},
    )
    c.update(
        "redemptions",
        identity,
        state="cancelled" if cancelled else "failed",
        version=row["version"] + 1,
        updated_at=c.now,
    )
    c.execute(
        "UPDATE story_chapters SET state='failed' WHERE redemption_id=:id AND state='pending'",
        {"id": identity},
    )


def cancel(c, identity, version):
    row = c.get("redemptions", identity)
    check_version(row, version)
    require(row["state"] != "succeeded", message="作品已经交付")
    fail(c, identity, row["attempt_number"], "用户结束尝试", True)
    c.execute(
        "UPDATE jobs SET state='cancelled',lease_token=lease_token+1,updated_at=:at WHERE json_extract(payload_json,'$.redemption_id')=:id AND state IN ('queued','running','retry_wait','needs_review')",
        {"id": identity, "at": c.now},
    )
    return redemption_detail(c, identity)
