import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Filters, Ledger, Overview, Txn } from "../types";
import { EMPTY_FILTERS, activeFilterCount } from "../types";
import { formatMonth, money, monthKey } from "../format";
import { Card, Empty, ErrorBox, Skeleton, TxnRow, useShell } from "../ui";

const FLAGS = ["pending", "reversed", "declined", "no_merchant",
               "no_category", "unknown_direction", "next_day", "unsettled"];
const SORTS = ["date_desc", "date_asc", "amount_desc", "amount_asc"];
const TYPES = ["Purchase", "Withdrawal", "Deposit", "Transfer", "Payment", "Adjustment"];
const STATUSES = ["Approved", "Pending", "Declined", "Reversed"];
const CHANNELS = ["ATM", "App", "Branch", "POS", "Transfer", "Web"];
const CATEGORIES = ["__none__", "Food", "Health", "Transport", "Services", "Entertainment", "Other"];

export default function Movements(props: {
  filters: Filters; setFilters: (filters: Filters) => void;
}) {
  const { filters, setFilters } = props;
  const { lang, t, openTxn, toast } = useShell();

  const [page, setPage] = useState<Ledger | null>(null);
  const [rows, setRows] = useState<Txn[]>([]);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const [error, setError] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const [products, setProducts] = useState<Overview["products"]>([]);
  const [draft, setDraft] = useState(filters.q);

  useEffect(() => { setDraft(filters.q); }, [filters.q]);

  useEffect(() => {
    api.overview().then((overview) => setProducts(overview.products)).catch(() => undefined);
  }, []);

  /* Typing must not fire a request per keystroke. */
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (draft === filters.q) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setFilters({ ...filters, q: draft }), 280);
    return () => window.clearTimeout(timer.current);
  }, [draft]);

  const key = JSON.stringify(filters);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    api.ledger(filters, 0, 40)
      .then((result) => {
        if (!alive) return;
        setPage(result);
        setRows(result.transactions);
      })
      .catch((caught) => alive && setError(caught?.message ?? "failed"))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [key]);

  async function loadMore() {
    if (!page?.next_offset) return;
    setMore(true);
    try {
      const next = await api.ledger(filters, page.next_offset, 40);
      setPage(next);
      setRows((current) => [...current, ...next.transactions]);
    } catch (caught: any) {
      toast(caught?.message ?? "failed", "bad");
    } finally {
      setMore(false);
    }
  }

  function toggleFlag(flag: string) {
    const flags = filters.flags.includes(flag)
      ? filters.flags.filter((item) => item !== flag)
      : [...filters.flags, flag];
    setFilters({ ...filters, flags });
  }

  const grouped = useMemo(() => {
    const map = new Map<string, Txn[]>();
    for (const row of rows) {
      const month = monthKey(row.event_date);
      if (!map.has(month)) map.set(month, []);
      map.get(month)!.push(row);
    }
    return [...map.entries()];
  }, [rows]);

  const currencies = useMemo(
    () => [...new Set(products.map((product) => product.currency))].sort(),
    [products]);
  const count = activeFilterCount(filters);
  const currency = rows[0]?.currency ?? "";
  const mixed = (page?.sums.currencies ?? 0) > 1;

  return (
    <>
      <header className="page-head reveal">
        <h1>{t("mov.title")}</h1>
        <p className="note">
          {t("mov.count", { shown: rows.length, total: page?.total ?? "—" })}
          {count > 0 && page && <> · {t("mov.matched", { n: page.matched })}</>}
          {" · "}{t("mov.dateNote")}
        </p>
      </header>

      <div className="toolbar reveal" style={{ ["--i" as string]: 1 }}>
        <label className="search">
          <input type="search" value={draft} placeholder={t("mov.search")}
                 aria-label={t("mov.search")}
                 onChange={(event) => setDraft(event.target.value)} />
        </label>
        <button className="chip" aria-pressed={showFilters}
                onClick={() => setShowFilters((open) => !open)}>
          <span aria-hidden="true">⚙</span>
          <span>{t("mov.filters")}</span>
          {count > 0 && <span className="n">{count}</span>}
        </button>
        <select aria-label={t("mov.sort")} value={filters.sort} style={{ width: "auto" }}
                onChange={(event) => setFilters({ ...filters, sort: event.target.value })}>
          {SORTS.map((sort) => (
            <option key={sort} value={sort}>{t(`mov.sort.${sort}`)}</option>
          ))}
        </select>
        <button className="btn ghost sm"
                onClick={() => api.downloadCsv(filters, "savia-movements.csv")
                  .then(() => toast(t("mov.export") + " ✓"))
                  .catch(() => toast(t("err.title"), "bad"))}>
          ↧ {t("mov.export")}
        </button>
        {count > 0 && (
          <button className="linkbtn" onClick={() => setFilters(EMPTY_FILTERS)}>
            {t("mov.clear")}
          </button>
        )}
      </div>

      <div className="chips reveal" style={{ ["--i" as string]: 2, marginBottom: 13 }}>
        {currencies.length > 1 && currencies.map((code) => (
          <button key={code} className="chip" aria-pressed={filters.currency === code}
                  onClick={() => setFilters({
                    ...filters, currency: filters.currency === code ? "" : code })}>
            {code}
          </button>
        ))}
        {FLAGS.map((flag) => (
          <button key={flag} className="chip" aria-pressed={filters.flags.includes(flag)}
                  onClick={() => toggleFlag(flag)}>{t(`flag.${flag}`)}</button>
        ))}
      </div>

      {showFilters && (
        <div className="filters">
          <Select label={t("f.product")} value={filters.product} t={t}
                  options={products.map((p) => [p.reference,
                    `${t(`product.${p.type}`)} · ${p.masked}`])}
                  onChange={(value) => setFilters({ ...filters, product: value })} />
          <Select label={t("f.type")} value={filters.type} t={t}
                  options={TYPES.map((v) => [v, t(`type.${v}`)])}
                  onChange={(value) => setFilters({ ...filters, type: value })} />
          <Select label={t("f.status")} value={filters.status} t={t}
                  options={STATUSES.map((v) => [v, t(`status.${v}`)])}
                  onChange={(value) => setFilters({ ...filters, status: value })} />
          <Select label={t("f.channel")} value={filters.channel} t={t}
                  options={CHANNELS.map((v) => [v, t(`channel.${v}`)])}
                  onChange={(value) => setFilters({ ...filters, channel: value })} />
          <Select label={t("f.category")} value={filters.category} t={t}
                  options={CATEGORIES.map((v) => [v, t(`cat.${v}`)])}
                  onChange={(value) => setFilters({ ...filters, category: value })} />
          <Select label={t("f.direction")} value={filters.direction} t={t}
                  options={[["debit", t("dir.debit")], ["credit", t("dir.credit")],
                            ["unknown", t("dir.unknown")]]}
                  onChange={(value) => setFilters({ ...filters, direction: value })} />
          <Field label={t("f.from")}>
            <input type="date" value={filters.date_from}
                   onChange={(event) => setFilters({ ...filters, date_from: event.target.value })} />
          </Field>
          <Field label={t("f.to")}>
            <input type="date" value={filters.date_to}
                   onChange={(event) => setFilters({ ...filters, date_to: event.target.value })} />
          </Field>
          <Field label={t("f.min")}>
            <input type="number" inputMode="decimal" value={filters.min_amount}
                   onChange={(event) => setFilters({ ...filters, min_amount: event.target.value })} />
          </Field>
          <Field label={t("f.max")}>
            <input type="number" inputMode="decimal" value={filters.max_amount}
                   onChange={(event) => setFilters({ ...filters, max_amount: event.target.value })} />
          </Field>
        </div>
      )}

      {page && (
        <div className="summary reveal" style={{ ["--i" as string]: 3 }}>
          <span className="summary-item">
            <span>{t("mov.results")}</span>
            <b className="num">{page.matched}</b>
          </span>
          {!mixed && currency && (
            <>
              <span className="summary-item">
                <span>{t("mov.inflow")}</span>
                <b className="num" style={{ color: "var(--in)" }}>
                  {money(page.sums.inflow, currency, lang)}</b>
              </span>
              <span className="summary-item">
                <span>{t("mov.outflow")}</span>
                <b className="num" style={{ color: "var(--out)" }}>
                  {money(page.sums.outflow, currency, lang)}</b>
              </span>
              {page.sums.undetermined > 0 && (
                <span className="summary-item">
                  <span>{t("mov.undetermined")}</span>
                  <b className="num" style={{ color: "var(--none)" }}>
                    {money(page.sums.undetermined, currency, lang)}</b>
                </span>
              )}
            </>
          )}
          {mixed && <span className="note">{t("mov.mixed")}</span>}
        </div>
      )}

      {error && <ErrorBox message={error} t={t} onRetry={() => setFilters({ ...filters })} />}
      {loading && <Skeleton kind="row" count={8} />}

      {!loading && rows.length === 0 && !error && (
        <Card>
          <Empty glyph="⌕" title={t("mov.empty")} />
        </Card>
      )}

      {!loading && grouped.map(([month, items]) => (
        <section key={month}>
          <div className="month-head">
            <span className="eyebrow">{formatMonth(month, lang)}</span>
            <span className="note num">{items.length}</span>
          </div>
          <div className="rows">
            {items.map((txn, index) => (
              <TxnRow key={txn.reference} txn={txn} onOpen={openTxn}
                      lang={lang} t={t} index={Math.min(index, 12)} />
            ))}
          </div>
        </section>
      ))}

      {!loading && rows.length > 0 && (
        <div style={{ display: "grid", placeItems: "center", marginTop: 22 }}>
          {page?.next_offset
            ? <button className="btn ghost" onClick={loadMore} disabled={more}>
                {more ? t("mov.loading") : t("mov.more")}
              </button>
            : <p className="note">{t("mov.end")}</p>}
        </div>
      )}
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

function Select(props: {
  label: string; value: string; options: [string, string][];
  onChange: (value: string) => void; t: (key: string) => string;
}) {
  return (
    <Field label={props.label}>
      <select value={props.value} onChange={(event) => props.onChange(event.target.value)}>
        <option value="">{props.t("f.all")}</option>
        {props.options.map(([value, label]) => (
          <option key={value} value={value}>{label}</option>
        ))}
      </select>
    </Field>
  );
}
