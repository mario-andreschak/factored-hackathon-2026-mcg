import type { AvatarId } from './domain';
import { normalizeLocale, type Locale } from './locale';
import { nativeLanguageInstruction } from '../server/locale.mjs';

const spanish = {
  invalidWorld: 'Ese lugar no está disponible.',
  invalidTask: 'La consulta no es válida. Usa una petición más breve.',
  unknownTool: 'Esa función no está disponible.',
  taskFailed: 'La consulta no pudo completarse. Revisa su estado en la ventana de Savia.',
  browserRequired: 'La voz necesita acceso al micrófono en una conexión segura. Puedes usar el teclado del menú de pausa.',
  playbackBlocked: 'Activa el sonido para escuchar la voz.',
  connectionFailed: 'No pudimos conectar la voz. Vuelve a intentarlo.',
  connectionEnded: 'La conexión de voz terminó. Puedes volver a conectarte o usar el teclado.',
  connectionBehind: 'La conexión de voz se retrasó. Vuelve a conectarte para continuar.',
  microphoneDenied: 'No se permitió usar el micrófono. Habilita el acceso y vuelve a conectarte, o usa el teclado del menú de pausa.',
  configurationInvalid: 'La configuración de voz no es válida. Intenta conectarte de nuevo.',
  tokenExpired: 'El permiso de conexión venció. Vuelve a conectarte.',
  setupTimeout: 'La voz no terminó de conectarse. Vuelve a intentarlo.',
  sessionEnding: 'La sesión de voz está terminando. Vuelve a conectarte para continuar.',
  sessionExpired: 'La sesión de voz venció. Vuelve a conectarte para continuar.',
  streamFailed: 'El audio se interrumpió. Vuelve a conectarte para continuar.',
  providerFailed: 'El servicio de voz no pudo completar la petición. Vuelve a intentarlo.',
  providerUnavailable: 'La voz no está disponible en este momento. Puedes usar el teclado.',
  accessRequired: 'No se pudo autorizar la voz. Revisa tu acceso y vuelve a intentarlo.',
  quotaExceeded: 'El servicio de voz alcanzó su límite de uso. Puedes usar el teclado.',
  tooBusy: 'El servicio de voz está ocupado. Espera un momento antes de volver a intentarlo.',
  unsupportedAudio: 'El formato de audio recibido no es compatible.',
  emptyAudio: 'El servicio de voz no devolvió audio. Vuelve a intentarlo.',
  messageTooLong: 'Usa mensajes de menos de 4000 caracteres.',
  recordingTooLong: 'Hablemos en frases de menos de 25 segundos.',
  conversationEnded: 'La conversación se interrumpió. Vuelve a intentarlo.',
  speechUnrecognized: 'No pude reconocer lo que dijiste. Intenta hablar de nuevo.',
  signIn: 'Inicia sesión en la ventana de Savia para consultar tu cuenta.',
  resultInstruction: 'Resume brevemente para el usuario el resultado de la consulta. No repitas la consulta. Usa solo los datos del resultado y no prometas acciones futuras.',
};

const portuguese: typeof spanish = {
  invalidWorld: 'Esse lugar não está disponível.',
  invalidTask: 'A consulta não é válida. Faça um pedido mais breve.',
  unknownTool: 'Essa função não está disponível.',
  taskFailed: 'Não foi possível concluir a consulta. Confira o status na janela do Savia.',
  browserRequired: 'A voz precisa de acesso ao microfone em uma conexão segura. Você pode usar o teclado no menu de pausa.',
  playbackBlocked: 'Ative o som para ouvir a voz.',
  connectionFailed: 'Não foi possível conectar a voz. Tente novamente.',
  connectionEnded: 'A conexão de voz terminou. Você pode conectar novamente ou usar o teclado.',
  connectionBehind: 'A conexão de voz ficou atrasada. Conecte novamente para continuar.',
  microphoneDenied: 'O acesso ao microfone não foi permitido. Autorize o acesso e conecte novamente, ou use o teclado no menu de pausa.',
  configurationInvalid: 'A configuração de voz não é válida. Tente conectar novamente.',
  tokenExpired: 'A autorização de conexão expirou. Conecte novamente.',
  setupTimeout: 'A voz não concluiu a conexão. Tente novamente.',
  sessionEnding: 'A sessão de voz está terminando. Conecte novamente para continuar.',
  sessionExpired: 'A sessão de voz expirou. Conecte novamente para continuar.',
  streamFailed: 'O áudio foi interrompido. Conecte novamente para continuar.',
  providerFailed: 'O serviço de voz não conseguiu concluir o pedido. Tente novamente.',
  providerUnavailable: 'A voz não está disponível no momento. Você pode usar o teclado.',
  accessRequired: 'Não foi possível autorizar a voz. Confira seu acesso e tente novamente.',
  quotaExceeded: 'O serviço de voz atingiu o limite de uso. Você pode usar o teclado.',
  tooBusy: 'O serviço de voz está ocupado. Aguarde um momento antes de tentar novamente.',
  unsupportedAudio: 'O formato de áudio recebido não é compatível.',
  emptyAudio: 'O serviço de voz não retornou áudio. Tente novamente.',
  messageTooLong: 'Use mensagens com menos de 4000 caracteres.',
  recordingTooLong: 'Vamos conversar em frases de menos de 25 segundos.',
  conversationEnded: 'A conversa foi interrompida. Tente novamente.',
  speechUnrecognized: 'Não consegui reconhecer o que você disse. Tente falar novamente.',
  signIn: 'Entre na janela do Savia para consultar sua conta.',
  resultInstruction: 'Resuma brevemente para o usuário o resultado da consulta. Não repita a consulta. Use apenas os dados do resultado e não prometa ações futuras.',
};

