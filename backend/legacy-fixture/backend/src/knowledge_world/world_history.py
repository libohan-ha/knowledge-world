"""Read-only, append-bounded world history for Three.js presentation and replay."""

import json

from itsdangerous import BadSignature

from .common import DomainError, STAGES, iso, local_ms, require
from .plans import valid_date
from .models import WorldHistoryCoverage, WorldHistoryEvent, WorldHistoryPage
from .rewards import signer


# Resolve and verify identities on the server. Archived sources stay readable;
# no live-list predicate may remove their historical events.
HISTORY_SELECT = """
SELECT e.*,w.id plot_id,r.id region_id,p.id verified_point_id,ch.id chapter_id,
       CASE WHEN cl.point_id=e.point_id AND source_activity.id IS NOT NULL THEN a.id END assessment_id,
       source_activity.id source_activity_id,
       ag.id achievement_id,l.id verified_ledger_id,l.business_date,
       CASE WHEN ag.id IS NOT NULL AND e.event_key='chapter-landmark:'||ag.id
          AND NOT EXISTS (
              SELECT 1 FROM world_events duplicate
              JOIN world_event_order dq ON dq.event_id=duplicate.id
              WHERE duplicate.owner_id=e.owner_id AND duplicate.kind='chapter_landmark'
                AND json_extract(duplicate.payload_json,'$.achievement_id')=ag.id
                AND duplicate.id!=e.id AND dq.sequence<=:upper
          ) THEN 1 ELSE 0 END legacy_landmark_verified
FROM world_events e JOIN world_event_order q ON q.event_id=e.id
LEFT JOIN knowledge_points p ON p.id=e.point_id AND p.owner_id=e.owner_id
LEFT JOIN world_plots w ON w.point_id=p.id
LEFT JOIN world_regions r ON r.id=w.region_id AND r.owner_id=e.owner_id
LEFT JOIN chapters ch ON ch.owner_id=e.owner_id AND ch.id=CASE WHEN e.kind='chapter_landmark'
    THEN json_extract(e.payload_json,'$.chapter_id') ELSE p.chapter_id END
LEFT JOIN assessments a ON e.kind='learning' AND a.owner_id=e.owner_id
    AND a.id=COALESCE(json_extract(e.payload_json,'$.assessment_id'),
        CASE WHEN substr(e.event_key,1,11)='assessment:' THEN substr(e.event_key,12) END)
LEFT JOIN learning_claims cl ON cl.id=a.claim_id AND cl.owner_id=e.owner_id
LEFT JOIN activities source_activity ON source_activity.id=a.activity_id
    AND source_activity.owner_id=e.owner_id AND source_activity.claim_id=cl.id
LEFT JOIN achievement_grants ag ON e.kind='chapter_landmark' AND ag.owner_id=e.owner_id
    AND ag.id=json_extract(e.payload_json,'$.achievement_id') AND ag.code='chapter:'||ch.id
LEFT JOIN ledger_entries l ON l.owner_id=e.owner_id AND l.id=CASE
    WHEN e.kind='learning' AND cl.point_id=e.point_id THEN e.ledger_id
    WHEN e.kind='chapter_landmark' THEN ag.ledger_id END
    AND (e.kind!='learning' OR l.assessment_id=a.id)
WHERE e.owner_id=:owner AND q.sequence<=:upper
    AND e.kind IN ('learning','chapter_landmark')
    AND e.created_at>=:start_ms AND e.created_at<:end_ms
    AND (:region IS NULL OR r.id=:region)
"""


