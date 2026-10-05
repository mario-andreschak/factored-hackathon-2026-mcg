import { useCallback, useEffect, useRef } from 'react';
import type { Locale } from './locale';

export function validInquiryNotification(value: unknown): value is { type: string; case_id: string; event_id: number } {
  if (!value || typeof value !== 'object') return false;
  const item = value as Record<string, unknown>;
  return Object.keys(item).length === 3 && item.type === 'savia:inquiry-update' &&
    typeof item.case_id === 'string' && /^i_[a-f0-9]{32}$/.test(item.case_id) &&
    Number.isSafeInteger(item.event_id) && (item.event_id as number) > 0;
}

interface Options {
  enabled: boolean; locale: Locale; getOwner: () => symbol | null;
  sendResult: (taskId: string, owner: symbol) => boolean; onError: () => void;
}

/** Frame messages contain pointers only. Spoken prose must match a receipt
 * recorded from the authenticated host response, in the same voice session. */
export function useInquiryVoiceUpdates(options: Options) {
  const opts = useRef(options); opts.current = options;
  const epoch = useRef(0), cursors = useRef(new Map<string, number>()), replies = useRef(new Map<string, string>());
  const latest = useRef(new Map<string, number>()), pending = useRef(new Map<string, AbortController>());
  const run = useRef((_caseId: string, _eventId: number) => {});
  const clear = useCallback(() => {
    epoch.current++;
    pending.current.forEach(controller => controller.abort()); pending.current.clear();
    cursors.current.clear(); replies.current.clear(); latest.current.clear();
  }, []);
  const notify = useCallback((caseId: string, eventId: number) => {
    if (!validInquiryNotification({ type: 'savia:inquiry-update', case_id: caseId, event_id: eventId }) || !opts.current.enabled) return;
    const owner = opts.current.getOwner(); if (!owner) return;
    const previous = cursors.current.get(caseId) ?? 0;
    if (eventId <= previous) return;
    if (!latest.current.has(caseId) && latest.current.size >= 32) return;
    latest.current.set(caseId, Math.max(latest.current.get(caseId) ?? 0, eventId));
    if (pending.current.has(caseId)) return;
    const controller = new AbortController(), generation = epoch.current, locale = opts.current.locale;
    pending.current.set(caseId, controller);
    const owns = () => !controller.signal.aborted && generation === epoch.current && opts.current.enabled && opts.current.getOwner() === owner;
    void (async () => {
      const query = new URLSearchParams({ case_id: caseId, after_event_id: String(previous), language: locale });
      const response = await fetch(`/savia/api/assistant/voice-update?${query}`, {
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
      });
      if (!owns()) { await response.body?.cancel(); return; }
      if (response.status === 204) { cursors.current.set(caseId, eventId); return; }
      if (!response.ok) throw new Error('inquiry_update_unavailable');
      const body = await response.json();
      if (!owns()) return;
      if (body.mode !== 'assistant' || body.status !== 'completed' || body.bank_authority !== false ||
          !Number.isSafeInteger(body.event_id) || body.event_id <= previous || typeof body.reply !== 'string' ||
          !body.reply.trim() || body.reply.length > 8000) throw new Error('invalid_inquiry_update');
      // A closed historical inquiry is still visible in Savia, but opening the
      // panel should not announce its old closure as a new conversation result.
      if (previous === 0 && body.inquiry_state === 'informational_resolved') {
        cursors.current.set(caseId, body.event_id); replies.current.set(caseId, body.reply); return;
      }
      // Worker start/completion events can share the same reviewed status copy.
      if (body.reply === replies.current.get(caseId)) { cursors.current.set(caseId, body.event_id); return; }
      const receipt = await fetch('/api/avatar/native-result-receipt', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reply: body.reply, locale }),
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]),
      });
      if (!owns()) { await receipt.body?.cancel(); return; }
      if (!receipt.ok) throw new Error('inquiry_receipt_unavailable');
      const bound = await receipt.json();
      if (!owns()) return;
      if (typeof bound.taskId !== 'string' || !opts.current.sendResult(bound.taskId, owner)) throw new Error('inquiry_voice_unavailable');
      cursors.current.set(caseId, body.event_id); replies.current.set(caseId, body.reply);
    })().catch(() => { if (owns()) opts.current.onError(); }).finally(() => {
      if (pending.current.get(caseId) !== controller) return;
      pending.current.delete(caseId);
      const next = latest.current.get(caseId) ?? 0;
      if (owns() && next > eventId && next > (cursors.current.get(caseId) ?? 0)) run.current(caseId, next);
    });
  }, []);
  run.current = notify;
  useEffect(() => { if (!options.enabled) clear(); }, [options.enabled, clear]);
  useEffect(() => clear, [clear]);
  return { notify, clear };
}
