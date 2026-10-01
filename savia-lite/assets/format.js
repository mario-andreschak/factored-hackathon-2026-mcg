/**
 * Savia Lite - formatting helpers.
 *
 * Dates in the dataset are plain calendar/clock strings. They are formatted
 * field by field so the host timezone can never move a transaction to another
 * calendar day, which is exactly the kind of silent drift this portal exists
 * to avoid.
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
  const hh = String(p.hh).padStart(2, "0");
  const mm = String(p.mm).padStart(2, "0");
  return `${formatDay(stampText, lang)} · ${hh}:${mm}`;
}

/** "2026-06" -> "junio 2026" */
export function formatMonth(monthText, lang) {
  const [y, m] = monthText.split("-").map(Number);
  const name = MONTHS[lang]?.[m - 1] ?? MONTHS.en[m - 1];
  return `${name} ${y}`;
}

/** "2026-06" -> "jun" */
export function formatMonthShort(monthText, lang) {
  const [, m] = monthText.split("-").map(Number);
  return MONTHS_SHORT[lang]?.[m - 1] ?? MONTHS_SHORT.en[m - 1];
}

/**
 * Always prints the currency the row actually carries. There is no conversion
 * anywhere in this app, so a value is never shown in a currency it was not
 * recorded in.
 */
export function formatMoney(value, currency, lang) {
  const locale = LOCALE[lang] || LOCALE.es;
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${currency} ${formatNumber(value, lang)}`;
  }
}

/** Short form for chart axes: 1.2M / 340k. Never used for an exact figure. */
export function formatCompact(value, lang) {
  const locale = LOCALE[lang] || LOCALE.es;
  const abs = Math.abs(value);
  try {
    if (abs >= 1000) {
      return new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 1 }).format(value);
    }
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
  } catch {
    return String(Math.round(value));
  }
}

export function formatNumber(value, lang, digits = 2) {
  const locale = LOCALE[lang] || LOCALE.es;
  try {
    return new Intl.NumberFormat(locale, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  } catch {
    return String(value);
  }
}

export const formatCount = (value, lang) => formatNumber(value, lang, 0);

export function formatPercent(fraction, lang, digits = 1) {
  const locale = LOCALE[lang] || LOCALE.es;
  try {
    return new Intl.NumberFormat(locale, {
      style: "percent",
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(fraction);
  } catch {
    return `${(fraction * 100).toFixed(digits)}%`;
  }
}

/**
 * Signs a money figure only when the direction is actually known. An unknown
 * direction gets no sign, because inventing one would be a claim the data
 * does not support.
 */
export function signedMoney(value, currency, direction, lang) {
  const text = formatMoney(value, currency, lang);
  if (direction === "credit") return `+ ${text}`;
  if (direction === "debit") return `− ${text}`;
  return text;
}

/** RFC 4180 style quoting, so a separator inside a value cannot break a row. */
export function toCsv(rows) {
  const escape = (cell) => {
    const text = cell === null || cell === undefined ? "" : String(cell);
    return /[",;\n\r]/.test(text) ? `"${text.split('"').join('""')}"` : text;
  };
  return rows.map((row) => row.map(escape).join(",")).join("\r\n");
}

/** Triggers a client-side download. No upload, no network request. */
export function download(filename, text, mime = "text/plain;charset=utf-8") {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
