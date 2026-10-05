/** Capture milestones contain timing only: no audio, captions, account data or keys. */
export function voiceMilestone(event: 'task-start' | 'task-complete' | 'voice-start' | 'voice-audio' | 'voice-complete' | 'voice-interrupted') {
  window.dispatchEvent(new CustomEvent('savia:voice-milestone', { detail: { event, at: performance.now() } }));
}
