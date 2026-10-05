/* Node-only Canvas contract tests. Run: node --test tests/dev_history_graph.test.cjs */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const zlib = require('node:zlib');
const rendererSource = fs.readFileSync(path.join(__dirname, '../web/dev-history/graph-scene.js'), 'utf8');
const TIME = '2026-10-01T15:00:00.000Z';
const LATER = '2026-10-01T17:00:00.000Z';

function harness(width = 950, height = 650) {
  const commands = [], listeners = new Map();
  const context = new Proxy({
    measureText(text) { return { width: String(text).length * 7 }; },
    createLinearGradient(...args) { commands.push(['linearGradient', ...args]); return { addColorStop(...stop) { commands.push(['colorStop', ...stop]); } }; },
    createRadialGradient(...args) { commands.push(['radialGradient', ...args]); return { addColorStop(...stop) { commands.push(['colorStop', ...stop]); } }; }
  }, {
    get(object, key) { return key in object ? object[key] : (...args) => commands.push([key, ...args]); },
    set(object, key, value) { object[key] = value; commands.push(['property', key, value]); return true; }
  });
  const canvas = {
    getContext() { return context; },
    getBoundingClientRect() { return { width, height, left: 0, top: 0 }; },
    addEventListener(name, fn) { listeners.set(name, fn); },
    removeEventListener(name) { listeners.delete(name); },
    setPointerCapture() {}, style: {}
  };
  const sandbox = { window: { devicePixelRatio: 1 }, Intl, Date, Map, Set, Math, Number, String, Boolean, Array, Infinity };
  vm.runInNewContext(rendererSource, sandbox, { filename: 'graph-scene.js' });
  const selected = [];
  const scene = new sandbox.window.HistoryGraphScene(canvas, { onSelect(hit) { selected.push(hit); } });
  return { scene, commands, canvas, listeners, selected };
}

function fixture() {
  const event = { id: 'event:spawn', source: 'codex', threadId: 'parent', timestamp: TIME, kind: 'agent_spawn', references: [], metadata: { sessionId: 'codex:parent' } };
  const flowEvent = { id: 'event:handoff', source: 'flujo', timestamp: TIME, kind: 'handoff', references: [], metadata: { sessionId: 'flujo:parent', executingSessionId: 'flujo:child', eventType: 'handoff', nodeId: 'coordinator', fromNodeId: 'coordinator', toNodeId: 'reviewer', flowId: 'flow:snapshot', basis: 'Timestamped persisted FLUJO execution log' } };
  const machines = Array.from({ length: 8 }, (_, index) => ({ id: `docker:${index}`, label: `Recorded container ${index}`, provider: 'docker', location: 'Docker Desktop · local host', createdAt: TIME, firstTimestamp: TIME, currentSnapshot: true, lastObservedAt: LATER, evidenceEventIds: [`event:machine:${index}`] }));
  const machineEvents = machines.map(machine => ({ id: machine.evidenceEventIds[0], timestamp: TIME, source: 'infrastructure', kind: 'machine_start', references: [], metadata: { machineId: machine.id, lifecycle: 'start' } }));
  return {
    event, flowEvent, machineEvents,
    data: {
      events: [event, flowEvent, ...machineEvents],
      landscape: {
        nodes: [{ id: 'codex', source: 'codex', label: 'Codex', firstTimestamp: TIME }, { id: 'github', source: 'github', label: 'GitHub', firstTimestamp: TIME }, { id: 'flujo', source: 'flujo', label: 'FLUJO', firstTimestamp: TIME }],
        edges: [{ id: 'shared:codex:github', from: 'codex', to: 'github', firstTimestamp: TIME, basis: 'Explicit cross-source references', evidenceIds: ['event:reference'] }, { id: 'inferred:codex:flujo', from: 'codex', to: 'flujo', firstTimestamp: TIME, basis: 'Inferred from configuration', evidenceIds: [event.id] }]
      },
      topology: {
        sessions: [
          { id: 'codex:parent', source: 'codex', threadId: 'parent', label: 'Supervise the release', startedAt: TIME, eventIds: [event.id] },
          { id: 'codex:child', source: 'codex', threadId: 'child', parentId: 'codex:parent', label: 'Implement the frontend', startedAt: TIME, eventIds: [] },
          { id: 'flujo:parent', source: 'flujo', label: 'Release coordinator', startedAt: TIME, eventIds: [flowEvent.id], flowId: 'flow:snapshot' },
          { id: 'flujo:child', source: 'flujo', parentId: 'flujo:parent', label: 'Independent reviewer', startedAt: TIME, eventIds: [], flowId: 'flow:snapshot' }
        ],
        agentEdges: [{ id: 'spawn:1', kind: 'spawn', from: 'codex:parent', to: 'codex:child', timestamp: TIME, eventIds: [event.id], basis: 'Recorded spawn tool call' }, { id: 'flow:handoff', kind: 'node_transition', from: 'flujo:parent', to: 'flujo:parent', flowId: 'flow:snapshot', fromNodeId: 'coordinator', toNodeId: 'reviewer', timestamp: TIME, eventIds: [flowEvent.id], basis: 'Timestamped persisted FLUJO execution log' }],
        flows: [{ id: 'flow:snapshot', source: 'flujo', label: 'Recorded release graph', availableFrom: TIME, declaredOnly: false, nodes: [{ id: 'coordinator', label: 'Coordinator', type: 'agent', x: 0, y: 0 }, { id: 'reviewer', label: 'Reviewer', type: 'agent', x: 300, y: 200 }], edges: [{ id: 'coordinator-reviewer', from: 'coordinator', to: 'reviewer', label: 'Handoff' }] }]
      },
      infrastructure: { machines, builds: [{ id: 'build:1', provider: 'docker', timestamp: TIME, state: 'completed', evidenceEventIds: [machineEvents[0].id] }], deployments: [] }
    }
  };
}

