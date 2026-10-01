import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Detail, Review, Txn } from "../types";
import { formatDay, formatDayTime, money, signed } from "../format";
import { Card, ErrorBox, Skeleton, StatusBadge, TxnRow, useShell } from "../ui";

const QUESTIONS = [
  { id: "recognise", key: "rev.q.recognise" },
  { id: "authorised", key: "rev.q.authorised" },
  { id: "amount", key: "rev.q.amount" },
  { id: "received", key: "rev.q.received" },
  { id: "card", key: "rev.q.card" },
];

const REASONS = ["unrecognised_charge", "duplicate_suspicion", "amount_wrong",
                 "service_not_received", "card_lost_or_stolen", "other"];

type Mode = "detail" | "review" | "receipt";

export default function TxnDrawer(props: { reference: string; onClose: () => void }) {
  const { reference, onClose } = props;
  const { lang, t, toast, openTxn } = useShell();

  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<Mode>("detail");
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [reason, setReason] = useState(REASONS[0]);
  const [note, setNote] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [receipt, setReceipt] = useState<Review | null>(null);
  const [busy, setBusy] = useState(false);

  const panel = useRef<HTMLDivElement | null>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    opener.current = document.activeElement as HTMLElement;
    return () => opener.current?.focus?.();
  }, []);

  useEffect(() => {
    setDetail(null);
    setError("");
    setMode("detail");
    setStep(0);
    setAnswers({});
    setUrgent(false);
    setReceipt(null);
    api.detail(reference)
      .then(setDetail)
      .catch((caught) => setError(caught?.message ?? "failed"));
  }, [reference]);

  /* Escape closes, and Tab stays inside the panel while it is open. */
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab" || !panel.current) return;
      const focusable = panel.current.querySelectorAll<HTMLElement>(
        'a[href],button:not([disabled]),input:not([disabled]),select,textarea,[tabindex]:not([tabindex="-1"])');
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    if (detail) panel.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
  }, [detail, mode]);

  async function submit() {
    setBusy(true);
    try {
      const created = await api.openReview({
        reference, reason: urgent ? "card_lost_or_stolen" : reason,
        answers: urgent ? {} : answers, note, urgent,
      });
      setReceipt(created);
      setMode("receipt");
      toast(`${t("rec.title")} · ${created.id}`);
    } catch (caught: any) {
      toast(caught?.message ?? "failed", "bad");
    } finally {
      setBusy(false);
    }
  }

  const txn = detail?.transaction;
  const last = step === QUESTIONS.length - 1;
  const answered = urgent || answers[QUESTIONS[step]?.id] !== undefined;

  return (
    <>
      <div className="overlay" onClick={onClose} />
      <aside className="drawer" ref={panel} role="dialog" aria-modal="true"
             aria-label={t("tx.detail")}>
        <header className="drawer-head">
          <div>
            <p className="eyebrow">{t("tx.detail")}</p>
            <h2>{txn ? (txn.merchant ?? t("tx.unknownMerchant")) : "…"}</h2>
          </div>
          <button className="iconbtn" onClick={onClose} aria-label={t("a11y.close")}>✕</button>
        </header>

        <div className="drawer-body">
          {error && <ErrorBox message={error} t={t} />}
          {!detail && !error && <Skeleton kind="text" count={8} />}

          {detail && txn && mode === "detail" && (
            <Detailed detail={detail} lang={lang} t={t} openTxn={openTxn} />
          )}

          {detail && txn && mode === "review" && (
            <>
              <p className="note">{t("rev.lead")}</p>

              <div className="progress">
                <i style={{ ["--w" as string]: urgent ? "100%"
                  : `${((step + (answered ? 1 : 0)) / QUESTIONS.length) * 100}%` }} />
              </div>

              {!urgent && (
                <>
                  <p className="eyebrow">{t("rev.step", { n: step + 1, total: QUESTIONS.length })}</p>
                  <h3>{t(QUESTIONS[step].key)}</h3>
                  <div className="answers" role="group" aria-label={t(QUESTIONS[step].key)}>
                    {["yes", "no", "unsure"].map((value) => (
                      <button key={value} className="answer"
                              aria-pressed={answers[QUESTIONS[step].id] === value}
                              onClick={() => setAnswers({ ...answers, [QUESTIONS[step].id]: value })}>
                        {t(`rev.${value}`)}
                      </button>
                    ))}
                  </div>
                </>
              )}

              {(urgent || last) && (
                <>
                  <label className="field" style={{ marginTop: 16 }}>
                    <span className="field-label">{t("rev.reason")}</span>
                    <select value={urgent ? "card_lost_or_stolen" : reason} disabled={urgent}
                            onChange={(event) => setReason(event.target.value)}>
                      {REASONS.map((item) => (
                        <option key={item} value={item}>{t(`rev.reason.${item}`)}</option>
                      ))}
                    </select>
                  </label>
                  <label className="field" style={{ marginTop: 12 }}>
                    <span className="field-label">{t("rev.note")}</span>
                    <textarea value={note} maxLength={1200}
                              onChange={(event) => setNote(event.target.value)} />
                  </label>
                </>
              )}

              <label className="check">
                <input type="checkbox" checked={urgent}
                       onChange={(event) => setUrgent(event.target.checked)} />
                <span>
                  <span className="check-title">{t("rev.urgent")}</span>
                  <span className="check-note">{t("rev.urgentNote")}</span>
                </span>
              </label>
            </>
          )}

          {mode === "receipt" && receipt && (
            <div className="receipt">
              <div className="receipt-id">
                <span>
                  <span className="eyebrow">{t("rec.id")}</span><br />
                  <b>{receipt.id}</b>
                </span>
                <span className={`badge ${receipt.priority === "security" ? "stop" : "ok"}`}>
                  {t(`rev.reason.${receipt.reason}`) === `rev.reason.${receipt.reason}`
                    ? receipt.reason : t(`rev.reason.${receipt.reason}`)}
                </span>
              </div>

              <div>
                <p className="eyebrow">{t("rec.digest")}</p>
                <p className="mono" style={{ overflowWrap: "anywhere", color: "var(--ink-2)" }}>
                  {receipt.evidence.facts_sha256}
                </p>
              </div>

              <div>
                <p className="eyebrow" style={{ marginBottom: 7 }}>{t("rec.notDone")}</p>
                <ul className="notdone" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {["nd1", "nd2", "nd3", "nd4"].map((key) => (
                    <li key={key}>
                      <span className="x" aria-hidden="true">✕</span>
                      <span>{t(`rec.${key}`)}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <pre className="receipt-json">{JSON.stringify(receipt, null, 2)}</pre>
            </div>
          )}
        </div>

        <footer className="drawer-foot">
          {mode === "detail" && (
            <>
              <button className="btn" data-autofocus onClick={() => setMode("review")}>
                {t("tx.review")}
              </button>
              <button className="btn ghost" onClick={() => {
                navigator.clipboard?.writeText(JSON.stringify(detail?.transaction, null, 2));
                toast(t("tx.copy") + " ✓");
              }}>{t("tx.copy")}</button>
            </>
          )}

          {mode === "review" && (
            <>
              {!urgent && step > 0 && (
                <button className="btn ghost" onClick={() => setStep(step - 1)}>
                  ← {t("rev.back")}
                </button>
              )}
              {urgent || last ? (
                <button className={`btn ${urgent ? "danger" : ""}`} disabled={busy} onClick={submit}>
                  {busy ? t("mov.loading") : t("rev.finish")}
                </button>
              ) : (
                <button className="btn" disabled={!answered} onClick={() => setStep(step + 1)}>
                  {t("rev.next")} →
                </button>
              )}
              <button className="btn ghost" onClick={() => setMode("detail")}>
                {t("a11y.close")}
              </button>
            </>
          )}

          {mode === "receipt" && receipt && (
            <>
              <button className="btn ghost" onClick={() => {
                const blob = new Blob([JSON.stringify(receipt, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const anchor = document.createElement("a");
                anchor.href = url;
                anchor.download = `${receipt.id}.json`;
                anchor.click();
                URL.revokeObjectURL(url);
              }}>{t("rec.download")}</button>
              <button className="btn" data-autofocus onClick={onClose}>{t("rec.close")}</button>
            </>
          )}
        </footer>
      </aside>
    </>
  );
}

function Detailed(props: {
  detail: Detail; lang: any; t: any; openTxn: (reference: string) => void;
}) {
  const { detail, lang, t, openTxn } = props;
  const txn = detail.transaction;

  const notes: { tone: string; text: string }[] = [];
  if (txn.status === "Pending") notes.push({ tone: "warn", text: t("tx.pendingNote") });
  if (txn.status === "Reversed") notes.push({ tone: "info", text: t("tx.reversedNote") });
  if (txn.status === "Declined") notes.push({ tone: "stop", text: t("tx.declinedNote") });
  if (txn.date_gap_days === 1) notes.push({ tone: "info", text: t("tx.gapNote") });
  if (txn.merchant_missing) notes.push({ tone: "mute", text: t("tx.unknownMerchantWhy") });

  const related: [keyof Detail["related"], Txn[]][] = [
    ["similar", detail.related.similar],
    ["same_merchant", detail.related.same_merchant],
    ["same_amount", detail.related.same_amount],
  ];

  return (
    <>
      <div>
        <div className="hero-amount">
          {signed(txn.amount, txn.currency, txn.direction, lang)}
        </div>
        <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 9 }}>
          <StatusBadge status={txn.status} t={t} />
          <span className="badge mute">{t(`type.${txn.type}`)}</span>
          <span className="badge mute">{t(`channel.${txn.channel}`)}</span>
          {txn.direction === "unknown" && <span className="badge info">{t("dir.unknown")}</span>}
        </div>
      </div>

      {notes.map((item) => (
        <div key={item.text} className={`notebox ${item.tone}`}>
          <b aria-hidden="true">i</b>
          <span>{item.text}</span>
        </div>
      ))}

      <dl className="dl">
        <dt>{t("tx.reference")}</dt><dd className="mono">{txn.reference}</dd>
        <dt>{t("tx.amount")}</dt>
        <dd className="num">{money(txn.amount, txn.currency, lang)} ({txn.currency})</dd>
        <dt>{t("tx.direction")}</dt><dd>{t(`dir.${txn.direction}`)}</dd>
        <dt>{t("tx.event")}</dt><dd>{formatDayTime(txn.occurred_at, lang)}</dd>
        <dt>{t("tx.process")}</dt><dd>{formatDay(txn.process_date, lang)}</dd>
        <dt>{t("tx.status")}</dt><dd>{t(`status.${txn.status}`)}</dd>
        <dt>{t("tx.product")}</dt>
        <dd>{detail.product
          ? `${t(`product.${detail.product.type}`)} · ${detail.product.masked}`
          : txn.product_reference}</dd>
        <dt>{t("tx.merchant")}</dt>
        <dd>{txn.merchant ?? <em style={{ color: "var(--ink-4)" }}>{t("tx.unknownMerchant")}</em>}</dd>
        <dt>{t("tx.category")}</dt>
        <dd>{txn.category ? t(`cat.${txn.category}`) : t("cat.__none__")}</dd>
        <dt>{t("tx.place")}</dt>
        <dd>{[txn.city, txn.country].filter(Boolean).join(", ") || "—"}</dd>
        {txn.response_code && <>
          <dt>{t("tx.response")}</dt><dd className="mono">{txn.response_code}</dd>
        </>}
      </dl>

      <div>
        <p className="eyebrow" style={{ marginBottom: 9 }}>{t("tx.journey")}</p>
        <div className="timeline">
          <Step index={0} title={t("tx.j1")} note={formatDayTime(txn.occurred_at, lang)} line />
          <Step index={1} title={t("tx.j2")} note={formatDay(txn.process_date, lang)} line />
          <Step index={2} title={t("tx.j3")}
                note={txn.status === "Approved" ? t("status.Approved")
                  : txn.status === "Pending" ? t("tx.pendingNote")
                  : txn.status === "Declined" ? t("tx.declinedNote") : t("tx.reversedNote")}
                tone={txn.status === "Approved" ? "" : txn.status === "Pending" ? "pending" : "stop"} />
        </div>
      </div>

      <div>
        <p className="eyebrow" style={{ marginBottom: 9 }}>{t("tx.related")}</p>
        {related.map(([key, list]) => (
          <div key={key} style={{ marginBottom: 12 }}>
            <p className="note note-strong">{t(`tx.rel.${key}`)}</p>
            {list.length === 0
              ? <p className="note">{t("tx.relNone")}</p>
              : <div className="rows">
                  {list.map((row, index) => (
                    <TxnRow key={row.reference} txn={row} onOpen={openTxn}
                            lang={lang} t={t} index={index} />
                  ))}
                </div>}
          </div>
        ))}
      </div>

      <Card>
        <p className="note">
          <span className="eyebrow">{detail.evidence.source}</span><br />
          <span className="mono">{detail.evidence.build_id}</span>
        </p>
      </Card>
    </>
  );
}

function Step(props: { index: number; title: string; note: string; line?: boolean; tone?: string }) {
  return (
    <div className="step" style={{ ["--i" as string]: props.index }}>
      <span className="step-mark">
        <i className={`step-dot ${props.tone ?? ""}`} style={{ ["--i" as string]: props.index }} />
        {props.line && <i className="step-line" style={{ ["--i" as string]: props.index }} />}
      </span>
      <span className="step-body">
        <span className="step-title">{props.title}</span>
        <span className="step-note">{props.note}</span>
      </span>
    </div>
  );
}
