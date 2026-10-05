/** Finite first-utterance replay. Owns no microphone, provider or audio output. */
export const INITIAL_REPLAY_RATE = 24_000;
export const INITIAL_FRAME_SAMPLES = 1_920;
export const INITIAL_FRAME_MS = 80;
export const MAX_INITIAL_FRAME_GAP_MS = 480;
export const MAX_INITIAL_SAMPLES = INITIAL_REPLAY_RATE * 12;
export const MAX_LIVE_PREROLL_SAMPLES = INITIAL_REPLAY_RATE / 5;

export type InitialReplayState = 'pending' | 'replaying' | 'live' | 'cancelled';
export type InitialReplayError = 'clock-invalid' | 'timer-stalled' | 'scheduler-failed' | 'send-failed' | 'send-rejected' | 'invalid-preroll';

/** Monotonic milliseconds and asynchronous timers must come from the owner. */
export interface ReplayClock<Handle = unknown> {
  now(): number;
  schedule(callback: () => void, delayMs: number): Handle;
  cancel(handle: Handle): void;
}

export interface InitialReplayFrame {
  index: number;
  sampleOffset: number;
  capturedSamples: number;
  paddedSamples: number;
  sentAtMs: number;
}

export interface InitialReplayHandoff {
  reason: 'complete' | 'new-speech';
  /** Independent owned copy of the most recent <=200 ms, already at24 kHz. */
  preroll: Float32Array;
  sentFrames: number;
  capturedSamplesSent: number;
}

export interface InitialReplayOptions<Handle = unknown> {
  clock: ReplayClock<Handle>;
  /** Synchronous acceptance; caller encodes PCM16 and sends its native packet. */
  sendFrame(frame: Float32Array, info: InitialReplayFrame): boolean;
  onLive(handoff: InitialReplayHandoff): void;
  onError?(code: InitialReplayError): void;
}

/**
 * Copy one finite24 kHz mono capture; start sends the first80 ms immediately.
 * Later frames use normal1x pacing, including a final80 ms drain before LIVE.
 * A late timer sends at most one frame; it never accelerates to catch up.
 * A gap greater than480 ms fails closed before any further old frame is sent.
 *
 * The owner must gate ordinary live microphone sends during replay. On fresh
 * speech, call handoffToLive with its bounded pre-roll and perform the native
 * interrupt separately. Never also send those same pre-roll samples as live
 * input. Cancel on mute, disconnect or session change. Emitted frame ownership
 * passes to sendFrame; caller-owned capture is not erased by this object.
 */
export class InitialPcmReplay<Handle = unknown> {
  private capture: Float32Array | undefined;
  private phase: InitialReplayState = 'pending';
  private epoch = 0;
  private timerTicket = 0;
  private armed = false;
  private handle: Handle | undefined;
  private cursor = 0;
  private frames = 0;
  private nextDue = 0;
  private previousNow = -Infinity;
  private lastSentAt: number | undefined;
  private readonly total: number;

  constructor(captured: Float32Array, private readonly options: InitialReplayOptions<Handle>) {
    if (!(captured instanceof Float32Array) || !captured.length || captured.length > MAX_INITIAL_SAMPLES) {
      throw new RangeError('Initial capture must be nonempty and no longer than12 seconds.');
    }
    for (const sample of captured) if (!Number.isFinite(sample)) throw new RangeError('Initial PCM must be finite.');
    this.total = captured.length;
    this.capture = new Float32Array(captured);
  }

  get state(): InitialReplayState { return this.phase; }
  get remainingSamples(): number { return this.capture ? this.total - this.cursor : 0; }
  get retainedSamples(): number { return this.capture?.length ?? 0; }

  start(): boolean {
    if (this.phase !== 'pending') return false;
    this.phase = 'replaying';
    const epoch = ++this.epoch;
    const now = this.readNow();
    if (now === undefined) return false;
    this.nextDue = now;
    this.tick(epoch);
    return this.state !== 'cancelled';
  }