function frame(view, event, playing = false, progress = 0.5) {
  return { view, now: Date.parse(TIME), selectedEvent: event, eventCursor: 0, playing, progress, reducedMotion: false };
}
const packets = commands => commands.filter(command => command[0] === 'arc' && command[3] === 3.5);
const snapshotFile = path.join(__dirname, '../web/dev-history/data/history-data.js');
let capturedDataset;
function actualDataset() {
  if (!capturedDataset) {
    const match = fs.readFileSync(snapshotFile, 'utf8').match(/atob\('([^']+)'\)/);
    assert.ok(match, 'generated browser snapshot must have a native gzip payload');
    capturedDataset = JSON.parse(zlib.gunzipSync(Buffer.from(match[1], 'base64')).toString('utf8'));
  }
  return capturedDataset;
}
function assertNoOverlap(hits, description) {
  const nodes = hits.filter(hit => hit.rect);
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
    const a = nodes[i].rect, b = nodes[j].rect;
    assert.equal(a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y, false, `${description}: ${nodes[i].id} overlaps ${nodes[j].id}`);
  }
}
const capturedOptions = { skip: !fs.existsSync(snapshotFile) && 'Run the development-history rebuild to enable actual-data regression coverage.' };

test('Savia product scope excludes development hosts and preserves their separate view', () => {
  const story = JSON.parse(fs.readFileSync(path.join(__dirname, '../scripts/history_story.json'), 'utf8'));
  const productNodes = story.nodes.filter(node => node.group === 'product');
  assert.equal(productNodes.length, 12);
  for (const [width, height] of [[950, 650], [650, 460], [390, 560]]) {
    const { scene, commands } = harness(width, height), { data, event } = fixture();
    data.landscape.nodes.push(...productNodes.map(node => ({ ...node, firstTimestamp: TIME })));
    data.landscape.nodes.push({ id:'reviewer-machine', source:'infrastructure', label:'Reviewer test Machine', firstTimestamp:TIME });
    data.landscape.edges.push(...story.edges.filter(edge => edge.from.startsWith('savia-')).map(edge => ({ ...edge, firstTimestamp:TIME })));
    scene.setData(data); scene.render(frame('landscape', event));
    let nodes = scene.hits.filter(hit => hit.type === 'system');
    assert.equal(nodes.length, 12);
    assert.ok(nodes.every(hit => hit.item.group === 'product'));
    assert.ok(nodes.some(hit => hit.id === 'savia-fleet' && /10.*10|100/.test(JSON.stringify(hit.item))));
    assertNoOverlap(nodes, `Savia product at ${width}px`);
    assert.match(scene.caption, /Development\/reviewer hosts are excluded/);
    assert.ok(commands.some(command => command[0] === 'fillText' && /^100 /.test(command[1])));
    commands.length = 0;
    scene.render({ ...frame('landscape', event), landscapeScope:'development' });
    nodes = scene.hits.filter(hit => hit.type === 'system');
    assert.ok(nodes.some(hit => hit.id === 'reviewer-machine'));
    assert.ok(nodes.every(hit => hit.item.group !== 'product'));
    assertNoOverlap(nodes, `Development scope at ${width}px`);
  }
});

