import { DEFAULT_LOCALE, isLocale, localeFromLanguage, localeTag, normalizeLocale } from '../server/locale.mjs';
export { DEFAULT_LOCALE, isLocale, localeTag, normalizeLocale };
export type { Locale } from '../server/locale.mjs';
import type { Locale } from '../server/locale.mjs';

export const LOCALE_STORAGE_KEY = 'elsewhere.locale';
export const LOCALE_LABELS: Readonly<Record<Locale, string>> = {
  es: 'Español (Latinoamérica)', pt: 'Português (Brasil)',
};
export interface LocaleStorage { getItem(key: string): string | null; setItem(key: string, value: string): void; }
export interface InitialLocaleOptions {
  storage?: LocaleStorage | null;
  language?: string;
  languages?: readonly string[];
}

function browserStorage(): LocaleStorage | null {
  try { return typeof window === 'undefined' ? null : window.localStorage; } catch { return null; }
}

/** Read a deliberate saved choice first; deriving a default never writes storage. */
export function getInitialLocale(options: InitialLocaleOptions = {}): Locale {
  try {
    const stored = (options.storage === undefined ? browserStorage() : options.storage)?.getItem(LOCALE_STORAGE_KEY);
    if (isLocale(stored)) return stored;
  } catch { /* Storage can be unavailable in private, sandboxed or SSR contexts. */ }
  let preferred: string | undefined;
  try {
    preferred = options.languages?.find(value => typeof value === 'string' && Boolean(value.trim())) || options.language;
    if (preferred === undefined && typeof navigator !== 'undefined') {
      preferred = navigator.languages?.find(value => Boolean(value.trim())) || navigator.language;
    }
  } catch { /* A denied navigator remains the Spanish default. */ }
  return localeFromLanguage(preferred);
}

/** Call only for a deliberate language selection, not the inferred first visit. */
export function persistLocale(locale: Locale, storage?: LocaleStorage | null): boolean {
  if (!isLocale(locale)) return false;
  try {
    const target = storage === undefined ? browserStorage() : storage;
    if (!target) return false;
    target.setItem(LOCALE_STORAGE_KEY, locale); return true;
  } catch { return false; }
}

