export type Locale = 'es' | 'pt';
export const DEFAULT_LOCALE: 'es';
export const SUPPORTED_LOCALES: readonly ['es', 'pt'];
export function isLocale(value: unknown): value is Locale;
export function normalizeLocale(value: unknown): Locale;
export function localeTag(locale: Locale): 'es-CO' | 'pt-BR';
export function localeFromLanguage(language: unknown): Locale;
export function nativeLanguageInstruction(locale: Locale): string;
