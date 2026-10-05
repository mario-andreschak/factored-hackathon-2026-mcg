"""Focused checks for factual, repeatable agent replay and privacy boundaries."""
from pathlib import Path
from unittest.mock import patch
import json
import tempfile
import unittest

from scripts.history_sources.topology import derive, _read_actions, DOCKER_READER


T0 = '2026-09-25T22:00:00Z'
T1 = '2026-09-25T22:00:01Z'
T2 = '2026-09-25T22:00:02Z'
T3 = '2026-09-25T22:00:03Z'
T4 = '2026-09-25T22:00:04Z'
T5 = '2026-09-25T22:00:05Z'


def message(source, thread, identity, time, workspace=None):
    return {'id': identity, 'source': source, 'threadId': thread, 'timestamp': time,
            'title': 'Visible development message', 'body': 'Public work update',
            'metadata': {'workspace': workspace} if workspace else {}}


class TopologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'project'
        self.home = Path(self.temp.name) / 'codex'
        self.repo.mkdir()
        self.home.mkdir()
        self.config = {'codex': {'home': str(self.home)}}

    def rollout(self, identity, entries=(), created=T0, **extra):
        root = self.home / 'sessions'
        root.mkdir(exist_ok=True)
        path = root / f'{identity}.jsonl'
        records = [{'timestamp': created, 'type': 'session_meta', 'payload': {'id': identity, 'cwd': str(self.repo), 'timestamp': created, **extra}}, *entries]
        path.write_text('\n'.join(json.dumps(record) for record in records) + '\n', encoding='utf-8')
        return path

    def call(self, time, name, arguments, identity='call-1', custom=False):
        return {'timestamp': time, 'type': 'response_item', 'payload': {'type': 'custom_tool_call' if custom else 'function_call', 'name': name, 'call_id': identity,
                                                                     'input' if custom else 'arguments': arguments if custom else json.dumps(arguments)}}

    def derive(self, source=None, rows=(), **config):
        with patch('scripts.history_sources.topology._read_flujo', return_value=list(rows)):
            return derive(self.repo, source or {}, {**self.config, **config})

    def test_actual_spawn_and_steer_use_explicit_ids_without_prompts(self):
        self.rollout('main', [
            self.call(T1, 'spawn_agent', {'task_name': 'backend', 'message': 'PRIVATE TASK PROMPT'}),
            {'timestamp': T1, 'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'call-1', 'output': json.dumps({'task_name': '/root/backend', 'private': 'PRIVATE OUTPUT'})}},
            self.call(T3, 'send_message', {'target': 'backend', 'message': 'PRIVATE STEERING PROMPT'}, 'call-2'),
            {'timestamp': T3, 'type': 'response_item', 'payload': {'type': 'reasoning', 'text': 'PRIVATE REASONING'}},
        ])
        self.rollout('child', created=T2, parent_thread_id='main', agent_path='/root/backend')
        source = {'codex': {'events': [message('codex', 'main', 'msg-main', T1), message('codex', 'child', 'msg-child', T4)]}}
        first = self.derive(source)
        self.assertEqual([(e['kind'], e['from'], e['to']) for e in first['agentEdges']], [('spawn', 'codex:main', 'codex:child'), ('steer', 'codex:main', 'codex:child')])
        self.assertEqual(first['events'][0]['timestamp'], '2026-09-25T22:00:01Z')
        self.assertEqual(first['events'][0]['metadata']['targetSessionId'], 'codex:child')
        self.assertTrue(all(s['endedAt'] is None for s in first['sessions']))
        text = json.dumps(first)
        for hidden in ('PRIVATE TASK PROMPT', 'PRIVATE OUTPUT', 'PRIVATE STEERING PROMPT', 'PRIVATE REASONING'):
            self.assertNotIn(hidden, text)
        self.assertEqual(first, self.derive(source))

    def test_sibling_and_reused_agent_paths_do_not_resolve_to_future_agents(self):
        self.rollout('main')
        self.rollout('sender', [self.call(T3, 'send_message', {'target': '/root/backend', 'message': 'hello'})], created=T1, parent_thread_id='main', agent_path='/root/review')
        self.rollout('old', created=T2, parent_thread_id='main', agent_path='/root/backend')
        self.rollout('future', created=T5, parent_thread_id='main', agent_path='/root/backend')
        result = self.derive()
        steer = next(edge for edge in result['agentEdges'] if edge['kind'] == 'steer')
        self.assertEqual(steer['from'], 'codex:sender')
        self.assertEqual(steer['to'], 'codex:old')

    def test_nested_mcp_tool_call_parses_literal_structure_and_redacts_labels(self):
        secret = 'ghp_' + 'z' * 40
        code = 'const r = await tools.mcp__codex_app__send_message_to_thread(' + json.dumps({'threadId': 'child', 'prompt': 'PRIVATE PROMPT'}) + '); text(r);'
        self.rollout('main', [self.call(T3, 'exec', code, custom=True)])
        self.rollout('child', created=T2, title='Backend ' + secret)
        result = self.derive()
        steer = next(e for e in result['events'] if e['kind'] == 'agent_steer')
        self.assertEqual(steer['metadata']['targetSessionId'], 'codex:child')
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn('PRIVATE PROMPT', json.dumps(result))

    def test_javascript_object_keys_and_root_reports_are_resolved_safely(self):
        code = 'await tools.mcp__codex_app__send_message_to_thread({threadId: "child", prompt: "PRIVATE, threadId: fake", title: dynamicLabel});'
        self.rollout('main', [self.call(T3, 'exec', code, custom=True)])
        self.rollout('child', [self.call(T4, 'send_message', {'target': '/root', 'message': 'PRIVATE REPORT'}, 'report')], created=T2, parent_thread_id='main', agent_path='/root/backend')
        result = self.derive()
        steer = [edge for edge in result['agentEdges'] if edge['kind'] == 'steer']
        self.assertEqual([(e['from'], e['to']) for e in steer], [('codex:main', 'codex:child'), ('codex:child', 'codex:main')])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('fake', json.dumps(result))

    def test_batched_create_outputs_cannot_assign_one_result_id_to_two_chats(self):
        code = ';'.join('await tools.mcp__codex_app__create_thread(' + json.dumps({'title': label, 'prompt': 'PRIVATE TASK', 'target': {'type': 'projectless'}}) + ')' for label in ('First', 'Second'))
        self.rollout('main', [self.call(T1, 'exec', code, custom=True),
            {'timestamp': T2, 'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'call-1', 'output': json.dumps({'threadId': 'child'})}}])
        self.rollout('child', created=T2)
        result = self.derive()
        self.assertEqual(result['agentEdges'], [])
        self.assertEqual(result['stats']['ambiguousBatchedResults'], 1)
        self.assertEqual(len(result['events']), 2)
        self.assertTrue(all(e['metadata']['targetResolved'] is False for e in result['events']))
        self.assertNotIn('PRIVATE TASK', json.dumps(result))

    def flow_rows(self):
        first = {'id': 'flow', 'name': 'Hackathon_Release_Supervisor', 'updatedAt': T0,
                 'nodes': [{'id': 'a', 'label': 'Supervisor', 'type': 'process', 'x': 10, 'y': 20}, {'id': 'b', 'label': 'Builder', 'type': 'subflow', 'x': 100, 'y': 20, 'subflowId': 'child-flow'}],
                 'edges': [{'id': 'a-b', 'from': 'a', 'to': 'b', 'type': 'custom'}]}
        latest = {**first, 'updatedAt': T5, 'nodes': first['nodes'] + [{'id': 'future-node', 'label': 'Later addition', 'type': 'process', 'x': 200, 'y': 20}]}
        return [{'kind': 'flow', 'workspace': 'w', 'basis': 'saved-version', 'versionId': 'original', 'savedAt': T0, 'flow': first},
                {'kind': 'flow', 'workspace': 'w', 'basis': 'current-declaration', 'flow': latest}]

    def conversation(self, identity='parent', **extra):
        return {'kind': 'conversation', 'workspace': 'w', 'conversationId': identity, 'flowId': 'flow',
                'flowName': 'Hackathon_Release_Supervisor', 'title': 'Develop release', 'createdAt': T1,
                'currentNodeId': 'b', 'status': 'completed', **extra}

    def log(self, typ, time, sequence, **extra):
        return {'kind': 'log', 'workspace': 'w', 'conversationId': 'parent', 'type': typ,
                'timestamp': time, 'seq': sequence, 'line': sequence, **extra}

    def test_historical_graph_is_declared_until_real_execution_and_status_is_not_a_finish(self):
        rows = self.flow_rows() + [self.conversation()]
        result = self.derive(rows=rows)
        session = next(s for s in result['sessions'] if s['source'] == 'flujo')
        selected = next(f for f in result['flows'] if f['id'] == session['flowId'])
        self.assertEqual([n['id'] for n in selected['nodes']], ['a', 'b'])
        self.assertEqual(selected['nodes'][0]['x'], 10)
        self.assertEqual(result['events'], [])
        self.assertTrue(all(f['declaredOnly'] for f in result['flows']))
        self.assertIsNone(session['endedAt'])
        self.assertIn('exact executed revision may differ', session['graphBasis'])

    def test_real_parallel_subflow_lifetimes_handoffs_and_message_node_binding(self):
        rows = self.flow_rows() + [self.conversation(), self.conversation('child', parentConversationId='parent', createdAt=T2, subflowLane={'parentNodeId': 'b', 'laneIndex': 0, 'laneCount': 2}),
            self.log('node:enter', T1, 1, node={'nodeId': 'a', 'nodeName': 'Supervisor', 'nodeType': 'process'}),
            self.log('subflow:start', T2, 2, node={'nodeId': 'b', 'nodeName': 'Builder'}, laneConversationId='child', laneCount=2),
            self.log('node:enter', T2, 3, node={'nodeId': 'unrelated-child-node'}, depth=1),
            self.log('handoff', T3, 4, **{'from': {'nodeId': 'a'}, 'toNodeId': 'b', 'edgeId': 'a-b'}),
            self.log('subflow:done', T4, 5, node={'nodeId': 'b'}, laneConversationId='child', status='completed'),
            self.log('run:done', T5, 6, status='completed')]
        source = {'flujo': {'events': [message('flujo', 'parent', 'parent-message', T3, 'w'), message('flujo', 'child', 'child-message', T3, 'w')]}}
        result = self.derive(source, rows)
        sessions = {s['id']: s for s in result['sessions']}
        self.assertEqual(sessions['flujo:w:child']['parentId'], 'flujo:w:parent')
        self.assertEqual(sessions['flujo:w:child']['endedAt'], '2026-09-25T22:00:04Z')
        self.assertEqual(sessions['flujo:w:parent']['endedAt'], '2026-09-25T22:00:05Z')
        self.assertEqual(sessions['flujo:w:child']['laneCount'], 2)
        self.assertEqual(source['flujo']['events'][0]['metadata']['nodeId'], 'a')
        handoff = next(e for e in result['agentEdges'] if e['kind'] == 'node_transition')
        self.assertEqual((handoff['fromNodeId'], handoff['toNodeId']), ('a', 'b'))
        self.assertEqual(handoff['eventIds'], ['flujo:execution:w:parent:4'])
        self.assertFalse(next(f for f in result['flows'] if f['id'] == sessions['flujo:w:parent']['flowId'])['declaredOnly'])

    def test_detached_tasks_and_skipped_schedule_are_real_records(self):
        rows = self.flow_rows() + [self.conversation(), self.conversation('child', createdAt=T2),
            {'kind': 'task', 'workspace': 'w', 'taskId': 'task', 'originConversationId': 'parent', 'originNodeId': 'b', 'childConversationId': 'child', 'createdAt': T2, 'completedAt': T4, 'status': 'completed'},
            {'kind': 'planned-run', 'workspace': 'w', 'planId': 'schedule', 'runId': 'skipped', 'planName': 'Release supervisor', 'flowId': 'flow', 'conversationId': '', 'firedAt': T3, 'finishedAt': T3, 'status': 'skipped'}]
        result = self.derive(rows=rows)
        kinds = [e['kind'] for e in result['events']]
        self.assertEqual(sorted(kinds), ['schedule_trigger', 'task_completed', 'task_dispatched'])
        scheduler = next(s for s in result['sessions'] if s['role'] == 'scheduler')
        self.assertIsNone(scheduler['threadId'])
        self.assertIsNone(scheduler['endedAt'])
        child = next(s for s in result['sessions'] if s['threadId'] == 'child')
        self.assertEqual(child['parentId'], 'flujo:w:parent')
        self.assertEqual(child['endedAt'], '2026-09-25T22:00:04Z')

    def test_forwarded_child_model_turns_match_the_executing_child_graph(self):
        child_graph = {'id': 'child-flow', 'name': 'Hackathon_Release_Builder', 'nodes': [{'id': 'build', 'label': 'Build', 'type': 'process', 'x': 1, 'y': 2}], 'edges': []}
        rows = self.flow_rows() + [
            {'kind': 'flow', 'workspace': 'w', 'basis': 'saved-version', 'savedAt': T0, 'versionId': 'child-version', 'flow': child_graph},
            self.conversation(), self.conversation('child', flowId='child-flow', flowName='Hackathon_Release_Builder', parentConversationId='parent', createdAt=T2),
            self.log('model:dispatch', T3, 1, depth=1, turn={'id': 'dispatch', 'conversationId': 'child', 'adapter': 'codex-cli', 'node': {'nodeId': 'build', 'nodeName': 'Build'}}),
            self.log('model:dispatch-result', T4, 2, depth=1, dispatchId='dispatch', outcome='completed')]
        result = self.derive(rows=rows)
        model_events = [e for e in result['events'] if e['kind'].startswith('model_dispatch')]
        self.assertEqual(len(model_events), 2)
        for event in model_events:
            self.assertEqual(event['metadata']['nodeId'], 'build')
            self.assertEqual(event['metadata']['flowDefinitionId'], 'child-flow')
            self.assertEqual(event['metadata']['executingSessionId'], 'flujo:w:child')
            self.assertEqual(event['metadata']['observedInSessionId'], 'flujo:w:parent')
        self.assertEqual(model_events[1]['metadata']['dispatchId'], 'dispatch')

    def test_offline_and_missing_records_do_not_invent_dispatches(self):
        source = {'codex': {'threads': [{'id': 'main', 'title': 'Supervisor', 'createdAt': T0}], 'events': [message('codex', 'main', 'visible', T1)]}}
        with patch('scripts.history_sources.topology._read_actions', side_effect=AssertionError('live call')), patch('scripts.history_sources.topology._read_flujo', side_effect=AssertionError('live call')):
            result = derive(self.repo, source, {**self.config, 'offline': True})
        self.assertEqual(result['events'], [])
        self.assertEqual(result['sessions'][0]['lastActivityAt'], T1)
        self.assertIsNone(result['sessions'][0]['endedAt'])
        self.assertIn('Offline', result['notes'][0])
        self.assertNotIn('frozenSystemPrompts', DOCKER_READER)
        self.assertNotIn('variables', DOCKER_READER)


if __name__ == '__main__':
    unittest.main()
