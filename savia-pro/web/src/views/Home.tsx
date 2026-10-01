import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Overview, Signals } from "../types";
import { compact, formatDay, formatMonth, money, percent } from "../format";
import { useCountUp } from "../motion";
import { FlowChart, Meter, Sparkline, type FlowSeries } from "../charts";
import { Card, ErrorBox, Skeleton, TxnRow, useShell } from "../ui";

/** Maps a signal to the ledger filter that reproduces it, so "worth a look"
 *  is never a dead end: every count is clickable and lands on the same rows. */
const SIGNAL_TO_FLAG: Record<string, string | null> = {
  pending: "pending", reversed: "reversed", declined: "declined",
  next_day: "next_day", no_merchant: "no_merchant", fx: "fx",
  inactive_product: null, similar_charge: null,
};

const SIGNAL_TONE: Record<string, string> = {
  pending: "warn", reversed: "info", declined: "stop",
  next_day: "info", no_merchant: "mute", fx: "warn",
  inactive_product: "mute", similar_charge: "mute",
};

function BalanceCard({ bucket, series, index }: {
  bucket: Overview["balances"][number];
  series: Overview["series"][string] | undefined;
  index: number;
}) {
  const { lang, t } = useShell();
  const headline = bucket.deposit === null || bucket.investment === null
    ? null : bucket.deposit + bucket.investment;
  const shown = useCountUp(headline ?? 0, 1100);
  const utilisation = bucket.credit !== null && bucket.credit_limit !== null && bucket.credit_limit > 0
    ? bucket.credit / bucket.credit_limit : null;
  const net = (series ?? []).map((point) => point.inflow - point.outflow);

  return (
    <div className="kpi reveal" style={{ ["--i" as string]: index }}>
      <div className="eyebrow">{bucket.currency}</div>
      <div className="kpi-value">{money(headline === null ? null : shown, bucket.currency, lang)}</div>
      <div className="kpi-sub">{t("home.deposits")} + {t("home.investment")}</div>
      {net.length > 1 && <div style={{ marginTop: 10 }}><Sparkline values={net} /></div>}
      {(bucket.credit === null || bucket.credit > 0) && (
        <div style={{ marginTop: 12 }}>
          {utilisation !== null && bucket.credit !== null && bucket.credit_limit !== null
            ? <Meter label={t("home.credit")} value={bucket.credit} of={bucket.credit_limit}
                     caption={`${money(bucket.credit, bucket.currency, lang)} · ${percent(utilisation, lang, 0)}`}
                     tone="warn" index={index} />
            : <div className="kpi-row">
                <span>{t("home.credit")}</span>
                <b>{money(bucket.credit, bucket.currency, lang)}</b>
              </div>}
        </div>
      )}
    </div>
  );
}

