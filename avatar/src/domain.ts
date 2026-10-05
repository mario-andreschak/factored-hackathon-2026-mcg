export { classifyMood } from '../server/mood.mjs';
import { classifyMood } from '../server/mood.mjs';
import { getMessages } from './locale';
import type { Locale } from './locale';
export type AvatarId = 'moss' | 'orbit' | 'spark';
export type Phase = 'idle' | 'listening' | 'thinking' | 'speaking';
export type Intent = 'inquiry' | 'dispute' | 'human' | 'other';
export interface Mood { avatar: AvatarId; intent: Intent; reason: string; }
export interface Transcript { id: string; role: 'user' | 'assistant'; text: string; avatar?: AvatarId; }
export interface AvatarConfig {
  voiceAvailable: boolean; backendAvailable: boolean; saviaUrl: string;
  mode: 'demo' | 'connected'; realtimeModel: string;
  voiceProvider?: 'gemini-live' | 'openai-realtime' | 'openrouter-native' | 'openrouter' | 'personaplex' | 'none';
  geminiModel?: string;
  voiceAvatar?: AvatarId;
  initialVoiceAvailable?: boolean;
  backgroundAsrAvailable?: boolean;
  nativeReadBridgeAvailable?: boolean;
}
export const AVATARS = getMessages('es').characters;

export function sceneForIntent(intent: Intent): number {
  return ({ inquiry: 0, dispute: 6, human: 1, other: 0 })[intent];
}

export function demoReply(text: string, avatar: AvatarId, locale: Locale = 'es'): string {
  const copy = getMessages(locale), character = copy.characters[avatar];
  const { intent } = classifyMood(text);
  if (intent === 'human') return copy.game.humanReply;
  if (intent === 'dispute' || intent === 'inquiry') return character.bankReply;
  if (/\b(hi|hello|hey|hola|ola|oi)\b/i.test(text.normalize('NFD').replace(/\p{Diacritic}/gu, ''))) return character.hello;
  return character.reply;
}