  /** One-way handoff; new speech abandons every unsent original sample. */
  handoffToLive(preroll: Float32Array): boolean {
    if (this.phase === 'live' || this.phase === 'cancelled') return false;
    if (!(preroll instanceof Float32Array)) { this.fail('invalid-preroll'); return false; }
    const tail = preroll.subarray(Math.max(0, preroll.length - MAX_LIVE_PREROLL_SAMPLES));
    for (const sample of tail) if (!Number.isFinite(sample)) { this.fail('invalid-preroll'); return false; }
    this.enterLive('new-speech', new Float32Array(tail));
    return true;
  }

  cancel(): boolean {
    if (this.phase === 'live' || this.phase === 'cancelled') return false;
    this.phase = 'cancelled';
    this.invalidateTimer();
    this.eraseCapture();
    return true;
  }

  private running(epoch: number): boolean { return this.phase === 'replaying' && this.epoch === epoch; }

  private readNow(): number | undefined {
    let now: number;
    try { now = this.options.clock.now(); } catch { this.fail('clock-invalid'); return; }
    if (!Number.isFinite(now) || now < this.previousNow) { this.fail('clock-invalid'); return; }
    this.previousNow = now;
    return now;
  }

  private tick(epoch: number): void {
    if (!this.running(epoch)) return;
    const now = this.readNow();
    if (now === undefined) return;
    if (this.lastSentAt !== undefined && now - this.lastSentAt > MAX_INITIAL_FRAME_GAP_MS) {
      this.fail('timer-stalled'); return;
    }
    if (now < this.nextDue) { this.arm(epoch, this.nextDue - now); return; }
    if (this.cursor >= this.total) { this.enterLive('complete', new Float32Array()); return; }
    const count = Math.min(INITIAL_FRAME_SAMPLES, this.total - this.cursor);
    const frame = new Float32Array(INITIAL_FRAME_SAMPLES);
    frame.set(this.capture!.subarray(this.cursor, this.cursor + count));
    this.capture!.fill(0, this.cursor, this.cursor + count);
    const info: InitialReplayFrame = { index: this.frames++, sampleOffset: this.cursor,
      capturedSamples: count, paddedSamples: INITIAL_FRAME_SAMPLES - count, sentAtMs: now };
    this.cursor += count;
    if (this.cursor === this.total) this.eraseCapture();
    let accepted: boolean;
    try { accepted = this.options.sendFrame(frame, info); }
    catch { if (this.running(epoch)) this.fail('send-failed'); return; }
    // sendFrame can synchronously cancel or hand off. It may not re-arm us.
    if (!this.running(epoch)) return;
    if (accepted !== true) { this.fail('send-rejected'); return; }
    this.lastSentAt = now;
    const afterSend = this.readNow();
    if (afterSend === undefined) return;
    if (afterSend - now > MAX_INITIAL_FRAME_GAP_MS) { this.fail('timer-stalled'); return; }
    this.nextDue = afterSend + INITIAL_FRAME_MS;
    this.arm(epoch, INITIAL_FRAME_MS);
  }

  private arm(epoch: number, delay: number): void {
    const ticket = ++this.timerTicket;
    this.armed = true;
    try {
      this.handle = this.options.clock.schedule(() => {
        if (!this.running(epoch) || ticket !== this.timerTicket) return;
        this.armed = false;
        this.handle = undefined;
        this.tick(epoch);
      }, delay);
    } catch { this.armed = false; this.handle = undefined; this.fail('scheduler-failed'); }
  }

  private invalidateTimer(): void {
    this.epoch++;
    this.timerTicket++;
    if (this.armed) {
      this.armed = false;
      try { this.options.clock.cancel(this.handle as Handle); } catch { /* Epoch still blocks a stale callback. */ }
      this.handle = undefined;
    }
  }

  private eraseCapture(): void { this.capture?.fill(0); this.capture = undefined; }

  private enterLive(reason: InitialReplayHandoff['reason'], preroll: Float32Array): void {
    this.phase = 'live';
    this.invalidateTimer();
    this.eraseCapture();
    this.options.onLive({ reason, preroll, sentFrames: this.frames, capturedSamplesSent: this.cursor });
  }

  private fail(code: InitialReplayError): void { if (this.cancel()) this.options.onError?.(code); }
}
