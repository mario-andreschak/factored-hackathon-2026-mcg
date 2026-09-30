/**
 * Savia Lite - formatting helpers.
 *
 * Dates in the dataset are plain calendar/clock strings. They are formatted
 * field by field so the host timezone can never move a transaction to another
 * day, which is exactly the kind of silent drift this portal is meant to avoid.
 */

const LOCALE = { es: "es-CO", pt: "pt-BR", en: "en-GB" };

const MONTHS = {
  es: ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
  pt: ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

const MONTHS_SHORT = {
  es: ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
  pt: ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

/** Splits "2026-06-17 21:04:00" without letting Date apply a timezone. */
export function parts(stampText) {
  const [date, time = "00:00:00"] = String(stampText).split(" ");
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  return { y, m, d, hh, mm, date, time };
}

export const dayKey = (stampText) => parts(stampText).date;
export const monthKey = (stampText) => parts(stampText).date.slice(0, 7);

export function formatDay(stampText, lang) {
  const p = parts(stampText);
  const month = MONTHS_SHORT[lang]?.[p.m - 1] ?? MONTHS_SHORT.en[p.m - 1];
  return lang === "en" ? `${p.d} ${month} ${p.y}` : `${p.d} ${month} ${p.y}`;
}

export function formatDayTime(stampText, lang) {
  const p = parts(stampText);
  return `${formatDay(stampText, lang)} · ${String(p.hh).padStart(2, "0")}:${String(p.mm).padStart(2, "0")}`;
}

export function formatMonth(monthText, lang) {
  const [y, m] = monthText.split("-").map(Number);
  const month = MONTHS[lang]?.[m - 1] ?? MONTHS.en[m - 1];
  const cap = month.charAt(0).toUpperCase() + month.slice(1);
  return `${cap} ${y}`;
}

export function formatMoney(value, currency, lang) {
  try {
    return new Intl.NumberFormat(LOCALE[lang] || "es-CO", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
      minimumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${value.toFixed(2)}`;
  }
}

export function formatNumber(value, lang) {
  try {
    return new Intl.NumberFormat(LOCALE[lang] || "es-CO").format(value);
  } catch {
    return String(value);
  }
}

/** A signed display is only offered when the source direction is known. */
export function signedMoney(transaction, lang) {
  const text = formatMoney(transaction.amount, transaction.currency, lang);
  if (transaction.direction === "credit") return `+ ${text}`;
  if (transaction.direction === "debit") return `− ${text}`;
  return text;
}

export function toCsv(rows, header) {
  const escape = (cell) => {
    const text = cell === null || cell === undefined ? "" : String(cell);
    return /[",\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [header, ...rows].map((row) => row.map(escape).join(",")).join("\r\n") + "\r\n";
}
