/* The chronological player advances at most one record per rendered frame. */
(function (root) {
  'use strict';
  class HistoryReplayEngine {
    constructor(count = 0, holdMs = 850) { this.configure(count, holdMs); }
    configure(count, holdMs = this.holdMs) {
      this.count = Math.max(0, Math.floor(Number(count) || 0));
      this.holdMs = Math.max(100, Number(holdMs) || 850);
      this.index = 0; this.elapsed = 0; this.visited = this.count ? 1 : 0;
      this.finished = !this.count; this.seeks = 0;
      return this.snapshot(false);
    }
    seek(index) {
      this.index = Math.max(0, Math.min(this.count - 1, Math.floor(Number(index) || 0)));
      this.elapsed = 0; this.finished = !this.count; this.seeks++;
      return this.snapshot(true);
    }
    advance(deltaMs, speed = 1) {
      if (this.finished) return this.snapshot(false);
      this.elapsed += Math.max(0, Number(deltaMs) || 0) * Math.max(.1, Number(speed) || 1);
      let changed = false;
      if (this.elapsed >= this.holdMs) {
        if (this.index + 1 < this.count) {
          this.elapsed -= this.holdMs; this.index++; this.visited++; changed = true;
        } else {
          this.elapsed = this.holdMs; this.finished = true;
        }
      }
      return this.snapshot(changed);
    }
    snapshot(changed) {
      return {index:this.index, changed, progress:Math.min(1,this.elapsed / this.holdMs),
        position:this.index * this.holdMs + Math.min(this.elapsed,this.holdMs),
        duration:this.count * this.holdMs, visited:this.visited, seeks:this.seeks,
        finished:this.finished, skippedByPlayback:0};
    }
  }
  root.HistoryReplayEngine = HistoryReplayEngine;
  if (typeof module !== 'undefined' && module.exports) module.exports = HistoryReplayEngine;
})(typeof window === 'undefined' ? globalThis : window);
