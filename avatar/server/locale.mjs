/** Shared language policy; this selects wording, never identity or authorization. */
export const DEFAULT_LOCALE = 'es';
export const SUPPORTED_LOCALES = Object.freeze(['es', 'pt']);

export function isLocale(value) { return value === 'es' || value === 'pt'; }
export function normalizeLocale(value) { return isLocale(value) ? value : DEFAULT_LOCALE; }
export function localeTag(locale) { return normalizeLocale(locale) === 'pt' ? 'pt-BR' : 'es-CO'; }

/** Only Portuguese as the preferred browser language changes the initial default. */
export function localeFromLanguage(language) {
  return typeof language === 'string' && /^pt(?:[-_]|$)/i.test(language.trim()) ? 'pt' : DEFAULT_LOCALE;
}

export function nativeLanguageInstruction(locale) {
  return normalizeLocale(locale) === 'pt'
    ? 'Converse sempre em português do Brasil, com linguagem natural, clara e acolhedora. Use as palavras do usuário e mantenha Moss, Orbit e Spark como nomes dos personagens. Não mude de idioma sem um pedido explícito.'
    : 'Conversa siempre en español latinoamericano, claro, natural y cercano, con un tono colombiano neutral. Usa las palabras del usuario y conserva Moss, Orbit y Spark como nombres de los personajes. No cambies de idioma sin una petición explícita.';
}