for (const [width, height] of [[950, 650], [390, 560]]) {
  test(`all graph modes draw stable paused frames at ${width}×${height}`, () => {
    const { scene, commands } = harness(width, height), { data, event, flowEvent } = fixture();
    scene.setData(data);
    for (const view of ['landscape', 'agents', 'flows', 'infrastructure']) {
      const state = frame(view, view === 'flows' ? flowEvent : event);
      scene.render(state); commands.length = 0;
      scene.render(state); const first = JSON.stringify(commands); commands.length = 0;
      scene.render(state);
      assert.equal(JSON.stringify(commands), first, `${view} must remain still while paused`);
      assert.equal(packets(commands).length, 0, `${view} must never create a paused packet`);
      assert.ok(scene.hits.some(hit => hit.rect), `${view} needs inspectable nodes`);
    }
  });
}

test('existing or inferred landscape links create no ambient packets', () => {
  const { scene, commands } = harness(), { data, event } = fixture(); scene.setData(data);
  scene.render(frame('landscape', event, true));
  assert.equal(packets(commands).length, 0, 'an inferred link with evidence does not establish a transfer');
  commands.length = 0;
  scene.render(frame('landscape', { ...event, id: 'event:reference', references: [] }, true));
  assert.equal(packets(commands).length, 1, 'only the selected recorded reference gets a signal');
  commands.length = 0;
  scene.render(frame('landscape', { ...event, id: 'event:unrelated' }, true));
  assert.equal(packets(commands).length, 0, 'an unrelated event cannot animate previously active edges');
});

test('a spawn packet follows the current event once and stops when paused', () => {
  const { scene, commands } = harness(), { data, event } = fixture(); scene.setData(data);
  scene.render(frame('agents', event, true, 0.2)); const early = packets(commands); commands.length = 0;
  scene.render(frame('agents', event, true, 0.8)); const late = packets(commands);
  assert.equal(early.length, 1); assert.equal(late.length, 1);
  assert.notDeepEqual(early[0], late[0], 'event progress must advance the packet along its actual edge');
  commands.length = 0; scene.render(frame('agents', event, false, 0.8)); assert.equal(packets(commands).length, 0);
  commands.length = 0; scene.render(frame('agents', { ...event, id: 'event:unrelated' }, true)); assert.equal(packets(commands).length, 0);
});

test('FLUJO handoffs animate exact recorded graph edges; declarations remain still', () => {
  const { scene, commands } = harness(), { data, flowEvent } = fixture(); scene.setData(data);
  scene.render(frame('flows', flowEvent, true)); assert.equal(packets(commands).length, 1);
  commands.length = 0; scene.render(frame('flows', { ...flowEvent, id: 'event:message', kind: 'message', metadata: { flowId: 'flow:snapshot' } }, true));
  assert.equal(packets(commands).length, 0); assert.match(scene.caption, /no recorded node execution marker/);
});

test('sources first recorded later cannot become earlier shared-reference traffic', () => {
  const { scene } = harness(), { data, event } = fixture();
  const ref = 'https://github.com/test/repo/pull/1';
  data.events.push({ ...event, id: 'event:later', source: 'flujo', timestamp: LATER, references: [ref] });
  scene.setData(data); scene.render(frame('landscape', { ...event, id: 'event:early', references: [ref] }, true));
  assert.ok(!scene.hits.some(hit => hit.id === 'reference:event:early:flujo'), 'future cross-source evidence must not leak backward');
  assert.ok(scene.hits.some(hit => hit.id === 'reference:event:early:github'), 'the actual explicit GitHub reference remains inspectable');
});

test('machine evidence selects its page; provider controls retain access to every container', () => {
  const { scene } = harness(390, 560), { data, machineEvents } = fixture(); scene.setData(data);
  scene.render(frame('infrastructure', machineEvents[7]));
  assert.ok(scene.hits.some(hit => hit.type === 'machine' && hit.id === 'docker:7'));
  assert.equal(scene.counts.machines, 8); assert.equal(scene.counts.visibleMachines, 2);
  assert.equal(scene.infraPages.get('local'), 3);
  const next = scene.controls[1]; assert.ok(next); next.action(); scene.render(scene.lastState);
  assert.ok(scene.hits.some(hit => hit.type === 'machine' && hit.id === 'docker:0'));
});