def range_coverage(c, params):
    # Count complete records in SQLite rather than constructing a Pydantic event
    # (and nested presentation/source objects) for every event in the range.
    # A receipt is optional; ownership-checked identity and applicable states are
    # required, exactly as in event_view's missing_fields contract.
    stages = ','.join("'" + stage + "'" for stage in STAGES)
    learning_states = ' AND '.join(
        f"json_extract(payload_json,'$.presentation.{side}.{field}') IN ({stages})"
        for side in ['before', 'after'] for field in ['current_stage', 'best_stage']
    )
    counts = c.one(
        f"""SELECT count(*) event_total, COALESCE(sum(CASE WHEN
            json_type(payload_json,'$.presentation.version')='integer'
            AND json_extract(payload_json,'$.presentation.version')=1
            AND json_type(payload_json,'$.presentation.is_correction') IN ('true','false')
            AND verified_point_id IS NOT NULL AND plot_id IS NOT NULL AND region_id IS NOT NULL
            AND ((kind='learning' AND NULLIF(assessment_id,'') IS NOT NULL AND {learning_states})
                OR (kind='chapter_landmark' AND NULLIF(achievement_id,'') IS NOT NULL
                    AND chapter_id IS NOT NULL
                    AND json_type(payload_json,'$.presentation.before.landmark_present') IN ('true','false')
                    AND json_type(payload_json,'$.presentation.after.landmark_present') IN ('true','false')))
            THEN 1 ELSE 0 END),0) complete_state_total
        FROM ({HISTORY_SELECT})""",
        params,
    )
    return WorldHistoryCoverage(**counts, partial_state_total=counts['event_total'] - counts['complete_state_total']).model_dump()


def numeric_stage(value):
    return STAGES[value] if type(value) is int and 0 <= value < len(STAGES) else None


def event_view(row):
    payload = json.loads(row['payload_json'])
    payload = payload if isinstance(payload, dict) else {}
    presentation = payload.get('presentation')
    presentation = presentation if isinstance(presentation, dict) else {}
    version = presentation.get('version')
    version = version if type(version) is int and version > 0 else None
    before = dict(current_stage=None, best_stage=None, landmark_present=None)
    after = before.copy()
    correction = None
    if version == 1:
        for key, target in [('before', before), ('after', after)]:
            state = presentation.get(key)
            if not isinstance(state, dict):
                continue
            if row['kind'] == 'learning':
                for field in ['current_stage', 'best_stage']:
                    if state.get(field) in STAGES:
                        target[field] = state[field]
            elif type(state.get('landmark_present')) is bool:
                target['landmark_present'] = state['landmark_present']
        if type(presentation.get('is_correction')) is bool:
            correction = presentation['is_correction']
    elif version is None:
        if row['kind'] == 'learning':
            before['current_stage'] = numeric_stage(payload.get('before_stage'))
            after['current_stage'] = numeric_stage(payload.get('stage'))
            after['best_stage'] = numeric_stage(payload.get('best_stage'))
        elif row['legacy_landmark_verified']:
            before['landmark_present'], after['landmark_present'] = False, True

    source_id = row['assessment_id'] if row['kind'] == 'learning' else row['achievement_id']
    source = {'kind': 'assessment' if row['kind'] == 'learning' else 'achievement', 'id': source_id,
              'activity_id': row['source_activity_id'] if row['kind'] == 'learning' else None} if source_id else None
    missing = []
    applicable = ['current_stage', 'best_stage'] if row['kind'] == 'learning' else ['landmark_present']
    for key, state in [('before', before), ('after', after)]:
        missing += [key + '.' + field for field in applicable if state[field] is None]
    if correction is None:
        missing.append('is_correction')
    if source is None:
        missing.append('source')
    if version != 1:
        missing.append('presentation_version')
    for name, value in [('point_id', row['verified_point_id']), ('plot_id', row['plot_id']), ('region_id', row['region_id'])]:
        if value is None:
            missing.append(name)
    if row['kind'] == 'chapter_landmark' and row['chapter_id'] is None:
        missing.append('chapter_id')
    return WorldHistoryEvent(
        id=row['id'], event_key=row['event_key'], kind=row['kind'], occurred_at=iso(row['created_at']),
        region_id=row['region_id'], plot_id=row['plot_id'] if row['region_id'] else None,
        point_id=row['verified_point_id'], chapter_id=row['chapter_id'], source=source,
        ledger_id=row['verified_ledger_id'],
        learning_business_date=row['business_date'] if row['kind'] == 'learning' else None,
        presentation_version=version, before=before, after=after, is_correction=correction,
        coverage='partial' if missing else 'complete', missing_fields=missing,
    )


