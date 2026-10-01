import { useEffect, useState } from "react";
import { api } from "../api";
import type { Review, Snapshot } from "../types";
import { count, percent } from "../format";
import { Card, ErrorBox, Skeleton, useShell } from "../ui";

/* Each rule is stated with the number it produced over the whole published
 * snapshot, including the ones that produced nothing. A rule that finds zero is
 * reported as zero rather than quietly dropped. */
const RULES: { metric: string; label: Record<string, string> }[] = [
  { metric: "no_merchant", label: {
      es: "Movimientos sin comercio informado",
      pt: "Lançamentos sem estabelecimento informado",
      en: "Rows with no merchant reported" } },
  { metric: "no_category", label: {
      es: "Movimientos sin categoría informada",
      pt: "Lançamentos sem categoria informada",
      en: "Rows with no category reported" } },
  { metric: "next_day_event", label: {
      es: "Evento registrado un día después del proceso",
      pt: "Evento registrado um dia após o processamento",
      en: "Event recorded a day after processing" } },
  { metric: "pending", label: {
      es: "Movimientos pendientes", pt: "Lançamentos pendentes", en: "Pending rows" } },
  { metric: "reversed", label: {
      es: "Movimientos reversados", pt: "Lançamentos estornados", en: "Reversed rows" } },
  { metric: "declined", label: {
      es: "Intentos rechazados", pt: "Tentativas recusadas", en: "Declined attempts" } },
  { metric: "similar_charge_pairs_72h", label: {
      es: "Mismo comercio, monto y moneda en 72 horas",
      pt: "Mesmo estabelecimento, valor e moeda em 72 horas",
      en: "Same merchant, amount and currency within 72 hours" } },
  { metric: "distinct_merchant_names", label: {
      es: "Nombres de comercio distintos en todo el snapshot",
      pt: "Nomes de estabelecimento distintos em todo o snapshot",
      en: "Distinct merchant names in the whole snapshot" } },
];

export default function DataRoom() {
  const { lang, t } = useShell();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [reviews, setReviews] = useState<Review[] | null>(null);
  const [error, setError] = useState("");

  function load() {
    setError("");
    Promise.all([api.snapshot(), api.reviews()])
      .then(([snap, list]) => { setSnapshot(snap); setReviews(list); })
      .catch((caught) => setError(caught?.message ?? "failed"));
  }

  useEffect(load, []);

  if (error) return <ErrorBox message={error} onRetry={load} t={t} />;
  if (!snapshot) return <Skeleton kind="card" count={3} />;

  const totals = snapshot.totals;
  const all = totals.transactions || 1;

  return (
    <>
      <header className="page-head reveal">
        <h1>{t("data.title")}</h1>
        <p className="note">{t("data.lead")}</p>
      </header>

      <div className="split">
        <div>
          <Card title={t("data.rules")} index={1}>
            <div className="rows">
              {RULES.map((rule, index) => {
                const value = totals[rule.metric] ?? 0;
                const share = ["no_merchant", "no_category", "next_day_event",
                               "pending", "reversed", "declined"].includes(rule.metric);
                return (
                  <div key={rule.metric} className="clearrow reveal"
                       style={{ ["--i" as string]: index, padding: "9px 0",
                                borderBottom: "1px solid var(--hairline)" }}>
                    <span className={value ? "tick" : ""} aria-hidden="true">
                      {value ? "•" : "✓"}
                    </span>
                    <span style={{ color: "var(--ink-2)" }}>
                      {rule.label[lang] ?? rule.label.en}
                    </span>
                    <b className="num" style={{ color: value ? "var(--ink)" : "var(--in)" }}>
                      {count(value, lang)}
                      {share && value > 0 && (
                        <span className="note"> · {percent(value / all, lang, 2)}</span>
                      )}
                    </b>
                  </div>
                );
              })}
            </div>
            <p className="note" style={{ marginTop: 13 }}>
              {count(all, lang)} {t("gate.txns")}.
            </p>
          </Card>

          <Card title={t("data.pipeline")} index={2}>
            <div className="timeline">
              {["p1", "p2", "p3", "p4"].map((key, index, list) => (
                <div className="step" key={key} style={{ ["--i" as string]: index }}>
                  <span className="step-mark">
                    <i className="step-dot" style={{ ["--i" as string]: index }} />
                    {index < list.length - 1 && (
                      <i className="step-line" style={{ ["--i" as string]: index }} />
                    )}
                  </span>
                  <span className="step-body">
                    <span className="step-title">{t(`data.${key}`)}</span>
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div>
          <Card title={t("data.build")} index={1}>
            <dl className="dl">
              {["build_id", "source_fingerprint", "snapshot_created_at",
                "first_process_date", "last_process_date", "last_event_date",
                "serving_built_at", "lake_path"].map((key) => (
                snapshot.build[key] ? (
                  <div key={key} style={{ display: "contents" }}>
                    <dt>{key.replace(/_/g, " ")}</dt>
                    <dd className="mono">{snapshot.build[key]}</dd>
                  </div>
                ) : null
              ))}
            </dl>
          </Card>

          <Card title={t("data.isNot")} index={2}>
            <ul className="notdone" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {["n1", "n2", "n3", "n4"].map((key) => (
                <li key={key}>
                  <span className="x" aria-hidden="true">✕</span>
                  <span>{t(`data.${key}`)}</span>
                </li>
              ))}
            </ul>
          </Card>

          <Card title={t("rec.mine")} index={3}>
            {!reviews && <Skeleton kind="text" count={2} />}
            {reviews?.length === 0 && <p className="note">{t("rec.none")}</p>}
            <div className="rows">
              {reviews?.map((review, index) => (
                <div key={review.id} className="reveal" style={{
                  ["--i" as string]: index, padding: "10px 0",
                  borderTop: index ? "1px solid var(--hairline)" : "none" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <b className="mono">{review.id}</b>
                    <span className={`badge ${review.priority === "security" ? "stop" : "info"}`}>
                      {t(`rev.reason.${review.reason}`) !== `rev.reason.${review.reason}`
                        ? t(`rev.reason.${review.reason}`)
                        : review.reason}
                    </span>
                  </div>
                  <p className="note">{review.created_at}</p>
                  <p className="note mono" style={{ overflowWrap: "anywhere" }}>
                    {review.evidence.facts_sha256.slice(0, 24)}…
                  </p>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