test('node hit testing remains correct after fit and zoom', () => {
  const { scene } = harness(), { data, event } = fixture(); scene.setData(data); scene.render(frame('agents', event)); scene.fitView(); scene.zoomBy(1.2);
  const target = scene.hits.find(hit => hit.type === 'session' && hit.id === 'codex:child');
  const x = (target.rect.x + target.rect.w / 2) * scene.camera.scale + scene.camera.x;
  const y = (target.rect.y + target.rect.h / 2) * scene.camera.scale + scene.camera.y;
  const hit = scene.hitTest(x, y); assert.equal(hit.type, 'session'); assert.equal(hit.id, 'codex:child');
});

test('later snapshots stay dim and create no earlier execution packets', () => {
  const { scene, commands } = harness(), { data, flowEvent } = fixture();
  data.topology.flows[0].availableFrom = LATER;
  scene.setData(data); scene.render(frame('flows', flowEvent, true));
  assert.equal(packets(commands).length, 0);
  assert.match(scene.caption, /after the current playhead/);
  assert.ok(commands.some(command => command[0] === 'fillText' && command[1] === 'FLUJO · GRAPH CAPTURED LATER'));
  assert.ok(commands.some(command => command[0] === 'property' && command[1] === 'globalAlpha' && command[2] === 0.38), 'future node cards must be visibly dimmed');
});

test('runtime logs cannot overwrite the last authoritative machine lifecycle', () => {
  const { scene, commands } = harness(), { data } = fixture();
  const stoppedAt = '2026-10-01T15:05:00.000Z', loggedAt = '2026-10-01T15:10:00.000Z';
  data.infrastructure.machines[0].state = 'exited';
  data.events.push({ id: 'event:stop', source: 'infrastructure', timestamp: stoppedAt, metadata: { machineId: 'docker:0', lifecycle: 'stop' } });
  const log = { id: 'event:log', source: 'infrastructure', timestamp: loggedAt, metadata: { machineId: 'docker:0', lifecycle: 'log' } };
  data.events.push(log); scene.setData(data);
  scene.render({ ...frame('infrastructure', log), now: Date.parse(loggedAt) });
  assert.ok(commands.some(command => command[0] === 'fillText' && command[1] === 'RECORDED STOP'));
  assert.ok(!commands.some(command => command[0] === 'fillText' && command[1] === 'RECORDED LOG'));
  assert.ok(!commands.some(command => command[0] === 'fillText' && command[1] === 'OBSERVED EXITED'), 'current snapshot must not leak into earlier history');
  commands.length = 0; scene.render({ ...frame('infrastructure', log), now: Date.parse(LATER) });
  assert.ok(commands.some(command => command[0] === 'fillText' && command[1] === 'OBSERVED EXITED'), 'current observation becomes valid only when its timestamp is reached');
});

test('forwarded FLUJO execution highlights the actual child while preserving the observed parent context', () => {
  const { scene } = harness(), { data, flowEvent } = fixture(); scene.setData(data); scene.render(frame('agents', flowEvent));
  const child = data.topology.sessions.find(session => session.id === 'flujo:child');
  assert.equal(scene._sessionMatches(child), true);
  assert.ok(scene.hits.some(hit => hit.type === 'session' && hit.id === 'flujo:child'));
});

test('all-reference checkbox reveals context edges without inventing packets', () => {
  const { scene, commands } = harness(), { data, event } = fixture(); scene.setData(data);
  scene.render({ ...frame('landscape', event, true), allLinks: false });
  assert.ok(!scene.hits.some(hit => hit.id === 'shared:codex:github'));
  commands.length = 0; scene.render({ ...frame('landscape', event, true), allLinks: true });
  assert.ok(scene.hits.some(hit => hit.id === 'shared:codex:github'));
  assert.equal(packets(commands).length, 0, 'revealing a static reference never creates an event pulse');
});