const es = {
  ui: {
    language: 'Idioma', wakeWorld: 'Despertar el mundo', stopListening: 'Dejar de escuchar',
    talkTo: 'Hablar con {name}', lookPool: 'Mirar el estanque', useComputer: 'Usar la ventana del mundo',
    pauseStory: 'Pausar la historia', pauseMenu: 'Menú de pausa', returnWorld: 'Volver al mundo',
    wander: 'Explorar otro lugar', useKeyboard: 'Usar el teclado', followPace: 'Seguir mi ritmo',
    worldSound: 'Sonidos del mundo', subtitles: 'Subtítulos', gentlerMotion: 'Movimiento más suave',
    muteMicrophone: 'Silenciar el micrófono', unmuteMicrophone: 'Activar el micrófono',
    endVoice: 'Terminar conversación de voz', startVoice: 'Iniciar conversación de voz',
    wordsAlongWay: 'Palabras del camino', escapeToReturn: 'ESC PARA VOLVER',
    messageCompanion: 'Escribe a tu compañero', sendMessage: 'Enviar mensaje', closeKeyboard: 'Cerrar teclado',
    choosePlace: 'Elegir un lugar', closePlaces: 'Cerrar lugares', travelTo: 'Viajar a {place}',
    chooseCharacter: 'Elegir a {name}', conversationTranscript: 'Transcripción de la conversación',
    closeTranscript: 'Cerrar transcripción', you: 'TÚ', companion: 'COMPAÑERO',
    dismissNotice: 'Cerrar aviso', interruptCompanion: 'Interrumpir al compañero', preview: 'vista previa',
    closeComputer: 'Cerrar ventana', watchExample: 'Ver un ejemplo',
  },
  status: {
    idle: 'En calma', listening: 'Te escucho', connectingVoice: 'Conectando la voz',
    microphoneMuted: 'Micrófono silenciado', worldPreview: 'Vista previa del mundo', voiceOffline: 'Voz desconectada',
    thinking: 'Pensando', speaking: 'Hablando', saviaWorking: 'Savia está trabajando',
    initialPreparing: 'Preparando a tu compañero',
  },
  game: {
    firstListen: 'Cuéntame qué tienes en mente.',
    audioNotice: 'Compañero de IA. Al activar el micrófono, tu audio se envía a {provider} para responder y transcribir. Evita contraseñas y códigos. Puedes silenciarlo o escribir.',
    backgroundTranscriptionUnavailable: 'La transcripción no está disponible. Puedes seguir hablando.',
    saviaNotConnected: 'Savia no está conectado. Estás explorando una vista previa.',
    previousRequestBusy: 'Savia todavía está revisando tu solicitud anterior.',
    previousRequestWithheld: 'Tu sesión de Savia cambió. No se envió la solicitud anterior.',
    previousResponseWithheld: 'Tu sesión de Savia cambió. No se mostró la respuesta anterior.',
    requestStoppedBeforeSend: 'La solicitud se detuvo antes de enviarse.',
    poolOpening: 'El estanque todavía se está abriendo.',
    signInAtPool: 'Ven al estanque. Inicia sesión para ver tu cuenta.',
    signInCheckFailed: 'Savia no pudo verificar tu sesión. Cierra el estanque e inténtalo de nuevo.',
    lookTogether: 'Miremos los detalles juntos.',
    readFailed: 'Savia no pudo completar la consulta.',
    signInRequestExpired: 'La solicitud venció mientras esperábamos el inicio de sesión. Pregunta de nuevo cuando quieras.',
    comeToPool: 'Ven, miremos el estanque.',
    greeting: 'Mmm… hola. Ven, siéntate conmigo un momento.',
    nativeAuditionEnded: 'La conversación de voz terminó. Puedes seguir explorando el mundo.',
    travelInstruction: 'Vamos al siguiente lugar de este mundo. Haz una invitación breve y luego usa set_world para elegir la siguiente escena.',
    signInRequired: 'Inicia sesión en Savia.',
    waitAtPool: 'Inicia sesión en el estanque. Yo te espero aquí.',
    humanReply: 'Hagamos una pausa. Si tienes un problema de seguridad urgente, contacta a tu banco por su canal oficial. Podemos pensar juntos en el siguiente paso.',
  },
  characters: {
    moss: { name: 'Moss', role: 'El guardián tranquilo', line: 'Un pequeño paso a la vez.', description: 'Una presencia tranquila. Espacio para respirar.', color: '#c7d9a1', travel: 'Mmm… ven conmigo. Hay algo que quiero mostrarte.', hello: 'Hola, viajero. Aquí hay espacio para ti. ¿Qué tienes en mente?', reply: 'Mmm… te escucho. No tienes que resolver todo a la vez. Cuéntame qué parte se siente más pesada.', bankReply: 'Mmm… podemos mirar juntos. El estanque tiene un pequeño ejemplo. Tu cuenta real está protegida por tu inicio de sesión en Savia.' },
    orbit: { name: 'Orbit', role: 'El pensador claro', line: 'Organicemos las piezas.', description: 'Un poco de perspectiva. Un camino más claro.', color: '#bddcfa', travel: 'Un cambio de perspectiva. ¿Vamos?', hello: 'Hola. Podemos ordenar las ideas juntos. ¿Qué tienes en mente?', reply: 'Hagámoslo más manejable. ¿Qué resultado te gustaría conseguir?', bankReply: 'Primero revisemos los detalles. Abre el estanque para ver el ejemplo o conecta Savia para consultar tu cuenta.' },
    spark: { name: 'Spark', role: 'La chispa inquieta', line: 'Listo. ¡Vamos con toda!', description: 'Mucha energía. Ideas que sorprenden.', color: '#ffc284', travel: '¡Vamos! Conozco un lugar que te va a encantar.', hello: '¡Ey! Tú, yo y una buena dosis de energía. ¿Qué vamos a resolver?', reply: 'Una cosa a la vez, pero con impulso. ¿Qué quieres destrabar primero?', bankReply: '¡Listo, modo detective! Abramos el estanque y revisemos ese cobro juntos. Para tu cuenta real necesitas iniciar sesión en Savia.' },
  },
} as const;

