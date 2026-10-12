from knowledge_world.common import uid
from knowledge_world import agent, system, game_models as g, models as m
from knowledge_world.common import dumps


def test_fixed_task_completion_is_repeatable_but_same_report_is_once_only(h):
    task = h.post('/system/fixed-tasks', {'title': '复习错题', 'description': '复习一组错题', 'reward_points': 12})
    completion = uid()
    first = h.post(f"/system/fixed-tasks/{task['id']}/complete", {'completion_id': completion})
    again = h.post(f"/system/fixed-tasks/{task['id']}/complete", {'completion_id': completion})
    assert first == again
    assert h.get('/wallet')['available_points'] == 12
    h.post(f"/system/fixed-tasks/{task['id']}/complete", {'completion_id': uid()})
    assert h.get('/wallet')['available_points'] == 24
    h.request('DELETE', f"/system/fixed-tasks/{task['id']}", {'expected_version': task['version']})
    assert h.get('/system/fixed-tasks') == []
    h.request('POST', f"/system/fixed-tasks/{task['id']}/complete", {'completion_id': uid()}, status=409)
    h.reconcile()


def test_pending_terms_hide_accepted_entities_and_duplicate_tool_cards(h):
    with h.db.transaction(True, h.owner) as c:
        thread = agent.create_thread(c, m.ThreadCreate(title='SYNTHETIC terms', context={}))
        challenge = system.propose_challenge(c, g.ChallengeProposal(title='测试条款', goal='完成任务', reward_points=10))
        run = uid()
        c.insert('agent_runs', id=run, owner_id=c.owner, thread_id=thread['id'], state='succeeded', prompt_version='test', provider_snapshot_json='{}', context_snapshot_json='{}', created_at=c.now)
        for seq in (1, 2):
            c.insert('agent_tool_calls', id=uid(), run_id=run, sequence=seq, tool_name='propose_challenge', arguments_json='{}', result_json=dumps(challenge), command_key=uid(), state='proposed', created_at=c.now)
        assert len(agent.thread_detail(c, thread['id'])['actions']) == 1
        system.accept_challenge(c, challenge['id'], m.AcceptTerms(expected_version=challenge['version'], terms_hash=challenge['terms_hash']))
        assert agent.thread_detail(c, thread['id'])['actions'] == []