export default function Home({ onAlias }: { onAlias: (alias: string) => void }) {
  const { lang, t, openTxn, go } = useShell();
  const [data, setData] = useState<Overview | null>(null);
  const [signals, setSignals] = useState<Signals | null>(null);
  const [error, setError] = useState("");
  const [currency, setCurrency] = useState("");
  const generation = useRef(0);

  function load() {
    const current = ++generation.current;
    setError("");
    Promise.all([api.overview(), api.signals()])
      .then(([overview, found]) => {
        if (current !== generation.current) return;
        setData(overview);
        setSignals(found);
        setCurrency(overview.currencies[0] ?? "");
        onAlias(overview.customer.alias);
      })
      .catch((caught) => {
        if (current === generation.current) setError(caught?.message ?? "failed");
      });
  }

  useEffect(() => {
    load();
    return () => { generation.current += 1; };
  }, []);

  const points = useMemo(() => (currency ? data?.series[currency] ?? [] : []), [data, currency]);

  const [hidden, setHidden] = useState<string[]>([]);

  const allSeries: FlowSeries[] = useMemo(() => {
    const base: FlowSeries[] = [
      { key: "in", label: t("mov.inflow"), tone: "in", values: points.map((p) => p.inflow) },
      { key: "out", label: t("mov.outflow"), tone: "out", values: points.map((p) => p.outflow) },
    ];
    if (points.some((p) => p.undetermined > 0)) {
      base.push({ key: "none", label: t("mov.undetermined"), tone: "none",
                  values: points.map((p) => p.undetermined) });
    }
    return base;
  }, [points, t]);

  const flowSeries = useMemo(
    () => allSeries.filter((s) => !hidden.includes(s.key)),
    [allSeries, hidden]);

  if (error) return <ErrorBox message={error} onRetry={load} t={t} />;
  if (!data) {
    return (
      <>
        <div className="kpis" style={{ marginBottom: 16 }}>
          <div className="sk sk-card" /><div className="sk sk-card" />
        </div>
        <Skeleton kind="row" count={6} />
      </>
    );
  }

  const lastProcess = String(data.stats.last_process_date ?? "");

  return (
    <>
      <header className="page-head reveal">
        <h1>{t("home.greeting", { name: data.customer.alias.split(" ")[0] })}</h1>
        <p className="note">
          {t("home.asof", { date: lastProcess ? formatDay(lastProcess, lang) : "—" })}
          {" · "}
          <span className="num">{data.stats.transactions}</span> {t("gate.stat.tx")}
        </p>
      </header>

      <div className="kpis" style={{ marginBottom: 16 }}>
        {data.balances.map((bucket, index) => (
          <BalanceCard key={bucket.currency} bucket={bucket}
                       series={data.series[bucket.currency]} index={index} />
        ))}
      </div>
      <p className="note" style={{ marginBottom: 20, maxWidth: "80ch" }}>{t("home.balanceNote")}</p>

      <div className="split">
        <div>
          <Card title={t("home.flow")} note={t("home.flowNote")} index={1}
                aside={data.currencies.length > 1 ? (
                  <div className="seg" role="group" aria-label={t("f.currency")}>
                    {data.currencies.map((code) => (
                      <button key={code} aria-pressed={code === currency}
                              onClick={() => setCurrency(code)}>{code}</button>
                    ))}
                  </div>
                ) : null}>
            {points.length > 1 ? (
              <>
                {flowSeries.length > 0
                  ? <FlowChart labels={points.map((p) => formatMonth(p.month, lang, true).split(" ")[0])}
                               series={flowSeries}
                               format={(value) => money(value, currency, lang)}
                               labelFor={(index) => formatMonth(points[index].month, lang)} />
                  : <p className="note" style={{ padding: "40px 0", textAlign: "center" }}>
                      {t("mov.empty")}</p>}
                <div className="legend">
                  {allSeries.map((s) => (
                    <button key={s.key} aria-pressed={!hidden.includes(s.key)}
                            onClick={() => setHidden((current) => current.includes(s.key)
                              ? current.filter((item) => item !== s.key)
                              : [...current, s.key])}>
                      <i className={`tone-${s.tone}`} />{s.label}
                    </button>
                  ))}
                </div>
              </>
            ) : <Empty t={t} />}
          </Card>

          <Card title={t("home.recent")} index={2}
                aside={<button className="linkbtn" onClick={() => go("movements")}>
                  {t("home.seeAll")} →
                </button>}>
            <div className="rows">
              {data.recent.map((txn, index) => (
                <TxnRow key={txn.reference} txn={txn} onOpen={openTxn}
                        lang={lang} t={t} index={index} />
              ))}
            </div>
          </Card>
        </div>

        <div>
          <Card title={t("home.attention")} note={t("home.attentionNote")} index={1}>
            {!signals && <Skeleton kind="row" count={4} />}
            <div className="rows">
              {signals?.found.map((signal, index) => {
                const flag = SIGNAL_TO_FLAG[signal.kind];
                return (
                  <button key={signal.kind} className="signal reveal"
                          style={{ ["--i" as string]: index }}
                          onClick={() => flag
                            ? go("movements", { flags: [flag] })
                            : openTxn(signal.examples[0]?.reference ?? "")}>
                    <span className={`signal-mark badge ${SIGNAL_TONE[signal.kind] ?? "mute"}`}>!</span>
                    <span>
                      <span className="signal-title">{t(`flag.${signal.kind}`)}</span>
                      <span className="signal-rule">
                        {signal.examples[0]
                          ? `${signal.examples[0].merchant ?? t("tx.unknownMerchant")} · ${
                              money(signal.examples[0].amount, signal.examples[0].currency, lang)}`
                          : t("misc.rule")}
                      </span>
                    </span>
                    <span className="signal-count num">{signal.count}</span>
                  </button>
                );
              })}
            </div>
          </Card>

          {signals && signals.clear.length > 0 && (
            <Card title={t("home.clearTitle")} note={t("home.clearNote")} index={2}>
              <div className="clearlist">
                {signals.clear.map((signal) => (
                  <div className="clearrow" key={signal.kind}>
                    <span className="tick" aria-hidden="true">✓</span>
                    <span>{t(`flag.${signal.kind}`)}</span>
                    <b>{t("misc.none")}</b>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Card title={t("home.products")} index={3}>
            <div className="product-grid">
              {data.products.map((product, index) => (
                <button key={product.reference} className="product reveal"
                        style={{ ["--i" as string]: index }}
                        onClick={() => go("movements", { product: product.reference })}>
                  <span className="product-top">
                    <span>
                      <span className="product-type">{t(`product.${product.type}`)}</span><br />
                      <span className="product-mask">{product.masked} · {product.currency}</span>
                    </span>
                    {product.status !== "Active" && (
                      <span className={`badge ${product.status === "Blocked" ? "stop" : "mute"}`}>
                        {t(`pstatus.${product.status}`)}
                      </span>
                    )}
                  </span>
                  <span className="product-amount">
                    {money(product.balance, product.currency, lang)}
                  </span>
                  <span className="product-foot">
                    <span>
                      {product.balance_kind === "credit" ? t("home.credit")
                        : product.balance_kind === "investment" ? t("home.investment")
                        : t("home.deposits")}
                    </span>
                    {product.available !== null && (
                      <span>{compact(product.available, lang)} {t("home.available")}</span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function Empty({ t }: { t: (key: string) => string }) {
  return <p className="note">{t("mov.empty")}</p>;
}