export type VoiceMessage = keyof typeof spanish;
export function voiceCopy(locale: Locale = 'es'): typeof spanish {
  return normalizeLocale(locale) === 'pt' ? portuguese : spanish;
}

/** Browser/provider exception text is diagnostic data, never product copy. */
export class VoiceLocaleError extends Error {
  constructor(readonly key: VoiceMessage) { super(key); }
}
export function voiceError(locale: Locale | undefined, error: unknown, fallback: VoiceMessage = 'connectionFailed'): string {
  const copy = voiceCopy(locale);
  return copy[error instanceof VoiceLocaleError ? error.key : fallback];
}

export function voiceRequestError(status: number, code?: unknown): VoiceLocaleError {
  const key: VoiceMessage = code === 'voice_quota_exhausted' ? 'quotaExceeded'
    : status === 401 || status === 403 ? 'accessRequired'
    : status === 402 ? 'quotaExceeded' : status === 429 ? 'tooBusy'
    : status === 503 ? 'providerUnavailable' : 'providerFailed';
  return new VoiceLocaleError(key);
}

/** Only an allowlisted structured code can affect product copy. */
export async function voiceResponseError(response: Response): Promise<VoiceLocaleError> {
  const body: unknown = await response.json().catch(() => null);
  const code = body && typeof body === 'object' && 'code' in body ? body.code : undefined;
  return voiceRequestError(response.status, code);
}

const personas: Record<Locale, Record<AvatarId, string>> = {
  es: {
    moss: 'Eres Moss, una antigua tortuga del bosque. Habla con calma y paciencia, en frases cortas y cálidas, dejando espacio para respirar.',
    orbit: 'Eres Orbit, una guía serena y precisa del observatorio. Sé amable, breve y práctica.',
    spark: 'Eres Spark, una guía animada del desierto. Habla con energía y metáforas sorprendentes, con humor amable. Nunca insultes al usuario. Trata sus asuntos bancarios con cuidado.',
  },
  pt: {
    moss: 'Você é Moss, uma antiga tartaruga da floresta. Fale com calma e paciência, em frases curtas e acolhedoras, deixando espaço para respirar.',
    orbit: 'Você é Orbit, uma guia serena e precisa do observatório. Seja gentil, breve e prática.',
    spark: 'Você é Spark, uma guia animada do deserto. Fale com energia e metáforas surpreendentes, com humor gentil. Nunca insulte o usuário. Trate os assuntos bancários com cuidado.',
  },
};
export function voicePersona(avatar: AvatarId, locale: Locale = 'es'): string {
  return `${personas[normalizeLocale(locale)][avatar]} ${nativeLanguageInstruction(locale)}`;
}
export function voiceSessionInstructions(avatar: AvatarId, locale: Locale = 'es'): string {
  const policy = normalizeLocale(locale) === 'pt'
    ? 'Use set_world para preferências de ambiente e ritmo; isso não é uma avaliação clínica. Use delegate_task para consultar fatos da conta e acompanhar o trabalho. O login deve acontecer na janela visível do Savia; nunca peça senhas por voz. Não invente fatos ou resultados. Este serviço permite apenas consultas: contestações não são abertas. Não afirme que uma ação bancária aconteceu sem confirmação do sistema. Interromper a voz não cancela uma consulta já enviada.'
    : 'Usa set_world para preferencias de ambiente y ritmo; esto no es una evaluación clínica. Usa delegate_task para consultar datos de la cuenta y seguir el trabajo. El inicio de sesión ocurre en la ventana visible de Savia; nunca pidas contraseñas por voz. No inventes hechos ni resultados. Este servicio solo permite consultas: no se presentan disputas. No afirmes que se realizó una acción bancaria sin confirmación del sistema. Interrumpir la voz no cancela una consulta ya enviada.';
  return `${voicePersona(avatar, locale)} ${policy}`;
}
