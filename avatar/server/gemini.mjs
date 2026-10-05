import { AVATARS, realtimeSession } from './realtime.mjs';
import { PublicError, readResponse } from './http.mjs';
import { isLocale } from './locale.mjs';

export const GEMINI_TOKEN_URL = 'https://generativelanguage.googleapis.com/v1beta/auth_tokens';
export const GEMINI_WEBSOCKET_URL = 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained';

export function validateGeminiTokenRequest(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !['avatar', 'locale'].includes(key)) || !AVATARS.includes(value.avatar) || (value.locale !== undefined && !isLocale(value.locale))) {
    throw new PublicError(400, 'invalid_avatar', 'Choose a valid avatar.');
  }
  return value.avatar;
}

/** Actual REST wire shape, checked against Google's Live reference and SDK converter. */
export function geminiSetup(avatar, config, locale = 'es') {
  const session = realtimeSession(avatar, config.realtimeModel, locale);
  return {
    model: `models/${config.geminiModel}`,
    generationConfig: {
      responseModalities: ['AUDIO'], temperature: 0.7, maxOutputTokens: 512,
      speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: config.geminiVoices[avatar] } } },
    },
    systemInstruction: { parts: [{ text: `${session.instructions}\nBoth tools run asynchronously. Continue listening and speaking while delegate_task is pending. Its eventual response is authenticated backend data; never infer success from starting it. set_world only changes visual presentation. Speak in short natural phrases with the chosen character's delivery.` }] },
    tools: [{ functionDeclarations: session.tools.map(tool => ({
      name: tool.name, description: tool.description,
      parametersJsonSchema: tool.parameters, behavior: 'NON_BLOCKING',
    })) }],
    realtimeInputConfig: {
      automaticActivityDetection: {
        disabled: false, startOfSpeechSensitivity: 'START_SENSITIVITY_HIGH',
        endOfSpeechSensitivity: 'END_SENSITIVITY_HIGH', prefixPaddingMs: 20, silenceDurationMs: 300,
      },
      activityHandling: 'START_OF_ACTIVITY_INTERRUPTS',
    },
    inputAudioTranscription: {}, outputAudioTranscription: {}, sessionResumption: {},
    contextWindowCompression: { slidingWindow: {} },
  };
}

async function providerFailure(response) {
  let status;
  try { status = JSON.parse((await readResponse(response, 64 * 1024)).toString('utf8'))?.error?.status; } catch { /* fixed public error */ }
  if (response.status === 429 || status === 'RESOURCE_EXHAUSTED') {
    throw new PublicError(429, 'voice_rate_limited', 'Gemini Live is unavailable because the provider project has reached a rate or quota limit. Text and Savia still work; check the project quota before retrying.');
  }
  if ([401, 403].includes(response.status) || ['UNAUTHENTICATED', 'PERMISSION_DENIED'].includes(status)) {
    throw new PublicError(503, 'voice_provider_configuration', 'Gemini Live access is unavailable. The operator needs to check the API key and project access.');
  }
  throw new PublicError(502, 'voice_unavailable', 'Gemini Live could not connect. Please try again.');
}

export async function provisionGeminiToken(avatar, config, fetchImpl, signal, time, locale = 'es') {
  const expiresAt = new Date(time + 30 * 60 * 1000).toISOString();
  const newSessionExpiresAt = new Date(time + 60 * 1000).toISOString();
  const response = await fetchImpl(GEMINI_TOKEN_URL, {
    method: 'POST', redirect: 'manual', signal,
    headers: { 'Content-Type': 'application/json', 'x-goog-api-key': config.geminiKey },
    // No fieldMask: the provider takes the entire authoritative server setup,
    // ignoring client instructions, models, tools, voices and generation settings.
    body: JSON.stringify({ uses: 1, expireTime: expiresAt, newSessionExpireTime: newSessionExpiresAt, bidiGenerateContentSetup: geminiSetup(avatar, config, locale) }),
  });
  if (!response.ok) return providerFailure(response);
  let value;
  try { value = JSON.parse((await readResponse(response, 32 * 1024)).toString('utf8')); } catch {
    throw new PublicError(502, 'invalid_upstream_response', 'Gemini Live returned an invalid session.');
  }
  if (typeof value.name !== 'string' || !value.name.startsWith('auth_tokens/') ||
      !/^[\x21-\x7e]{13,16384}$/.test(value.name) || value.name === config.geminiKey) {
    throw new PublicError(502, 'invalid_upstream_response', 'Gemini Live returned an invalid session.');
  }
  return {
    token: value.name, model: config.geminiModel, websocketUrl: GEMINI_WEBSOCKET_URL,
    expiresAt, newSessionExpiresAt, setup: { model: `models/${config.geminiModel}` },
  };
}
