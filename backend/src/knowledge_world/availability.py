"""Conservative API uptime evidence, independent of the worker's catch-up clock."""
from .common import uid

MAX_HEARTBEAT_GAP_MS = 45000


def heartbeat(db, process_id):
    with db.transaction(True) as c:
        last = c.one("SELECT * FROM service_availability WHERE process_id=:p ORDER BY through_at DESC LIMIT 1", {"p": process_id})
        if last and 0 <= c.now - last["through_at"] <= MAX_HEARTBEAT_GAP_MS:
            c.update("service_availability", last["id"], through_at=c.now)
        else:
            c.insert("service_availability", id=uid(), process_id=process_id, started_at=c.now, through_at=c.now)


def covered(c, start, end):
    """Only a continuously observed window authorizes a missed-checkin judgment.

    The last heartbeat may precede the deadline by one normal heartbeat interval.
    Missing evidence (including before migration) remains unknown, not failed.
    """
    ranges = c.all("SELECT started_at,through_at FROM service_availability WHERE started_at<=:end AND through_at>=:start ORDER BY started_at", {"start": start, "end": end})
    cursor = start
    for row in ranges:
        if row["started_at"] > cursor:
            break
        cursor = max(cursor, row["through_at"])
        if cursor >= end - 15000:
            return True
    return False
