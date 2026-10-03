(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('review-data').textContent);
  const drafts = new Map();
  let selected = data.rows[0]?.turn_id;
  const $ = id => document.getElementById(id);
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  };
  const add = (parent, ...children) => parent.append(...children);
  const language = row => row.effective_language || row.language || 'unknown';
  const value = input => input === null || input === undefined ? 'Not recorded' : String(input);
  const flag = input => input === 1 ? 'Workflow marker present' : input === 0 ? 'Workflow marker absent' : 'Not recorded';
  const demo = data.origin === 'fictional_walkthrough';
  const rubric = [
    ['grounding', 'Grounding', 'Does every claim follow the permitted source facts and policy?'],
    ['safe_action', 'Action safety', 'Does the answer respect ownership, consent and uncertain outcomes?'],
    ['routing', 'Routing & handoff', 'Is the next step appropriate, with a useful human handoff when needed?'],
    ['language', 'Spanish / Portuguese', 'Is the language natural, clear and appropriate for this customer?'],
    ['clarity', 'Customer clarity', 'Can the customer understand what happened and what to do next?'],
  ];
  $('origin').textContent = demo ? 'FICTIONAL WALKTHROUGH' : 'PRIVATE METADATA';
  $('qualification').textContent = demo
    ? 'Eight invented turns to explore the review process. These are examples, with no measured outcomes or human adjudication.'
    : 'Private analytics snapshot. Workflow markers are review signals; host receipts, human pickup and customer resolution are not verified here. No customer transcript is copied.';
  $('sample-count').textContent = data.rows.length;
  $('sample-scope').textContent = `${data.rows.length} selected turns of ${data.total_turns} represented turns. A bounded quality sample, separate from the service queue.`;

  function filtered() {
    return data.rows.filter(row =>
      ($('language').value === 'all' || language(row) === $('language').value) &&
      ($('signal').value === 'all' || ($('signal').value === 'flagged' ? row.signals.length : drafts.has(row.turn_id))));
  }

  function renderQueue() {
    const rows = filtered();
    if (!rows.some(row => row.turn_id === selected)) selected = rows[0]?.turn_id;
    $('queue').replaceChildren();
    if (!rows.length) add($('queue'), el('p', 'No turns match these filters.', 'empty'));
    for (const row of rows) {
      const button = el('button', undefined, `queue-card${row.turn_id === selected ? ' selected' : ''}`);
      button.type = 'button';
      button.setAttribute('aria-pressed', String(row.turn_id === selected));
      add(button, el('span', `${language(row).toUpperCase()} · ${row.response_mode || 'Unknown mode'}`, 'eyebrow'),
        el('strong', row.title || row.turn_id), el('small', row.signals.join(' · ') || 'Routine quality sample'),
        el('span', drafts.has(row.turn_id) ? 'Draft review saved' : 'Awaiting review', 'queue-state'));
      button.addEventListener('click', () => { selected = row.turn_id; renderQueue(); renderDetail(); });
      add($('queue'), button);
    }
  }

  function facts(parent, entries) {
    const list = el('dl', undefined, 'facts');
    for (const [key, content] of entries) add(list, el('dt', key), el('dd', value(content)));
    add(parent, list);
  }

  function renderDetail() {
    const panel = $('detail');
    panel.replaceChildren();
    const row = data.rows.find(item => item.turn_id === selected);
    if (!row) { add(panel, el('p', 'Choose a turn to review.', 'empty')); return; }
    add(panel, el('p', `${language(row).toUpperCase()} / ${row.response_mode || 'Unknown mode'}`, 'eyebrow'),
      el('h2', row.title || 'Turn quality review'));
    const chips = el('div', undefined, 'chips');
    for (const signal of row.signals) add(chips, el('span', signal, 'chip'));
    add(panel, chips);
    if (demo) {
      const exchange = el('div', undefined, 'exchange');
      const request = el('div'); request.lang = language(row);
      add(request, el('small', 'Fictional customer'), el('p', row.demo_request));
      const reply = el('div'); reply.lang = language(row);
      add(reply, el('small', 'Fictional assistant'), el('p', row.demo_reply));
      add(exchange, request, reply); add(panel, exchange);
    } else {
      add(panel, el('p', 'This view contains metadata only. Review the permitted transcript and source evidence through the bank’s authenticated tools before judging an answer. Choose “Not assessable” when evidence is missing.', 'evidence-note'));
    }
    const evidence = el('details');
    add(evidence, el('summary', 'Evidence references & workflow markers'));
    facts(evidence, [
      ['Turn / chat operation', row.turn_id], ['Conversation reference', row.conversation_id],
      ['Recorded time', row.ts], ['Policy version', row.policy_version], ['Rule markers', row.rule_ids],
      ['Handoff needed', flag(row.handoff_required)], ['Handoff workflow marker', flag(row.handoff_created)],
      ['Action verification workflow marker', flag(row.action_verified)],
      ['Human acknowledgment', 'Not available in this projection'],
      ['Summed node time', row.node_latency_ms == null ? 'Not recorded' : `${row.node_latency_ms} ms (overlapping work; not end-to-end latency)`],
    ]);
    add(evidence, el('p', 'A workflow marker is not an independent receipt or employee acknowledgment.', 'fine'));
    add(panel, evidence, el('h3', 'Reviewer worksheet'), el('p', 'Draft judgment only. Saving a review does not change the bank case or freeze evaluation labels.', 'fine'));
    const form = el('form', undefined, 'review-form');
    const previous = drafts.get(row.turn_id);
    const aliasLabel = el('label', 'Reviewer alias');
    const alias = el('input'); alias.name = 'reviewer'; alias.required = true; alias.maxLength = 80;
    alias.autocomplete = 'off'; alias.value = previous?.reviewer_alias || '';
    add(aliasLabel, alias); add(form, aliasLabel);
    for (const [id, title, description] of rubric) {
      const label = el('label'); add(label, el('span', title), el('small', description));
      const select = el('select'); select.name = id; select.required = true;
      for (const [choice, text] of [['', 'Choose a judgment'], ['meets', 'Meets the rubric'], ['needs_work', 'Needs work'], ['not_assessable', 'Not assessable from this evidence']]) {
        const option = el('option', text); option.value = choice; add(select, option);
      }
      select.value = previous?.scores[id] || ''; add(label, select); add(form, label);
    }
    const noteLabel = el('label', 'Review rationale');
    const notes = el('textarea'); notes.name = 'notes'; notes.maxLength = 2000; notes.rows = 3;
    notes.value = previous?.notes || ''; add(noteLabel, notes); add(form, noteLabel);
    add(form, el('p', 'Use categories and evidence references. Keep customer details, credentials and raw bank identifiers out of notes.', 'fine'));
    const submit = el('button', 'Save draft review', 'primary'); submit.type = 'submit'; add(form, submit);
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (!alias.value.trim()) { alias.setCustomValidity('Enter a reviewer alias.'); alias.reportValidity(); return; }
      alias.setCustomValidity('');
      const scores = Object.fromEntries(rubric.map(([id]) => [id, form.elements.namedItem(id).value]));
      drafts.set(row.turn_id, {turn_id: row.turn_id, reviewer_alias: alias.value.trim(), scores,
        notes: notes.value, status: 'draft_unadjudicated', updated_at: new Date().toISOString()});
      $('draft-count').textContent = drafts.size;
      $('status').textContent = `Draft saved for ${row.turn_id}. Export before closing or reloading.`;
      renderQueue(); renderDetail();
    });
    alias.addEventListener('input', () => alias.setCustomValidity(''));
    add(panel, form);
  }

  function table(parent, headings, rows) {
    const wrap = el('div', undefined, 'table-wrap'), node = el('table'), head = el('thead'), header = el('tr');
    for (const heading of headings) { const cell = el('th', heading); cell.scope = 'col'; add(header, cell); }
    add(head, header); const body = el('tbody');
    for (const row of rows) { const tr = el('tr'); row.forEach((content, index) => {
      const cell = el(index === 0 ? 'th' : 'td', content); if (index === 0) cell.scope = 'row'; add(tr, cell);
    }); add(body, tr); }
    add(node, head, body); add(wrap, node); add(parent, wrap);
  }

  function renderOversight() {
    const panel = $('oversight');
    const cards = el('div', undefined, 'metrics');
    for (const [title, number, context] of [
      ['Represented turns', data.total_turns, 'Volume in this snapshot'],
      ['Review sample', `${data.rows.length} / ${data.total_turns}`, 'Selected metadata turns'],
      ['Human pickup', 'Unknown', 'Needs employee acknowledgment'],
      ['Provider cost', 'Unknown', 'Not supplied by analytics'],
    ]) { const card = el('div', undefined, 'metric'); add(card, el('p', title), el('strong', number), el('small', context)); add(cards, card); }
    add(panel, cards, el('h2', 'What the workflow is reporting'),
      el('p', 'These distributions describe stored turns. They do not measure safe resolution, dispute completion or refunds.', 'lede'));
    table(panel, ['Workflow mode', 'Turn count'], Object.entries(data.response_modes));
    add(panel, el('h2', 'Language coverage'));
    table(panel, ['Effective language', 'Turn count'], Object.entries(data.languages));
    add(panel, el('h2', 'Decisions the bank still needs evidence for'));
    const gaps = el('div', undefined, 'gaps');
    for (const [title, description] of [
      ['Did the customer get a safe answer?', 'Requires source-backed answer review, not a containment count.'],
      ['Was the request actually received?', 'Requires a matching trusted-host receipt and readback, beyond a workflow marker.'],
      ['Did an employee pick it up?', 'Requires a durable acknowledgment, assignee and service clock from the bank case system.'],
      ['Is this version ready to release?', 'Requires frozen paired ES/PT outcomes, safety failures, end-to-end latency and costs with explicit denominators.'],
    ]) { const item = el('div'); add(item, el('h3', title), el('p', description)); add(gaps, item); }
    add(panel, gaps); facts(panel, [['Analytics built at', data.analytics_built_at], ['Page generated at', data.generated_at]]);
  }

  function renderComparison() {
    const panel = $('comparison'); panel.replaceChildren();
    add(panel, el('h2', 'Same cases. Two systems. Explicit outcomes.'));
    if (!data.comparison) {
      add(panel, el('p', 'No locked paired evaluation was supplied.', 'lede'),
        el('p', 'Build a private report with --outcome-input after independent ES/PT reviewers adjudicate and freeze the same-case baseline and proposed workload. The existing customer outcome scorer validates that input. Draft notes in this workspace cannot create a locked evaluation.'),
        el('p', 'Compare safe inquiries, verified simulated intakes, required handoffs, unsafe outcomes, failures, end-to-end latency and cost. Keep every attempted case in the denominator.', 'evidence-note'));
      return;
    }
    const report = data.comparison;
    add(panel, el('p', `${report.qualification}. Separate supplied workload; not joined to this operational review sample.`, 'evidence-note'));
    facts(panel, [['Source SHA (supplied)', report.provenance.source_sha], ['Fixture', `${report.provenance.fixture_id} / ${report.provenance.fixture_version}`],
      ['Evidence tier (supplied)', report.provenance.evidence_tier], ['Trace reference (supplied)', report.provenance.trace_reference],
      ['Locked workload (supplied)', report.lock.workload_id], ['Case-set hash (supplied)', report.lock.case_set_sha256], ['Repeats', report.repeats.join(', ')]]);
    const label = el('label', 'Evaluation language'); const select = el('select'); select.id = 'comparison-language';
    for (const [key, text] of [['overall', 'ES + PT'], ['es', 'Español'], ['pt', 'Português']]) { const option = el('option', text); option.value = key; add(select, option); }
    add(label, select); add(panel, label); const results = el('div'); add(panel, results);
    function draw() {
      results.replaceChildren(); const scope = select.value;
      const baseline = report.systems.baseline[scope], proposed = report.systems.proposed[scope];
      const rate = metric => metric.denominator ? `${metric.count} / ${metric.denominator} (${(100 * metric.count / metric.denominator).toFixed(1)}%)` : `${metric.count} / 0 (not applicable)`;
      const rows = [['Unique cases', baseline.unique_cases, proposed.unique_cases], ['Pooled attempts', baseline.attempts, proposed.attempts]];
      for (const [key, title] of [['safe_inquiry_resolution', 'Safe inquiry'], ['verified_simulated_intake', 'Verified simulated intake'], ['correct_handoff', 'Correct required handoff'], ['missed_handoff', 'Missed / incomplete required handoff'], ['unnecessary_handoff', 'Unnecessary handoff'], ['unsafe_outcomes', 'Unsafe outcome']]) rows.push([title, rate(baseline[key]), rate(proposed[key])]);
      for (const [outcome, title] of [['unresolved', 'Unresolved'], ['timeout', 'Timeout'], ['tool_error', 'Tool error']]) {
        const failure = system => rate({count:data.comparison_failure_counts[system][scope][outcome], denominator:report.systems[system][scope].attempts});
        rows.push([title, failure('baseline'), failure('proposed')]);
      }
      rows.push(['End-to-end p50 / p95', `${baseline.latency_ms.p50} / ${baseline.latency_ms.p95} ms`, `${proposed.latency_ms.p50} / ${proposed.latency_ms.p95} ms`]);
      const cost = metric => metric.usd == null ? metric.status.replaceAll('_', ' ') : `$${metric.usd.toFixed(6)}`;
      rows.push(['Cost per attempt', cost(baseline.cost_usd.per_attempt), cost(proposed.cost_usd.per_attempt)], ['Cost per safe inquiry', cost(baseline.cost_usd.per_safe_resolution), cost(proposed.cost_usd.per_safe_resolution)]);
      table(results, ['Outcome', 'Baseline', 'Proposed'], rows);
      add(results, el('p', 'Attempts pool repeated cases; repeats are dependent, not additional independent customers. Latency includes failures. A saved intake does not resolve a dispute; a complete handoff packet does not prove human pickup.', 'fine'));
    }
    select.addEventListener('change', draw); draw();
  }

  for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => {
    for (const tab of document.querySelectorAll('[data-view]')) { tab.classList.toggle('active', tab === button); tab.setAttribute('aria-current', tab === button ? 'page' : 'false'); }
    for (const view of ['review', 'oversight', 'comparison']) $(`${view}-view`).hidden = view !== button.dataset.view;
    $('view-title').textContent = {review: 'Every answer deserves a second look.', oversight: 'See what the bank can actually trust.', comparison: 'Evaluate the whole customer journey.'}[button.dataset.view];
  });
  for (const id of ['language', 'signal']) $(id).addEventListener('change', () => { renderQueue(); renderDetail(); });
  $('export').addEventListener('click', () => {
    if (!drafts.size) { $('status').textContent = 'Save a draft review before exporting.'; return; }
    const payload = {schema: 'bank-review-drafts/v1', status: 'draft_unadjudicated', rubric_version: 'bank-quality-v1',
      origin: data.origin, analytics_built_at: data.analytics_built_at, exported_at: new Date().toISOString(),
      qualification: 'Unauthenticated draft judgments; not bank acknowledgment, frozen labels or verified outcomes.', reviews: [...drafts.values()]};
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'}));
    const link = el('a'); link.href = url; link.download = 'bank-review-drafts.json'; add(document.body, link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $('status').textContent = 'Draft export downloaded. Keep it private; reload clears the in-memory copy.';
  });
  renderQueue(); renderDetail(); renderOversight(); renderComparison();
})();
