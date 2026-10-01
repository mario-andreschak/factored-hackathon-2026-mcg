import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Txn } from "../types";
import { formatDay, money } from "../format";
import { VIEW_GLYPH, useShell, type View } from "../ui";

const VIEWS: View[] = ["home", "movements", "insights", "data"];

export default function Palette(props: {
  onClose: () => void;
  onNavigate: (view: View) => void;
  onOpenTxn: (reference: string) => void;
}) {
  const { onClose, onNavigate, onOpenTxn } = props;
  const { lang, t } = useShell();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Txn[]>([]);
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => { input.current?.focus(); }, []);

  /* The transaction search runs on the server, so the palette can look through
   * the whole ledger instead of only the page already loaded. */
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (query.trim().length < 2) { setHits([]); return; }
    timer.current = window.setTimeout(() => {
      api.ledger({ q: query.trim() }, 0, 7)
        .then((result) => setHits(result.transactions))
        .catch(() => setHits([]));
    }, 220);
    return () => window.clearTimeout(timer.current);
  }, [query]);

  const navHits = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return VIEWS.filter((view) => !needle || t(`nav.${view}`).toLowerCase().includes(needle));
  }, [query, t]);

  const items = useMemo(
    () => [
      ...navHits.map((view) => ({ kind: "nav" as const, view })),
      ...hits.map((txn) => ({ kind: "txn" as const, txn })),
    ],
    [navHits, hits]);

  useEffect(() => { setIndex(0); }, [query]);

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") { event.preventDefault(); onClose(); }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setIndex((current) => Math.min(current + 1, items.length - 1));
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setIndex((current) => Math.max(current - 1, 0));
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const chosen = items[index];
      if (!chosen) return;
      if (chosen.kind === "nav") onNavigate(chosen.view);
      else onOpenTxn(chosen.txn.reference);
    }
  }

  return (
    <div className="palette-wrap" onClick={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label={t("cmd.title")}
           onClick={(event) => event.stopPropagation()}>
        <input ref={input} type="text" value={query} placeholder={t("cmd.placeholder")}
               aria-label={t("cmd.title")}
               onChange={(event) => setQuery(event.target.value)} onKeyDown={onKeyDown} />

        <div className="palette-list">
          {items.length === 0 && <p className="palette-group note">{t("cmd.empty")}</p>}

          {navHits.length > 0 && <p className="palette-group eyebrow">{t("cmd.nav")}</p>}
          {navHits.map((view, position) => (
            <button key={view} className="palette-item"
                    aria-selected={items[index]?.kind === "nav" && position === index}
                    onMouseEnter={() => setIndex(position)}
                    onClick={() => onNavigate(view)}>
              <span className="glyph" aria-hidden="true">{VIEW_GLYPH[view]}</span>
              <span>{t(`nav.${view}`)}</span>
              <span className="sub">↵</span>
            </button>
          ))}

          {hits.length > 0 && <p className="palette-group eyebrow">{t("cmd.tx")}</p>}
          {hits.map((txn, position) => {
            const absolute = navHits.length + position;
            return (
              <button key={txn.reference} className="palette-item"
                      aria-selected={absolute === index}
                      onMouseEnter={() => setIndex(absolute)}
                      onClick={() => onOpenTxn(txn.reference)}>
                <span className="glyph" aria-hidden="true">≡</span>
                <span>
                  {txn.merchant ?? t("tx.unknownMerchant")}
                  <br />
                  <span className="sub">
                    {formatDay(txn.event_date, lang)} · {t(`type.${txn.type}`)}
                  </span>
                </span>
                <span className="sub num">{money(txn.amount, txn.currency, lang)}</span>
              </button>
            );
          })}
        </div>

        <p className="palette-foot">{t("cmd.hint")}</p>
      </div>
    </div>
  );
}