type TextShape<T> = { readonly [K in keyof T]: T[K] extends string ? string : TextShape<T[K]> };
export type Messages = TextShape<typeof es>;
const pt: Messages = {
  ui: {
    language: 'Idioma', wakeWorld: 'Despertar o mundo', stopListening: 'Parar de ouvir',
    talkTo: 'Conversar com {name}', lookPool: 'Olhar o lago', useComputer: 'Usar a janela do mundo',
    pauseStory: 'Pausar a história', pauseMenu: 'Menu de pausa', returnWorld: 'Voltar ao mundo',
    wander: 'Explorar outro lugar', useKeyboard: 'Usar o teclado', followPace: 'Seguir meu ritmo',
    worldSound: 'Sons do mundo', subtitles: 'Legendas', gentlerMotion: 'Movimentos mais suaves',
    muteMicrophone: 'Silenciar o microfone', unmuteMicrophone: 'Ativar o microfone',
    endVoice: 'Encerrar conversa por voz', startVoice: 'Iniciar conversa por voz',
    wordsAlongWay: 'Palavras do caminho', escapeToReturn: 'ESC PARA VOLTAR',
    messageCompanion: 'Escreva para seu companheiro', sendMessage: 'Enviar mensagem', closeKeyboard: 'Fechar teclado',
    choosePlace: 'Escolher um lugar', closePlaces: 'Fechar lugares', travelTo: 'Viajar para {place}',
    chooseCharacter: 'Escolher {name}', conversationTranscript: 'Transcrição da conversa',
    closeTranscript: 'Fechar transcrição', you: 'VOCÊ', companion: 'COMPANHEIRO',
    dismissNotice: 'Fechar aviso', interruptCompanion: 'Interromper o companheiro', preview: 'prévia',
    closeComputer: 'Fechar janela', watchExample: 'Ver um exemplo',
  },
  status: {
    idle: 'Em calma', listening: 'Estou ouvindo', connectingVoice: 'Conectando a voz',
    microphoneMuted: 'Microfone silenciado', worldPreview: 'Prévia do mundo', voiceOffline: 'Voz desconectada',
    thinking: 'Pensando', speaking: 'Falando', saviaWorking: 'Savia está trabalhando',
    initialPreparing: 'Preparando seu companheiro',
  },
  game: {
    firstListen: 'Conte o que está passando pela sua cabeça.',
    audioNotice: 'Companheiro de IA. Ao ativar o microfone, seu áudio é enviado a {provider} para responder e transcrever. Evite senhas e códigos. Você pode silenciar ou escrever.',
    backgroundTranscriptionUnavailable: 'A transcrição não está disponível. Você pode continuar falando.',
    saviaNotConnected: 'Savia não está conectado. Você está explorando uma prévia.',
    previousRequestBusy: 'Savia ainda está verificando sua solicitação anterior.',
    previousRequestWithheld: 'Sua sessão do Savia mudou. A solicitação anterior não foi enviada.',
    previousResponseWithheld: 'Sua sessão do Savia mudou. A resposta anterior não foi exibida.',
    requestStoppedBeforeSend: 'A solicitação foi interrompida antes do envio.',
    poolOpening: 'O lago ainda está abrindo.',
    signInAtPool: 'Venha até o lago. Entre para ver sua conta.',
    signInCheckFailed: 'Savia não conseguiu verificar sua sessão. Feche o lago e tente novamente.',
    lookTogether: 'Vamos olhar os detalhes juntos.',
    readFailed: 'Savia não conseguiu concluir a consulta.',
    signInRequestExpired: 'A solicitação expirou enquanto esperávamos o login. Pergunte de novo quando quiser.',
    comeToPool: 'Venha, vamos olhar o lago.',
    greeting: 'Hmm… oi. Venha, sente comigo um pouco.',
    nativeAuditionEnded: 'A conversa por voz terminou. Você pode continuar explorando o mundo.',
    travelInstruction: 'Vamos ao próximo lugar deste mundo. Faça um convite curto e depois use set_world para escolher a próxima cena.',
    signInRequired: 'Entre no Savia.',
    waitAtPool: 'Entre pelo lago. Eu espero você aqui.',
    humanReply: 'Vamos fazer uma pausa. Se você tiver um problema urgente de segurança, fale com seu banco pelo canal oficial. Podemos pensar juntos no próximo passo.',
  },
  characters: {
    moss: { name: 'Moss', role: 'O guardião tranquilo', line: 'Um pequeno passo de cada vez.', description: 'Uma presença tranquila. Espaço para respirar.', color: '#c7d9a1', travel: 'Hmm… venha comigo. Quero mostrar uma coisa.', hello: 'Olá, viajante. Aqui tem espaço para você. O que está pensando?', reply: 'Hmm… estou ouvindo. Você não precisa resolver tudo de uma vez. Conte qual parte está pesando mais.', bankReply: 'Hmm… podemos olhar juntos. O lago tem um pequeno exemplo. Sua conta real continua protegida pelo seu login no Savia.' },
    orbit: { name: 'Orbit', role: 'O pensador claro', line: 'Vamos organizar as peças.', description: 'Um pouco de perspectiva. Um caminho mais claro.', color: '#bddcfa', travel: 'Uma mudança de perspectiva. Vamos?', hello: 'Olá. Podemos organizar as ideias juntos. O que está pensando?', reply: 'Vamos tornar isso mais simples. Qual resultado você gostaria de alcançar?', bankReply: 'Primeiro vamos verificar os detalhes. Abra o lago para ver o exemplo ou conecte o Savia para consultar sua conta.' },
    spark: { name: 'Spark', role: 'A faísca inquieta', line: 'Fechou. Vamos nessa!', description: 'Muita energia. Ideias que surpreendem.', color: '#ffc284', travel: 'Bora! Conheço um lugar que você vai adorar.', hello: 'Ei! Você, eu e uma boa dose de energia. O que vamos resolver?', reply: 'Uma coisa de cada vez, mas com energia. O que você quer destravar primeiro?', bankReply: 'Fechou, modo detetive! Vamos abrir o lago e olhar essa cobrança juntos. Para sua conta real, você precisa entrar no Savia.' },
  },
};

const catalogs: Readonly<Record<Locale, Messages>> = { es, pt };
export function getMessages(locale: Locale): Messages { return catalogs[normalizeLocale(locale)]; }

/** Plain-text interpolation; replacement values are never parsed as templates. */
export function formatMessage(template: string, values: Readonly<Record<string, string | number>>): string {
  return template.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (placeholder, key: string) =>
    Object.hasOwn(values, key) ? String(values[key]) : placeholder);
}