test('CI landscape nodes follow infrastructure and Codex source coverage aliases', () => {
  const { scene } = harness(), { data, event } = fixture(); scene.setData(data);
  scene.render({ ...frame('landscape', event), sourceFilter: ['codex', 'infrastructure', 'github', 'flujo'] });
  assert.equal(scene._allowed({ id: 'local-ci', source: 'ci' }), true);
  scene.render({ ...frame('landscape', event), sourceFilter: ['infrastructure'] });
  assert.equal(scene._allowed({ id: 'modal-ci', source: 'ci' }), true);
  scene.render({ ...frame('landscape', event), sourceFilter: ['slack'] });
  assert.equal(scene._allowed({ id: 'local-ci', source: 'ci' }), false);
});

for (const [width, height] of [[950, 389], [390, 389]]) {
  test(`a newly selected recorded flow node follows into view at ${width}×${height}`, () => {
    const { scene, commands } = harness(width, height), { data, flowEvent } = fixture(); scene.setData(data);
    scene.render(frame('flows', flowEvent, false));
    const visible = (id = 'reviewer') => { const target = scene.hits.find(hit => hit.type === 'flowNode' && hit.id === id).rect; return { left: target.x * scene.camera.scale + scene.camera.x, top: target.y * scene.camera.scale + scene.camera.y, right: (target.x + target.w) * scene.camera.scale + scene.camera.x, bottom: (target.y + target.h) * scene.camera.scale + scene.camera.y }; };
    const initial = visible(); assert.ok(initial.left >= 24 && initial.right <= width - 24); assert.ok(initial.top >= 24 && initial.bottom <= height - 88);
    commands.length = 0; scene.render(scene.lastState); const first = JSON.stringify(commands); commands.length = 0; scene.render(scene.lastState);
    assert.equal(JSON.stringify(commands), first, 'automatic follow must settle into deterministic paused frames');
    scene.camera.x += 1200; scene.camera.y += 1200; const manual = { ...scene.camera }; scene.render(scene.lastState);
    assert.deepEqual({ ...scene.camera }, manual, 'manual same-event pan must not be overridden by follow');
    scene.render(frame('flows', { ...flowEvent, id: 'event:same-node-message' }, true));
    assert.deepEqual({ ...scene.camera }, manual, 'consecutive same-node events cannot jerk the camera back from manual pan');
    scene.render(frame('flows', { ...flowEvent, id: 'event:enter-coordinator', kind: 'node_enter', metadata: { ...flowEvent.metadata, eventType: 'node:enter', nodeId: 'coordinator', toNodeId: null } }, true));
    const next = visible('coordinator'); assert.ok(next.left >= 24 && next.right <= width - 24); assert.ok(next.top >= 24 && next.bottom <= height - 88);
    scene.fitView(); const fitted = { ...scene.camera }; scene.render(scene.lastState); assert.deepEqual({ ...scene.camera }, fitted, 'explicit Fit must remain available for the same event');
  });
}

test('every landscape component is accessible without panning in compact desktop cinema', () => {
  for (const height of [389, 460, 650]) {
    const { scene } = harness(950, height), { data, event } = fixture();
    data.landscape.nodes = ['slack', 'docs', 'codex', 'flujo', 'codex-team', 'flujo-team', 'github', 'local-ci', 'modal-ci'].map(id => ({ id, label: id, source: id.includes('ci') ? 'ci' : id.split('-')[0], firstTimestamp: TIME }));
    scene.setData(data); scene.render(frame('landscape', event));
    const components = scene.hits.filter(hit => hit.type === 'system'); assert.equal(components.length, 9);
    for (const component of components) {
      const r = component.rect;
      assert.ok(r.x >= 0 && r.x + r.w <= 950, `${component.id} must be horizontally visible`);
      assert.ok(r.y >= 0 && r.y + r.h <= height - 82, `${component.id} must remain above the playback HUD at ${height}px`);
      for (const other of components) {
        if (component === other) continue;
        const q = other.rect, overlaps = r.x < q.x + q.w && r.x + r.w > q.x && r.y < q.y + q.h && r.y + r.h > q.y;
        assert.equal(overlaps, false, `${component.id} must not obstruct ${other.id}`);
      }
    }
  }
});

