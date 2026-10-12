"""Explicit user-configured rewards; each reported completion has one source."""
import json
from .common import uid, public, require, check_version, dumps
from .economy import append
from .game_events import emit, wallet_view


def catalog(c):
    return [public(r) for r in c.all('SELECT * FROM fixed_tasks WHERE owner_id=:o AND enabled=1 ORDER BY created_at,id', {'o': c.owner})]


def save(c, data, identity=None):
    values = data.model_dump(exclude={'expected_version'})
    if identity:
        row = c.get('fixed_tasks', identity)
        require(row['enabled'], message='任务已删除')
        check_version(row, data.expected_version)
        c.update('fixed_tasks', identity, **values, version=row['version'] + 1, updated_at=c.now)
    else:
        identity = uid()
        c.insert('fixed_tasks', id=identity, owner_id=c.owner, **values, created_at=c.now, updated_at=c.now)
    c.change('system')
    return public(c.get('fixed_tasks', identity))


def disable(c, identity, version):
    row = c.get('fixed_tasks', identity)
    check_version(row, version)
    c.update('fixed_tasks', identity, enabled=0, version=row['version'] + 1, updated_at=c.now)
    c.change('system')
    return public(c.get('fixed_tasks', identity))


def complete(c, identity, completion_id):
    task = c.get('fixed_tasks', identity)
    old = c.one('SELECT * FROM fixed_task_completions WHERE owner_id=:o AND completion_id=:k', {'o': c.owner, 'k': completion_id})
    if old:
        require(old['task_id'] == identity, 'IDEMPOTENCY_CONFLICT', '此完成标识已用于另一任务')
        return json.loads(old['receipt_json'])
    require(task['enabled'], message='任务已删除')
    source = 'fixed-task:' + completion_id
    entry = append(c, 'achievement', 'achievement', source, 'fixed_task', identity,
        available=task['reward_points'], economic_kind='fixed_task_reward',
        detail={'reason': task['title'], 'completion_id': completion_id, 'task_version': task['version'], 'user_reported': True})
    event = emit(c, source, 'system_reward', 'fixed_task', identity, after={'points': task['reward_points'], 'title': task['title']},
        ledger_ids=[entry['id']] if entry else [], detail={'reason': task['title']})
    receipt = {'completion_id': completion_id, 'task_id': identity, 'title': task['title'], 'awarded_points': task['reward_points'],
        'ledger_entry_ids': [entry['id']] if entry else [], 'game_event_ids': [event['id']], 'wallet': wallet_view(c)}
    c.insert('fixed_task_completions', id=uid(), owner_id=c.owner, task_id=identity, completion_id=completion_id,
        receipt_json=dumps(receipt), created_at=c.now)
    c.change('system', 'wallet', 'ledger')
    return receipt
