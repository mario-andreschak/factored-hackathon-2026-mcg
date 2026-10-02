export function classifyMood(text: string): {
  avatar: 'moss' | 'orbit' | 'spark';
  intent: 'inquiry' | 'dispute' | 'human' | 'other';
  reason: string;
};