test('the actual ten-source landscape retains separate non-overlapping machine and CI components', () => {
  // Match builder order: infrastructure is the sixth source, followed by derived team/CI nodes.
  const ids = ['github', 'slack', 'codex', 'flujo', 'docs', 'infrastructure', 'codex-team', 'flujo-team', 'local-ci', 'modal-ci'];
  for (const [width, height] of [[950, 389], [950, 460], [650, 460], [390, 560]]) {
    const { scene } = harness(width, height), { data, event } = fixture();
    data.landscape.nodes = ids.map(id => ({ id, label: id, source: id.includes('ci') ? 'ci' : id.split('-')[0], firstTimestamp: id.includes('ci') ? LATER : TIME }));
    scene.setData(data); scene.render(frame('landscape', event));
    const components = scene.hits.filter(hit => hit.type === 'system'); assert.equal(components.length, 10);
    for (const component of components) {
      const r = component.rect; assert.ok(r.x >= 0 && r.x + r.w <= width, `${component.id} is horizontally accessible at ${width}px`);
      if (width >= 600) assert.ok(r.y >= 0 && r.y + r.h <= height - 82, `${component.id} stays above cinema HUD`);
      for (const other of components) {
        if (component === other) continue;
        const q = other.rect;
        assert.equal(r.x < q.x + q.w && r.x + r.w > q.x && r.y < q.y + q.h && r.y + r.h > q.y, false, `${component.id} must not overlap ${other.id}`);
      }
    }
    const machines = components.find(hit => hit.id === 'infrastructure'), ci = components.find(hit => hit.id === 'local-ci');
    assert.notDeepEqual(machines.rect, ci.rect); assert.equal(machines.item.firstTimestamp, TIME); assert.equal(ci.item.firstTimestamp, LATER);
  }
});

test('flow fallback retains an attributed snapshot through unrelated source events', () => {
  const { scene } = harness(), { data, flowEvent } = fixture();
  data.topology.flows[0].flowDefinitionId = 'definition:release';
  data.topology.flows.push({ ...data.topology.flows[0], id: 'flow:unrelated', flowDefinitionId: 'definition:other', label: 'A different graph saved later', availableFrom: LATER });
  scene.setData(data); scene.render(frame('flows', flowEvent)); assert.equal(scene.activeFlowId, 'flow:snapshot');
  scene.render({ ...frame('flows', { id: 'github:unattributed', source: 'github', timestamp: LATER, metadata: {} }), now: Date.parse(LATER) });
  assert.equal(scene.activeFlowId, 'flow:snapshot'); assert.match(scene.flowResolution, /Last attributed snapshot/);
});

test('actual captured flow graphs and machine panels have no card collisions', capturedOptions, t => {
  const data = actualDataset(); t.diagnostic(`Actual capture: ${data.topology.sessions.length} sessions, ${data.topology.flows.length} graph snapshots, ${data.infrastructure.machines.length} machine identities.`);
  assert.ok(data.topology.flows.length >= 10, 'exercise the complete saved graph collection');
  for (const [width, height] of [[950, 460], [650, 460], [390, 560]]) {
    const { scene, commands } = harness(width, height); scene.setData(data);
    for (const flow of data.topology.flows) {
      scene.render({ view: 'flows', flowId: flow.id, now: Date.parse(flow.availableFrom) + 1000, selectedEvent: { id: 'regression:declared', source: 'docs', metadata: {} }, playing: false });
      const nodes = scene.hits.filter(hit => hit.type === 'flowNode'); assert.equal(nodes.length, flow.nodes.length); assertNoOverlap(nodes, `${flow.label} at ${width}px`); commands.length = 0;
    }
    scene.render({ view: 'infrastructure', now: Date.parse(data.events[data.events.length - 1].timestamp), selectedEvent: data.events[data.events.length - 1], playing: false });
    assertNoOverlap(scene.hits.filter(hit => ['machine', 'event'].includes(hit.type)), `machine/build panels at ${width}px`);
  }
});

test('all actual captured agent sessions have stable, non-overlapping chronological slots', capturedOptions, () => {
  const data = actualDataset(); assert.ok(data.topology.sessions.length >= 300);
  for (const [width, height] of [[950, 460], [390, 560]]) {
    const { scene, commands } = harness(width, height); scene.setData(data);
    const events = data.events.filter(event => event.source === 'flujo' && event.metadata?.sessionId).slice(0, 40);
    let previous = null;
    for (const event of events) {
      scene.render({ view: 'agents', now: Date.parse(event.timestamp), selectedEvent: event, playing: true, progress: 0.4 });
      const current = new Map(scene.hits.filter(hit => hit.type === 'session').map(hit => [hit.id, JSON.stringify(hit.rect)]));
      if (previous) for (const [id, box] of current) if (previous.has(id)) assert.equal(box, previous.get(id), `${id} must not move when the next message arrives`);
      assertNoOverlap(scene.hits.filter(hit => hit.type === 'session'), `agent replay at ${width}px`); previous = current; commands.length = 0;
    }
    const complete = [...scene.agentLayouts.values()][0].map;
    assert.equal(complete.size, data.topology.sessions.length, 'the geometry is derived from every captured session, including offscreen context');
    assertNoOverlap([...complete].map(([id, node]) => ({ id, rect: node })), `all ${complete.size} agent slots at ${width}px`);
  }
});

