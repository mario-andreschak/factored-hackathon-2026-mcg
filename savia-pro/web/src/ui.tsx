import { createContext, useContext } from "react";
import type { Lang, Txn } from "./types";
import type { T } from "./i18n";
import { formatDayTime, money, signed } from "./format";

/* ------------------------------------------------------------------ context */

export type Shell = {
  lang: Lang;
  t: T;
  toast: (message: string, tone?: "ok" | "bad") => void;
  openTxn: (reference: string) => void;
  go: (view: View, filters?: Record<string, unknown>) => void;
};

export type View = "home" | "movements" | "insights" | "data";

export const ShellContext = createContext<Shell | null>(null);

export function useShell(): Shell {
  const shell = useContext(ShellContext);
  if (!shell) throw new Error("useShell used outside the shell");
  return shell;
}

/* ------------------------------------------------------------------- glyphs */

export const TYPE_GLYPH: Record<string, string> = {
  Purchase: "\u{1F6CD}", Withdrawal: "\u{1F3E7}", Deposit: "↓",
  Transfer: "⇄", Payment: "◷", Adjustment: "⤺",
};

export const VIEW_GLYPH: Record<View, string> = {
  home: "⌂", movements: "≣", insights: "◴", data: "◬",
};

/* ------------------------------------------------- small shared components */

export function Card(props: {
  title?: string; note?: string; aside?: React.ReactNode;
  children: React.ReactNode; className?: string; index?: number;
}) {
  const { title, note, aside, children, className = "", index = 0 } = props;
  return (
    <section className={`card reveal ${className}`} style={{ ["--i" as string]: index }}>
      {(title || aside) && (
        <header className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {note && <p className="note">{note}</p>}
          </div>
          {aside}
        </header>
      )}
      {children}
    </section>
  );
}

/** The status badge is the single place a status becomes a colour, so a pending
 *  row can never be painted as if it had settled. */
export function StatusBadge({ status, t }: { status: string; t: T }) {
  const tone = status === "Approved" ? "ok"
    : status === "Pending" ? "warn"
    : status === "Declined" ? "stop" : "info";
  return <span className={`badge ${tone}`}>{t(`status.${status}`)}</span>;
}

export function merchantLabel(txn: Txn, t: T) {
  return txn.merchant ?? t("tx.unknownMerchant");
}

export function TxnRow(props: {
  txn: Txn; onOpen: (reference: string) => void; selected?: boolean;
  lang: Lang; t: T; index?: number;
}) {
  const { txn, onOpen, selected, lang, t, index = 0 } = props;
  const meta = [
    formatDayTime(txn.occurred_at, lang),
    t(`type.${txn.type}`),
    t(`channel.${txn.channel}`),
    txn.product_reference.slice(-4),
  ].join(" · ");

  return (
    <button className="row reveal" aria-current={selected ? "true" : undefined}
            style={{ ["--i" as string]: index }}
            onClick={() => onOpen(txn.reference)}>
      <span className="row-glyph" aria-hidden="true">{TYPE_GLYPH[txn.type] ?? "•"}</span>
      <span>
        <span className="row-title">
          {txn.merchant
            ? <span>{txn.merchant}</span>
            : <span className="unknown">{t("tx.unknownMerchant")}</span>}
          {txn.date_gap_days === 1 && <span className="badge mute">+1d</span>}
        </span>
        <span className="row-meta">{meta}</span>
      </span>
      <span className="row-right">
        <span className={`row-amount ${txn.direction}`}>
          {signed(txn.amount, txn.currency, txn.direction, lang)}
        </span>
        <span style={{ display: "flex", gap: 5, justifyContent: "flex-end" }}>
          {txn.direction === "unknown" && <span className="badge mute">{t("dir.unknown")}</span>}
          {txn.status !== "Approved" && <StatusBadge status={txn.status} t={t} />}
        </span>
      </span>
    </button>
  );
}

export function Money({ value, currency, lang }: { value: number | null; currency: string; lang: Lang }) {
  return <span className="num">{money(value, currency, lang)}</span>;
}

export function Skeleton({ kind = "row", count = 1 }: { kind?: "row" | "card" | "text"; count?: number }) {
  return (
    <div className="rows" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => <div key={i} className={`sk sk-${kind}`} />)}
    </div>
  );
}

export function Empty({ glyph, title, note }: { glyph: string; title: string; note?: string }) {
  return (
    <div className="empty">
      <span className="big" aria-hidden="true">{glyph}</span>
      <strong>{title}</strong>
      {note && <p className="note">{note}</p>}
    </div>
  );
}

export function ErrorBox({ message, onRetry, t }: { message: string; onRetry?: () => void; t: T }) {
  return (
    <div className="notebox stop">
      <b aria-hidden="true">!</b>
      <span>
        <b>{t("err.title")}</b> — {message}
        {onRetry && <> <button className="linkbtn" onClick={onRetry}>{t("err.retry")}</button></>}
      </span>
    </div>
  );
}
