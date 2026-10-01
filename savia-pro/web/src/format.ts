import type { Lang } from "./types";

const LOCALE: Record<Lang, string> = { es: "es-CO", pt: "pt-BR", en: "en-GB" };

const MONTH_SHORT: Record<Lang, string[]> = {
  es: ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
  pt: ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

const MONTH_LONG: Record<Lang, string[]> = {
  es: ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
  pt: ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

/** Splits an ISO-like stamp field by field. Never constructs a Date, so the
 *  host timezone cannot move a row onto another calendar day. */
export function parts(stamp: string) {
  const [date, time = "00:00:00"] = String(stamp).replace("T", " ").split(" ");
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  return { y, m, d, hh: hh || 0, mm: mm || 0, date };
}

export const dayKey = (stamp: string) => parts(stamp).date;
export const monthKey = (stamp: string) => parts(stamp).date.slice(0, 7);

export function formatDay(stamp: string, lang: Lang) {
  const p = parts(stamp);
  return `${p.d} ${MONTH_SHORT[lang][p.m - 1]} ${p.y}`;
}

export function formatDayTime(stamp: string, lang: Lang) {
  const p = parts(stamp);
  return `${formatDay(stamp, lang)} · ${String(p.hh).padStart(2, "0")}:${String(p.mm).padStart(2, "0")}`;
}

export function formatMonth(key: string, lang: Lang, short = false) {
  const [y, m] = key.split("-").map(Number);
  const table = short ? MONTH_SHORT : MONTH_LONG;
  return `${table[lang][m - 1]} ${y}`;
}

export function money(amount: number | null | undefined, currency: string, lang: Lang) {
  if (amount === null || amount === undefined) return "—";
  try {
    return new Intl.NumberFormat(LOCALE[lang], {
      style: "currency", currency, maximumFractionDigits: 2, minimumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

/** Keeps a long ledger readable: 1.2 M instead of 1.234.567,89 */
export function compact(value: number, lang: Lang) {
  return new Intl.NumberFormat(LOCALE[lang], {
    notation: "compact", maximumFractionDigits: 1,
  }).format(value);
}

export const count = (value: number, lang: Lang) =>
  new Intl.NumberFormat(LOCALE[lang]).format(value);

export const percent = (ratio: number, lang: Lang, digits = 1) =>
  new Intl.NumberFormat(LOCALE[lang], {
    style: "percent", minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(ratio);

/** A sign is only ever shown when the snapshot states a direction. */
export function signed(amount: number, currency: string,
                       direction: "debit" | "credit" | "unknown", lang: Lang) {
  const text = money(Math.abs(amount), currency, lang);
  if (direction === "credit") return `+ ${text}`;
  if (direction === "debit") return `− ${text}`;
  return text;
}