test('actual dated graph evolution retains unchanged node positions and exact child graph attribution', capturedOptions, () => {
  const data = actualDataset(), { scene, commands } = harness(); scene.setData(data);
  const definitions = new Map(); for (const flow of data.topology.flows) { if (!definitions.has(flow.flowDefinitionId)) definitions.set(flow.flowDefinitionId, []); definitions.get(flow.flowDefinitionId).push(flow); }
  let shared = 0;
  for (const versions of definitions.values()) {
    versions.sort((a, b) => Date.parse(a.availableFrom) - Date.parse(b.availableFrom)); let previous = null;
    for (const flow of versions) {
      scene.render({ view: 'flows', flowId: flow.id, now: Date.parse(flow.availableFrom) + 1000, selectedEvent: { id: 'regression:version', source: 'docs', metadata: {} }, playing: false });
      const current = new Map(scene.hits.filter(hit => hit.type === 'flowNode').map(hit => [hit.id, { original: flow.nodes.find(node => node.id === hit.id), rect: JSON.stringify(hit.rect) }]));
      if (previous) for (const [id, node] of current) { const old = previous.get(id); if (old && old.original.x === node.original.x && old.original.y === node.original.y) { assert.equal(node.rect, old.rect, `${id} must not jump on a saved version change`); shared++; } }
      previous = current; commands.length = 0;
    }
  }
  assert.ok(shared >= 10, 'exercise unchanged nodes across actual historical snapshots');
  const child = data.events.find(event => event.metadata?.executingSessionId && event.metadata.executingSessionId !== event.metadata.sessionId && data.topology.flows.some(flow => flow.id === event.metadata.flowId && flow.nodes.some(node => node.id === event.metadata.nodeId)));
  assert.ok(child, 'exercise an actual forwarded child execution record');
  scene.render({ view: 'flows', now: Date.parse(child.timestamp), selectedEvent: child, playing: false }); assert.equal(scene.activeFlowId, child.metadata.flowId);
  scene.render({ view: 'flows', now: Date.parse(data.events[data.events.length - 1].timestamp), selectedEvent: { id: 'github:context-free', source: 'github', metadata: {} }, playing: false });
  assert.equal(scene.activeFlowId, child.metadata.flowId, 'unattributed events cannot flip a child graph back to a globally newer parent graph');
});

test('actual forwarded child messages retain the parent camera context in the agent view', capturedOptions, () => {
  const data = actualDataset(), { scene } = harness(950, 460); scene.setData(data);
  const child = data.events.find(event => event.metadata?.executingSessionId && event.metadata.executingSessionId !== event.metadata.sessionId);
  assert.ok(child); const observedId = child.metadata.observedInSessionId || child.metadata.sessionId;
  const parent = data.events.find(event => event.metadata?.sessionId === observedId && (!event.metadata.executingSessionId || event.metadata.executingSessionId === observedId));
  assert.ok(parent); scene.render({ view: 'agents', now: Date.parse(parent.timestamp), selectedEvent: parent, playing: false });
  const card = scene.hits.find(hit => hit.type === 'session' && hit.id === observedId); assert.ok(card);
  assert.ok(card.rect.y * scene.camera.scale + scene.camera.y >= 24);
  assert.ok((card.rect.y + card.rect.h) * scene.camera.scale + scene.camera.y <= 460 - 88);
  const camera = { ...scene.camera }; scene.render({ view: 'agents', now: Date.parse(child.timestamp), selectedEvent: child, playing: true, progress: 0.4 });
  assert.deepEqual({ ...scene.camera }, camera, 'forwarded execution changes the evidence highlight, not the parent viewport');
  assert.ok(scene.hits.some(hit => hit.type === 'session' && hit.id === child.metadata.executingSessionId), 'the actual executing child remains separately inspectable');
});