def decode(serializer, token, purpose):
    try:
        value = serializer.loads(token)
    except (BadSignature, ValueError, TypeError):
        raise DomainError('CURSOR_INVALID', '成长历史游标无效，请重新加载', 400)
    require(isinstance(value, dict) and value.get('type') == purpose, 'CURSOR_INVALID', '成长历史游标用途不匹配', 400)
    return value


def history(c, date_from, date_to, region_id=None, cursor=None, limit=20):
    valid_date(date_from)
    valid_date(date_to)
    require(date_from <= date_to, 'INVALID_DATE', '开始日期不能晚于结束日期', 400)
    require(1 <= limit <= 100, 'INVALID_INPUT', '每页需为 1—100 条', 400)
    # SQLite legacy transaction mode does not begin on SELECT. Hold a short
    # request-local read snapshot, never a transaction spanning browser pages.
    if not c.s.connection().connection.driver_connection.in_transaction:
        c.execute('BEGIN')
    if region_id:
        c.get('world_regions', region_id)
    epoch = c.scalar('SELECT epoch FROM world_history_state WHERE id=1')
    upper = c.scalar('SELECT COALESCE(max(sequence),0) FROM world_event_order')
    serializer = signer(c.db.settings)
    after = None
    if cursor:
        decoded = decode(serializer, cursor, 'world-history-cursor-v1')
        snapshot_token = decoded.get('snapshot')
        snapshot = decode(serializer, snapshot_token, 'world-history-snapshot-v1')
        require(
            snapshot.get('owner') == c.owner and snapshot.get('date_from') == date_from
            and snapshot.get('date_to') == date_to and snapshot.get('region_id') == region_id,
            'CURSOR_INVALID', '游标不属于当前账户或筛选范围', 400,
        )
        require(snapshot.get('epoch') == epoch, 'HISTORY_SNAPSHOT_EXPIRED', '数据库已恢复，请重新加载成长历史', 409)
        require(type(snapshot.get('upper')) is int and 0 <= snapshot['upper'] <= upper,
                'HISTORY_SNAPSHOT_EXPIRED', '成长历史快照已失效，请重新加载', 409)
        after = decoded.get('after')
        require(isinstance(after, list) and len(after) == 2 and type(after[0]) is int and isinstance(after[1], str),
                'CURSOR_INVALID', '成长历史游标位置无效', 400)
    else:
        snapshot = dict(type='world-history-snapshot-v1', owner=c.owner, epoch=epoch,
                        date_from=date_from, date_to=date_to, region_id=region_id,
                        timezone=c.tz, upper=upper, as_of=c.now)
    try:
        start_ms = local_ms(date_from, tz=snapshot['timezone'])
        end_ms = local_ms(date_to, tz=snapshot['timezone'], offset=1)
    except (ValueError, OverflowError, OSError):
        raise DomainError('INVALID_DATE', '日期超出可查询范围', 400)
    params = {'owner': c.owner, 'upper': snapshot['upper'], 'start_ms': start_ms,
              'end_ms': end_ms, 'region': region_id, 'limit': limit + 1}
    coverage = snapshot.get('coverage') or range_coverage(c, params)
    if not cursor:
        snapshot['coverage'] = coverage
        snapshot_token = serializer.dumps(snapshot)
    condition = ''
    if after:
        condition = ' AND (e.created_at>:last_time OR (e.created_at=:last_time AND e.id>:last_id))'
        params.update(last_time=after[0], last_id=after[1])
    rows = c.all(HISTORY_SELECT + condition + ' ORDER BY e.created_at,e.id LIMIT :limit', params)
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = serializer.dumps({'type': 'world-history-cursor-v1', 'snapshot': snapshot_token,
                                    'after': [rows[-1]['created_at'], rows[-1]['id']]}) if more else None
    return WorldHistoryPage(
        items=[event_view(row) for row in rows], next_cursor=next_cursor,
        as_of=iso(snapshot['as_of']), snapshot_token=snapshot_token,
        range={'date_from': date_from, 'date_to': date_to, 'timezone': snapshot['timezone']},
        coverage=coverage,
    ).model_dump()
