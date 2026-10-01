import { useEffect, useState } from "react";
import { api } from "../api";
import type { Insights as InsightsData } from "../types";
import { compact, count, formatDay, money, percent } from "../format";
import { BarList, Donut, Meter, SpreadBar, type Slice } from "../charts";
import { Card, ErrorBox, Skeleton, useShell } from "../ui";

const TONES = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];

export default function Insights() {
  const { lang, t, go } = useShell();
  const [data, setData] = useState<InsightsData | null>(null);
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [error, setError] = useState("");

  function load(code?: string) {
    setError("");
    api.insights(code)
      .then((result) => { setData(result); setCurrency(result.currency ?? undefined); })
      .catch((caught) => setError(caught?.message ?? "failed"));
  }

  useEffect(() => { load(currency); }, [currency]);

  if (error) return <ErrorBox message={error} onRetry={() => load(currency)} t={t} />;
  if (!data) return <Skeleton kind="card" count={3} />;

  const code = data.currency ?? "";

  /* The missing category is kept as its own slice. Dropping it would make the
   * chart look tidy and the data look better than it is. */
  const known = data.categories.filter((row) => row.category !== "__none__");
  const unknown = data.categories.find((row) => row.category === "__none__");
  const total = data.categories.reduce((sum, row) => sum + row.total, 0);

  const slices: Slice[] = known.map((row, index) => ({
    key: row.category, label: t(`cat.${row.category}`),
    value: row.total, tone: TONES[index % TONES.length],
  }));
  if (unknown) {
    slices.push({ key: "__none__", label: t("cat.__none__"), value: unknown.total, tone: "cnone" });
  }

  return (
    <>
      <header className="page-head reveal">
        <h1>{t("ins.title")}</h1>
        <p className="note">{t("ins.lead")}</p>
      </header>

      <div className="split">
        <Card title={t("ins.categories")} note={t("ins.categoriesNote")} index={1}
              aside={data.currencies.length > 1 ? (
                <div className="seg" role="group" aria-label={t("f.currency")}>
                  {data.currencies.map((item) => (
                    <button key={item} aria-pressed={item === code}
                            onClick={() => setCurrency(item)}>{item}</button>
                  ))}
                </div>
              ) : null}>
          <Donut slices={slices} total={total}
                 centreTop={compact(total, lang)} centreBottom={t("ins.outflow")} />
          <div className="swatches">
            {slices.map((slice) => (
              <div key={slice.key}
                   className={`swatch ${slice.key === "__none__" ? "is-none" : ""}`}>
                <i className={`sw-${slice.tone}`} />
                <span>{slice.label}</span>
                <b>{money(slice.value, code, lang)} · {percent(total ? slice.value / total : 0, lang, 1)}</b>
              </div>
            ))}
          </div>
        </Card>

        <div>
          <Card title={t("ins.completeness")} note={t("ins.completenessNote")} index={1}>
            <div className="meters">
              {data.completeness.map((row, index) => (
                <Meter key={row.metric} label={t(`ins.m.${row.metric}`)}
                       value={row.count} of={row.of} index={index}
                       tone={row.metric === "no_merchant" ? "warn"
                         : row.metric === "unsettled" ? "stop" : "info"}
                       caption={`${count(row.count, lang)} / ${count(row.of, lang)} · ${
                         percent(row.of ? row.count / row.of : 0, lang, 1)}`} />
              ))}
            </div>
          </Card>

          <Card title={t("ins.channels")} index={2}>
            <BarList rows={data.channels.map((row) => ({
              key: row.channel, label: t(`channel.${row.channel}`),
              value: row.count, caption: count(row.count, lang), tone: "brand",
            }))} />
          </Card>
        </div>
      </div>

      <div className="grid g2" style={{ marginTop: 15 }}>
        <Card title={t("ins.merchants")} note={t("ins.merchantsNote")} index={2}>
          {data.merchants.length === 0
            ? <p className="note">{t("mov.empty")}</p>
            : <BarList rows={data.merchants.map((row) => ({
                key: row.merchant, label: row.merchant, value: row.total,
                caption: money(row.total, code, lang), tone: "brand",
              }))} />}
        </Card>

        <Card title={t("ins.repeat")} note={t("ins.repeatNote")} index={3}>
          {data.repeat_merchants.length === 0
            ? <p className="note">{t("mov.empty")}</p>
            : <div className="rows">
                {data.repeat_merchants.map((row, index) => (
                  <div key={row.merchant + row.currency} className="reveal"
                       style={{ ["--i" as string]: index, padding: "11px 0" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                      <button className="linkbtn" style={{ textAlign: "left" }}
                              onClick={() => go("movements", { q: row.merchant })}>
                        {row.merchant}
                      </button>
                      <span className="note num">
                        {t("ins.times", { n: row.occurrences, m: row.months })}
                      </span>
                    </div>
                    {row.amount_is_constant
                      ? <p className="note">{t("ins.constant")} · {money(row.avg_amount, row.currency, lang)}</p>
                      : <>
                          <p className="note">
                            {t("ins.spread", {
                              lo: money(row.min_amount, row.currency, lang),
                              hi: money(row.max_amount, row.currency, lang),
                            })}
                          </p>
                          <SpreadBar min={row.min_amount} avg={row.avg_amount} max={row.max_amount}
                                     format={(value) => compact(value, lang)} />
                        </>}
                    <p className="note" style={{ marginTop: 4 }}>
                      {formatDay(row.last_seen, lang)}
                    </p>
                  </div>
                ))}
              </div>}
        </Card>
      </div>
    </>
  );
}
