import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  ArrowDownLeft,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  CreditCard,
  Eye,
  EyeOff,
  FileText,
  Fingerprint,
  Globe2,
  Home,
  Leaf,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Menu,
  MessageCircle,
  Search,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Wallet,
  X,
} from "lucide-react";
import type {
  ChatMessage,
  ChatStatus,
  Overview,
  Product,
  Profile,
  Transaction,
} from "./types";
import {
  api,
  ApiError,
  categoryNames,
  csv,
  date,
  label,
  money,
  number,
  productShort,
  statusNames,
  typeNames,
} from "./lib";

type Page = "home" | "products" | "transactions";
const nav = [
  { id: "home" as Page, label: "Inicio", icon: Home },
  { id: "products" as Page, label: "Mis productos", icon: Wallet },
  { id: "transactions" as Page, label: "Movimientos", icon: ArrowDownLeft },
];

function Brand({ inverse = false }: { inverse?: boolean }) {
  return (
    <span className={`brand ${inverse ? "inverse" : ""}`}>
      <span className="brand-icon">
        <Leaf size={23} strokeWidth={2.2} />
      </span>
      savia<span className="brand-dot">.</span>
    </span>
  );
}
function Avatar({ name, small = false }: { name: string; small?: boolean }) {
  return (
    <span className={`avatar ${small ? "small" : ""}`}>
      {name
        .split(" ")
        .slice(0, 2)
        .map((n) => n[0])
        .join("")}
    </span>
  );
}
function Badge({ status }: { status: string }) {
  return (
    <span className={`badge ${status.toLowerCase()}`}>
      <span />
      {statusNames[status] || status}
    </span>
  );
}
function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <FileText size={28} />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function TxIcon({ transaction }: { transaction: Transaction }) {
  const Icon =
    transaction.type === "Purchase"
      ? CreditCard
      : transaction.direction === "credit"
        ? ArrowDownLeft
        : transaction.type === "Withdrawal"
          ? Wallet
          : ArrowUpRight;
  return (
    <span className={`transaction-icon ${transaction.direction}`}>
      <Icon size={19} />
    </span>
  );
}
function Amount({ t, hidden }: { t: Transaction; hidden?: boolean }) {
  return (
    <span
      className={`amount ${t.direction === "credit" && t.status === "Approved" ? "incoming" : ""}`}
    >
      {!hidden && t.direction !== "unknown" && t.status === "Approved"
        ? t.direction === "credit"
          ? "+"
          : "−"
        : ""}
      {money(t.amount, t.currency, hidden)}
      <small>{t.currency}</small>
    </span>
  );
}

function Login({
  onLogin,
  notice,
}: {
  onLogin: (mode: "demo" | "invite") => void;
  notice: string;
}) {
  const [profiles, setProfiles] = useState<Profile[]>([]),
    [mode, setMode] = useState<"loading" | "demo" | "invite">("loading"),
    [profileId, setProfileId] = useState(""),
    [code, setCode] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    setMode("loading");
    api<{ mode?: "demo" | "invite"; profiles: Profile[] }>(
      "/api/auth/profiles",
      { signal: AbortSignal.timeout(8000) },
    )
      .then((r) => {
        setMode(r.mode === "invite" ? "invite" : "demo");
        setProfiles(r.profiles);
        setProfileId(r.profiles[0]?.id || "");
      })
      .catch(() =>
        setError(
          "La conexión con los datos no está disponible. Intenta de nuevo.",
        ),
      );
  }, []);
  useEffect(load, [load]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(mode === "invite" ? "/api/auth/invite" : "/api/auth/login", {
        method: "POST",
        body: JSON.stringify(
          mode === "invite" ? { code } : { profile: profileId, code },
        ),
      });
      onLogin(mode === "invite" ? "invite" : "demo");
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? "El código no es correcto. Revisa e intenta de nuevo."
          : e instanceof Error
            ? e.message
            : "No pudimos iniciar tu sesión.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-page">
      <section className="login-story">
        <Brand inverse />
        <div className="story-content">
          <span className="eyebrow light">
            <span className="live-dot" />
            TU BANCA, A TU RITMO
          </span>
          <h1>
            Tu dinero.
            <br />
            Tus planes.
            <br />
            <em>Tu tranquilidad.</em>
          </h1>
          <p>
            Una forma más clara de ver tus finanzas.
            <br />
            Todo lo que necesitas, en un solo lugar.
          </p>
          <div className="login-art" aria-hidden="true">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <div className="orbit orbit-three" />
            <div className="art-card">
              <div>
                <Leaf size={27} />
                <span>savia.</span>
              </div>
              <span className="art-card-line" />
              <span className="art-card-line short" />
              <div className="art-card-bottom">
                <span>Tu mundo, conectado</span>
                <Globe2 size={25} />
              </div>
            </div>
            <div className="art-float">
              <span>
                <Check size={15} />
              </span>
              Todo en su lugar
            </div>
          </div>
        </div>
        <div className="story-footer">
          <span>Hecho para moverte con confianza.</span>
          <span>LATAM ↗</span>
        </div>
      </section>
      <section className="login-form-side">
        <div className="mobile-brand">
          <Brand />
        </div>
        <span className="login-demo">
          <span className="live-dot" />
          FACTORED HACKATHON 2026
        </span>
        <div className="login-form-wrap">
          <span className="login-lock">
            <LockKeyhole size={24} />
          </span>
          <h2>
            {mode === "invite" ? "Tu acceso, solo tuyo." : "Qué bueno verte."}
          </h2>
          <p className="login-intro">
            {mode === "invite"
              ? "Ingresa la invitación que recibiste para explorar tu espacio."
              : "Entra a tu espacio personal."}
          </p>
          {mode === "loading" ? (
            <div className="login-loading">
              {error ? (
                <p className="form-error" role="alert">
                  {error}{" "}
                  <button type="button" className="text-button" onClick={load}>
                    Reintentar
                  </button>
                </p>
              ) : (
                <>
                  <LoaderCircle size={18} className="spin" /> Preparando tu
                  acceso…
                </>
              )}
            </div>
          ) : (
            <form onSubmit={submit}>
              {mode === "demo" && (
                <>
                  <label className="field-label">
                    Elige un perfil de demostración
                  </label>
                  <div className="profile-options">
                    {profiles.map((p) => (
                      <button
                        type="button"
                        key={p.id}
                        className={`profile-option ${profileId === p.id ? "selected" : ""}`}
                        onClick={() => setProfileId(p.id || "")}
                      >
                        <Avatar name={p.alias} small />
                        <span>
                          <strong>{p.alias}</strong>
                          <small>
                            {p.country} · {p.primary_currency}
                          </small>
                        </span>
                        <span className="radio-mark">
                          {profileId === p.id && <span />}
                        </span>
                      </button>
                    ))}
                  </div>
                </>
              )}
              <label className="field-label" htmlFor="login-code">
                {mode === "invite"
                  ? "Código de invitación"
                  : "Código de acceso"}
              </label>
              <div className="input-with-icon">
                <LockKeyhole size={18} />
                <input
                  id="login-code"
                  type="password"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder={
                    mode === "invite"
                      ? "Pega tu invitación"
                      : "Ingresa tu código"
                  }
                  autoComplete={
                    mode === "invite" ? "one-time-code" : "current-password"
                  }
                  required
                  maxLength={128}
                />
              </div>
              {error && (
                <p className="form-error" role="alert">
                  {error}
                </p>
              )}
              <button
                className="button primary login-submit"
                disabled={busy || (mode === "demo" && !profileId)}
              >
                {busy ? (
                  <LoaderCircle className="spin" size={19} />
                ) : (
                  <>
                    Entrar a mi banca
                    <ArrowRight size={18} />
                  </>
                )}
              </button>
            </form>
          )}
          <div className="login-trust">
            <ShieldCheck size={17} />
            <span>Sesión privada · Acceso de solo lectura</span>
          </div>
          {notice && (
            <p className="login-warning" role="alert">
              {notice}
            </p>
          )}
          <p className="login-disclosure">
            {mode === "invite"
              ? "Prototipo con datos sintéticos creados por el equipo. Cada invitación abre un único perfil ficticio."
              : "Experiencia de demostración con los datos sintéticos del hackathon. Los nombres son alias; los productos y movimientos provienen del dataset."}
          </p>
        </div>
        <footer className="login-footer">
          <span>© 2026 Savia</span>
          <span>Tu dinero, en calma.</span>
        </footer>
      </section>
    </div>
  );
}

function ProductCard({
  product,
  hidden,
  onSelect,
  index = 0,
}: {
  product: Product;
  hidden: boolean;
  onSelect: () => void;
  index?: number;
}) {
  const credit = /cr[eé]dito|credit|pr[eé]stamo|hipotec/i.test(product.type),
    investment = /inver|plazo|cdt/i.test(product.type);
  return (
    <button
      className={`product-card product-tone-${index % 3}`}
      onClick={onSelect}
    >
      <div className="product-card-top">
        <span className="product-icon">
          {credit ? (
            <CreditCard size={20} />
          ) : investment ? (
            <Leaf size={20} />
          ) : (
            <Wallet size={20} />
          )}
        </span>
        <ChevronRight size={18} />
      </div>
      <span className="product-name">{productShort(product.type)}</span>
      <span className="product-ref">
        Ref. {product.reference.slice(-6).toUpperCase()} <span>·</span>{" "}
        {product.currency}
      </span>
      <div className="product-card-bottom">
        <span>
          <small>{credit ? "Saldo del producto" : "Saldo en cuenta"}</small>
          <strong>{money(product.balance, product.currency, hidden)}</strong>
        </span>
        <Badge status={product.status} />
      </div>
    </button>
  );
}

function BankingCard({
  product,
  alias,
  hidden,
  onClick,
}: {
  product: Product;
  alias: string;
  hidden: boolean;
  onClick: () => void;
}) {
  return (
    <button className="banking-card" onClick={onClick}>
      <div className="bank-card-brand">
        <span>savia.</span>
        <span>{product.currency}</span>
      </div>
      <div className="bank-card-orbits" aria-hidden="true" />
      <span className="card-chip" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <div className="bank-card-details">
        <span>{productShort(product.type)}</span>
        <strong>{money(product.balance, product.currency, hidden)}</strong>
      </div>
      <div className="bank-card-bottom">
        <span>{alias.toUpperCase()}</span>
        <span>REF {product.reference.slice(-6).toUpperCase()}</span>
      </div>
    </button>
  );
}

function ActivityChart({
  data,
  currency,
  asOf,
  hidden,
}: {
  data: Overview;
  currency: string;
  asOf: string;
  hidden: boolean;
}) {
  const base = new Date(asOf.slice(0, 10) + "T12:00:00Z");
  const months = Array.from({ length: 6 }, (_, i) => {
    const d = new Date(
      Date.UTC(base.getUTCFullYear(), base.getUTCMonth() - 5 + i, 1),
    );
    const key = d.toISOString().slice(0, 7);
    const match = data.summary.monthly_activity.find(
      (m) => m.month === key && m.currency === currency,
    );
    return {
      key,
      name: d
        .toLocaleDateString("es-MX", { month: "short", timeZone: "UTC" })
        .replace(".", ""),
      inflow: match?.inflow || 0,
      outflow: match?.outflow || 0,
    };
  });
  const maximum = Math.max(...months.flatMap((m) => [m.inflow, m.outflow]), 1);
  return (
    <div className="activity-chart">
      <div
        className="chart-bars"
        role="img"
        aria-label={`Entradas y salidas identificadas en ${currency} durante seis meses. Solo operaciones aprobadas.`}
      >
        {months.map((m) => (
          <div className="chart-month" key={m.key}>
            <div
              className="bar-pair"
              title={
                hidden
                  ? m.key
                  : `${m.key} · Entradas: ${money(m.inflow, currency)} · Salidas: ${money(m.outflow, currency)}`
              }
            >
              <div
                className="chart-bar inflow"
                style={{
                  height: `${Math.max((m.inflow / maximum) * 100, 3)}%`,
                  opacity: m.inflow ? 1 : 0.22,
                }}
              />
              <div
                className="chart-bar outflow"
                style={{
                  height: `${Math.max((m.outflow / maximum) * 100, 3)}%`,
                  opacity: m.outflow ? 1 : 0.22,
                }}
              />
            </div>
            <span>{m.name}</span>
          </div>
        ))}
      </div>
      <div className="chart-legend">
        <span>
          <i className="inflow" />
          Entradas
        </span>
        <span>
          <i className="outflow" />
          Salidas
        </span>
        <span>{currency} · Aprobados</span>
      </div>
    </div>
  );
}

function Spending({
  data,
  currency,
  hidden,
}: {
  data: Overview;
  currency: string;
  hidden: boolean;
}) {
  const items = data.transactions.filter(
    (t) =>
      t.currency === currency &&
      t.status === "Approved" &&
      t.direction === "debit",
  );
  const groups = Object.entries(
    items.reduce<Record<string, number>>((g, t) => {
      const k =
        categoryNames[t.category || ""] ||
        t.category ||
        typeNames[t.type] ||
        t.type;
      g[k] = (g[k] || 0) + t.amount;
      return g;
    }, {}),
  ).sort((a, b) => b[1] - a[1]);
  const total = groups.reduce((n, g) => n + g[1], 0),
    colors = ["#234f43", "#a9c8a1", "#d8e6bd", "#d3c4a9", "#93aba5"];
  let offset = 0;
  const segments = groups
    .map((g, i) => {
      const start = offset;
      offset += (g[1] / total) * 100;
      return `${colors[i % colors.length]} ${start}% ${offset}%`;
    })
    .join(",");
  return (
    <section className="panel spending-panel">
      <div className="panel-title">
        <h3>En qué se mueve</h3>
        <span className="currency-tag">{currency}</span>
      </div>
      <p className="panel-subtitle">
        Salidas identificadas · Historial disponible
      </p>
      {total ? (
        <>
          <div className="donut-wrap">
            <div
              className="donut"
              style={{ background: `conic-gradient(${segments})` }}
              role="img"
              aria-label="Distribución de salidas por categoría"
            >
              <div>
                <small>Total de salidas</small>
                <strong>{money(total, currency, hidden)}</strong>
                <span>{items.length} movimientos</span>
              </div>
            </div>
          </div>
          <div className="spending-groups">
            {groups.slice(0, 4).map(([name, value], i) => (
              <div key={name}>
                <span>
                  <i style={{ background: colors[i] }} />
                  {name}
                </span>
                <strong>
                  {hidden ? "•••" : `${Math.round((value / total) * 100)}%`}
                </strong>
              </div>
            ))}
          </div>
        </>
      ) : (
        <Empty title="Aún sin salidas identificadas">
          No hay compras o retiros aprobados en esta moneda.
        </Empty>
      )}
      <p className="data-footnote">
        Transferencias, pagos y ajustes no se clasifican como entradas o
        salidas.
      </p>
    </section>
  );
}

function TransactionTable({
  items,
  hidden,
  onSelect,
  compact = false,
}: {
  items: Transaction[];
  hidden: boolean;
  onSelect: (t: Transaction) => void;
  compact?: boolean;
}) {
  return (
    <div className="transaction-table">
      <div className="table-heading">
        <span>Movimiento</span>
        <span>Fecha</span>
        <span>Estado</span>
        <span>Monto</span>
      </div>
      {items.map((t) => (
        <button
          className="transaction-row"
          key={t.reference}
          onClick={() => onSelect(t)}
        >
          <span className="transaction-description">
            <TxIcon transaction={t} />
            <span>
              <strong>{label(t)}</strong>
              <small>
                {t.merchant ? typeNames[t.type] || t.type : t.channel}{" "}
                {!compact && (
                  <span>
                    · Ref. {t.product_reference.slice(-6).toUpperCase()}
                  </span>
                )}
              </small>
              <span className="transaction-mini-status">
                <Badge status={t.status} />
              </span>
            </span>
          </span>
          <span className="transaction-date">
            {date(t.occurred_at, {
              day: "2-digit",
              month: "short",
              timeZone: "UTC",
            })}
            <small>{t.occurred_at.slice(0, 4)}</small>
          </span>
          <span className="transaction-status">
            <Badge status={t.status} />
          </span>
          <Amount t={t} hidden={hidden} />
        </button>
      ))}
      {items.length === 0 && (
        <Empty title="No hay movimientos aquí">
          Prueba otro filtro para explorar tu historial.
        </Empty>
      )}
    </div>
  );
}

function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    const close = () => onClose();
    element.addEventListener("cancel", close);
    return () => {
      element.removeEventListener("cancel", close);
      element.close();
    };
  }, [onClose]);
  return (
    <dialog
      ref={dialog}
      className={`modal ${wide ? "wide" : ""}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-top">
        <h2>{title}</h2>
        <button className="icon-button" onClick={onClose} aria-label="Cerrar">
          <X size={21} />
        </button>
      </div>
      {children}
    </dialog>
  );
}

function ProductDetail({
  product,
  hidden,
  onClose,
  onTransactions,
}: {
  product: Product;
  hidden: boolean;
  onClose: () => void;
  onTransactions: () => void;
}) {
  return (
    <Modal title={productShort(product.type)} onClose={onClose}>
      <div className="detail-balance">
        <span>Saldo del producto · {product.currency}</span>
        <h2>{money(product.balance, product.currency, hidden)}</h2>
        <Badge status={product.status} />
      </div>
      <dl className="details-list">
        <div>
          <dt>Referencia del producto</dt>
          <dd>{product.reference.slice(-6).toUpperCase()}</dd>
        </div>
        <div>
          <dt>Moneda</dt>
          <dd>{product.currency}</dd>
        </div>
        <div>
          <dt>Fecha de apertura</dt>
          <dd>{date(product.opened_at)}</dd>
        </div>
        {product.credit_limit != null && (
          <div>
            <dt>Límite de crédito del snapshot</dt>
            <dd>{money(product.credit_limit, product.currency, hidden)}</dd>
          </div>
        )}
        {product.interest_rate != null && (
          <div>
            <dt>Tasa registrada en el dataset</dt>
            <dd>{product.interest_rate}%</dd>
          </div>
        )}
        <div>
          <dt>Última actualización de origen</dt>
          <dd>{date(product.last_updated)}</dd>
        </div>
      </dl>
      <div className="inline-note">
        <ShieldCheck size={18} />
        <p>
          Saldo del snapshot suministrado. No representa un saldo bancario en
          tiempo real. La referencia identifica el producto en esta demo.
        </p>
      </div>
      <button className="button primary full" onClick={onTransactions}>
        Ver movimientos de este producto
        <ArrowRight size={18} />
      </button>
    </Modal>
  );
}

function TransactionDetail({
  transaction: t,
  products,
  hidden,
  chatAvailable,
  onClose,
  onChat,
}: {
  transaction: Transaction;
  products: Product[];
  hidden: boolean;
  chatAvailable: boolean;
  onClose: () => void;
  onChat: () => void;
}) {
  const product = products.find((p) => p.reference === t.product_reference);
  const isCharge = t.type === "Purchase";
  return (
    <Modal title="Detalle del movimiento" onClose={onClose}>
      <div className="transaction-detail-head">
        <TxIcon transaction={t} />
        <h3>{label(t)}</h3>
        <Amount t={t} hidden={hidden} />
        <Badge status={t.status} />
      </div>
      <dl className="details-list">
        <div>
          <dt>Fecha del movimiento</dt>
          <dd>
            {date(t.occurred_at)} · {t.occurred_at.slice(11, 16)}
          </dd>
        </div>
        {t.process_date.slice(0, 10) !== t.occurred_at.slice(0, 10) && (
          <div>
            <dt>Fecha de procesamiento</dt>
            <dd>{date(t.process_date)}</dd>
          </div>
        )}
        <div>
          <dt>Producto</dt>
          <dd>
            {product ? productShort(product.type) : "Producto"} ·{" "}
            {t.product_reference.slice(-6).toUpperCase()}
          </dd>
        </div>
        <div>
          <dt>Tipo de operación</dt>
          <dd>{typeNames[t.type] || t.type}</dd>
        </div>
        <div>
          <dt>Canal</dt>
          <dd>{t.channel}</dd>
        </div>
        <div>
          <dt>Comercio</dt>
          <dd>{t.merchant || "No informado en el origen"}</dd>
        </div>
        <div>
          <dt>Ubicación</dt>
          <dd>
            {[t.city, t.country].filter(Boolean).join(", ") || "No informada"}
          </dd>
        </div>
        <div>
          <dt>Referencia</dt>
          <dd className="mono">{t.reference}</dd>
        </div>
      </dl>
      {t.direction === "unknown" && (
        <p className="data-footnote">
          El origen no indica si este movimiento es entrada o salida; su monto
          se presenta sin signo.
        </p>
      )}
      {isCharge && (
        <div className="charge-review">
          <span className="charge-review-icon">
            <ShieldCheck size={20} />
          </span>
          <div>
            <strong>¿No reconoces este cargo?</strong>
            <p>
              {chatAvailable
                ? "Comprueba el comercio, la fecha y el monto. Savia puede ayudarte a revisar el movimiento antes de solicitar atención humana."
                : "Comprueba el comercio, la fecha, el monto y el producto asociado. Este prototipo aún no registra revisiones ni casos."}
            </p>
          </div>
        </div>
      )}
      <button
        className="button primary full"
        onClick={onChat}
        disabled={!chatAvailable}
      >
        <MessageCircle size={18} />
        {isCharge ? "Revisar este cargo" : "Consultar este movimiento"}
        <ArrowRight size={18} />
      </button>
      <p className="modal-disclosure">
        {chatAvailable
          ? "La consulta es de solo lectura. Un caso humano solo se registra cuando recibes una confirmación verificable."
          : "La revisión asistida aún no está disponible en este prototipo. No se ha registrado un caso."}
      </p>
    </Modal>
  );
}

function AssistantText({ text }: { text: string }) {
  // Render the flow's common emphasis and references as React text nodes.
  // HTML and URLs remain plain text, keeping source/model content inert.
  return (
    <>
      {text.split(/\n\s*\n/).map((paragraph, index) => (
        <p key={index}>
          {paragraph
            .split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
            .map((part, i) =>
              part.startsWith("**") && part.endsWith("**") ? (
                <strong key={i}>{part.slice(2, -2)}</strong>
              ) : part.startsWith("`") && part.endsWith("`") ? (
                <code key={i}>{part.slice(1, -1)}</code>
              ) : (
                part
              ),
            )}
        </p>
      ))}
    </>
  );
}

function Assistant({
  open,
  status,
  selected,
  hidden,
  synthetic,
  onClose,
  onExpired,
}: {
  open: boolean;
  status: ChatStatus;
  selected: Transaction | null;
  hidden: boolean;
  synthetic: boolean;
  onClose: () => void;
  onExpired: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]),
    [input, setInput] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [historyReady, setHistoryReady] = useState(false),
    [historyLimited, setHistoryLimited] = useState(false),
    [historyAttempt, setHistoryAttempt] = useState(0);
  const end = useRef<HTMLDivElement>(null),
    controller = useRef<AbortController | null>(null),
    alive = useRef(true);
  useEffect(() => {
    if (open) end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, open]);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      controller.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (!status.available) return;
    const historyController = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setHistoryReady(false);
    setError("");
    function recover() {
      api<{ messages: ChatMessage[]; active: boolean; limited?: boolean }>(
        "/api/chat/history",
        {
          signal: historyController.signal,
        },
      )
        .then((result) => {
          if (historyController.signal.aborted || !alive.current) return;
          setMessages(result.messages);
          setHistoryLimited(Boolean(result.limited));
          setHistoryReady(true);
          setBusy(result.active);
          // A query admitted before a page refresh can finish in the server.
          // Recover its result rather than submitting that query a second time.
          if (result.active) timer = setTimeout(recover, 2000);
        })
        .catch((e) => {
          if (historyController.signal.aborted || !alive.current) return;
          if (e instanceof ApiError && e.status === 401) onExpired();
          else {
            setHistoryReady(false);
            setBusy(false);
            setError(
              "No pudimos recuperar tu conversación. Vuelve a intentar antes de enviar una consulta.",
            );
          }
        });
    }
    recover();
    return () => {
      historyController.abort();
      clearTimeout(timer);
    };
  }, [status.available, historyAttempt, onExpired]);
  async function send(text: string) {
    if (!text.trim() || busy || !status.available || !historyReady) return;
    setInput("");
    setError("");
    setMessages((m) => [
      ...m,
      { role: "user", text, ...(selected ? { selection: selected } : {}) },
    ]);
    setBusy(true);
    controller.current = new AbortController();
    try {
      const result = await api<{ reply: string }>("/api/chat/messages", {
        method: "POST",
        signal: controller.current.signal,
        body: JSON.stringify({
          message: text,
          ...(selected ? { transaction_reference: selected.reference } : {}),
        }),
      });
      if (!alive.current || controller.current.signal.aborted) return;
      setMessages((m) => [...m, { role: "assistant", text: result.reply }]);
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.status === 401) {
        onExpired();
        return;
      }
      if (e instanceof Error && e.name !== "AbortError")
        setError(
          "La consulta no pudo completarse. Puedes intentar de nuevo; tu historial sigue disponible.",
        );
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  // Closing the dialog keeps this authenticated component alive. A running
  // query can finish and its visible transcript will be here on reopening.
  if (!open) return null;
  return (
    <Modal title="Tu asistente Savia" onClose={onClose} wide>
      <div className="assistant-status">
        <span className="assistant-orb">
          <Sparkles size={18} />
        </span>
        <div>
          <strong>Un poco de claridad, cuando la necesitas.</strong>
          <span>
            {status.available
              ? "Conectado a FLUJO · Consulta de solo lectura"
              : "El asistente no está disponible ahora"}
          </span>
        </div>
      </div>
      {selected && (
        <div className="chat-selection">
          <TxIcon transaction={selected} />
          <span>
            <strong>{label(selected)}</strong>
            <small>
              {date(selected.occurred_at)} ·{" "}
              {money(selected.amount, selected.currency, hidden)}{" "}
              {selected.currency}
            </small>
          </span>
          <CheckCheck size={18} />
        </div>
      )}
      <div className="chat-messages" aria-live="polite">
        {historyLimited && (
          <p className="modal-disclosure">
            Mostramos los mensajes más recientes. El asistente mantiene el
            contexto de esta conversación.
          </p>
        )}
        {status.available && !historyReady && !error ? (
          <div className="chat-thinking">
            <LoaderCircle size={16} className="spin" />
            Recuperando tu conversación…
          </div>
        ) : messages.length === 0 && !busy ? (
          <div className="chat-welcome">
            <MessageCircle size={30} />
            <h3>Vamos a entender tus movimientos.</h3>
            <p>
              {selected
                ? "Puedes preguntarme por este movimiento, su estado o los siguientes pasos si no lo reconoces."
                : "Consulta tus movimientos y aclara una operación usando los datos de tu perfil."}
            </p>
            <div className="chat-prompts">
              {(selected
                ? [
                    "¿Qué significa el estado de este movimiento?",
                    "No reconozco este cargo. ¿Qué puedo hacer?",
                  ]
                : [
                    "Muéstrame mis movimientos recientes",
                    "¿Cómo puedo consultar un cargo que no reconozco?",
                  ]
              ).map((text) => (
                <button
                  key={text}
                  disabled={!status.available || !historyReady}
                  onClick={() => send(text)}
                >
                  {text}
                  <ArrowUpRight size={16} />
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`chat-message ${m.role}`}>
              <span>{m.role === "assistant" ? "Savia" : "Tú"}</span>
              {m.selection && (
                <div className="chat-message-selection">
                  <CreditCard size={14} />
                  <span>
                    {typeNames[m.selection.type] || m.selection.type} ·{" "}
                    {date(m.selection.occurred_at)} ·{" "}
                    {money(m.selection.amount, m.selection.currency, hidden)}
                  </span>
                </div>
              )}
              {m.role === "assistant" ? (
                <AssistantText text={m.text} />
              ) : (
                <p>{m.text}</p>
              )}
            </div>
          ))
        )}
        {busy && (
          <div className="chat-thinking">
            <LoaderCircle size={16} className="spin" />
            Consultando tus datos con FLUJO…
          </div>
        )}
        {error && (
          <div role="alert" className="form-error">
            <p>{error}</p>
            {!historyReady && (
              <button
                className="button outline"
                onClick={() => setHistoryAttempt((attempt) => attempt + 1)}
              >
                Recuperar conversación
              </button>
            )}
          </div>
        )}
        <div ref={end} />
      </div>
      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          aria-label="Mensaje para el asistente"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            status.available
              ? "Escribe tu consulta…"
              : "Asistente temporalmente desconectado"
          }
          maxLength={2000}
          disabled={!status.available || !historyReady || busy}
        />
        <button
          aria-label="Enviar mensaje"
          disabled={!status.available || !historyReady || busy || !input.trim()}
        >
          <Send size={19} />
        </button>
      </form>
      <p className="modal-disclosure">
        {synthetic
          ? "Las respuestas usan un escenario sintético del equipo. Una respuesta del asistente no confirma un caso ni una acción bancaria."
          : "Las respuestas se basan en el dataset del hackathon. Los casos y acciones bancarias requieren atención humana."}
      </p>
    </Modal>
  );
}

export default function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null),
    [authMode, setAuthMode] = useState<"demo" | "invite" | null>(null),
    [data, setData] = useState<Overview | null>(null),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [page, setPage] = useState<Page>("home"),
    [hidden, setHidden] = useState(false),
    [currency, setCurrency] = useState(""),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState("all"),
    [productFilter, setProductFilter] = useState("all"),
    [month, setMonth] = useState("all"),
    [pagination, setPagination] = useState(1),
    [selectedTx, setSelectedTx] = useState<Transaction | null>(null),
    [selectedProduct, setSelectedProduct] = useState<Product | null>(null),
    [assistant, setAssistant] = useState(false),
    [chatSelection, setChatSelection] = useState<Transaction | null>(null),
    [chatStatus, setChatStatus] = useState<ChatStatus>({ available: false }),
    [mobileMenu, setMobileMenu] = useState(false),
    [info, setInfo] = useState(false),
    [toast, setToast] = useState(""),
    [loginNotice, setLoginNotice] = useState("");
  const dataController = useRef<AbortController | null>(null);
  const expired = useCallback(() => {
    dataController.current?.abort();
    setAuthenticated(false);
    setData(null);
    setAssistant(false);
    setSelectedTx(null);
    setSelectedProduct(null);
    setInfo(false);
  }, []);
  const load = useCallback(async () => {
    dataController.current?.abort();
    const controller = new AbortController();
    dataController.current = controller;
    setLoading(true);
    setError("");
    try {
      const result = await api<Overview>("/api/overview", {
        signal: controller.signal,
      });
      const transactions = [...result.transactions];
      let offset = result.metadata.next_offset ?? null;
      while (offset !== null) {
        const next = await api<Pick<Overview, "transactions" | "metadata">>(
          `/api/transactions?limit=500&offset=${offset}`,
          { signal: controller.signal },
        );
        if (
          next.metadata.build_id !== result.metadata.build_id ||
          next.metadata.source_fingerprint !==
            result.metadata.source_fingerprint ||
          !next.transactions.length ||
          (next.metadata.next_offset !== null &&
            next.metadata.next_offset <= offset)
        ) {
          throw new Error(
            "The transaction snapshot could not be loaded consistently.",
          );
        }
        transactions.push(...next.transactions);
        offset = next.metadata.next_offset;
      }
      if (
        transactions.length !== result.metadata.transactions_total ||
        new Set(transactions.map((transaction) => transaction.reference))
          .size !== transactions.length
      ) {
        throw new Error("The transaction history is incomplete.");
      }
      if (controller.signal.aborted) return;
      result.transactions = transactions;
      result.metadata.transactions_returned = transactions.length;
      result.metadata.transactions_truncated = false;
      result.metadata.next_offset = null;
      setData(result);
      setCurrency(
        result.profile.primary_currency ||
          result.products[0]?.currency ||
          "USD",
      );
      setAuthenticated(true);
      api<ChatStatus>("/api/chat/status")
        .then(setChatStatus)
        .catch(() => setChatStatus({ available: false }));
    } catch (e) {
      if (controller.signal.aborted) return;
      if (e instanceof ApiError && e.status === 401) expired();
      else {
        setAuthenticated(true);
        setError(
          "No pudimos cargar el snapshot bancario. Comprueba la conexión y vuelve a intentar.",
        );
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [expired]);
  useEffect(() => () => dataController.current?.abort(), []);
  useEffect(() => {
    api<{ auth_mode?: "demo" | "invite" }>("/api/auth/me", {
      signal: AbortSignal.timeout(8000),
    })
      .then((result) => {
        setAuthMode(result.auth_mode === "invite" ? "invite" : "demo");
        load();
      })
      .catch(() => setAuthenticated(false));
  }, [load]);
  useEffect(() => {
    setPagination(1);
  }, [query, status, productFilter, month]);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [page]);
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(""), 3500);
      return () => clearTimeout(timer);
    }
  }, [toast]);
  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
      expired();
      setLoginNotice("");
      setPage("home");
      setQuery("");
      setProductFilter("all");
      setStatus("all");
      setMonth("all");
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.status === 503 &&
        error.revokeStatus === "persist_failed"
      ) {
        setLoginNotice(
          "Se retiró el acceso de este navegador, pero no pudimos confirmar el cierre completo de la sesión y el asistente. Solicita ayuda antes de usar otra cuenta.",
        );
        expired();
        setPage("home");
        return;
      }
      setToast("No pudimos cerrar la sesión. Intenta de nuevo.");
    }
  }
  const closeProduct = useCallback(() => setSelectedProduct(null), []),
    closeTx = useCallback(() => setSelectedTx(null), []),
    closeAssistant = useCallback(() => {
      setAssistant(false);
      setChatSelection(null);
    }, []),
    closeInfo = useCallback(() => setInfo(false), []);
  function navigate(next: Page) {
    setPage(next);
    setMobileMenu(false);
    if (next !== "transactions") setQuery("");
  }
  function openChat(t: Transaction | null = null) {
    setChatSelection(t);
    setSelectedTx(null);
    setAssistant(true);
  }
  if (authenticated === false)
    return (
      <Login
        onLogin={(mode) => {
          setAuthMode(mode);
          setLoginNotice("");
          load();
        }}
        notice={loginNotice}
      />
    );
  if (authenticated === null)
    return (
      <div className="app-boot">
        <Brand />
        <LoaderCircle size={24} className="spin" />
        <span>Preparando tu espacio…</span>
      </div>
    );
  const synthetic =
    authMode === "invite" ||
    data?.metadata.dataset === "team-synthetic-fixture";
  const currencies =
    data?.summary.balances_by_currency.map((b) => b.currency) || [];
  const balance = data?.summary.balances_by_currency.find(
    (b) => b.currency === currency,
  );
  const products = data?.products || [],
    transactions = data?.transactions || [],
    profile = data?.profile;
  const asOf = data?.metadata.data_as_of || "2026-06-17";
  const filtered = transactions.filter(
    (t) =>
      (status === "all" || t.status === status) &&
      (productFilter === "all" || t.product_reference === productFilter) &&
      (month === "all" || t.occurred_at.startsWith(month)) &&
      (!query ||
        [
          label(t),
          t.type,
          typeNames[t.type],
          t.channel,
          t.currency,
          t.reference,
        ]
          .join(" ")
          .toLocaleLowerCase("es")
          .includes(query.toLocaleLowerCase("es"))),
  );
  const months = [
    ...new Set(transactions.map((t) => t.occurred_at.slice(0, 7))),
  ]
    .sort()
    .reverse();
  const featureProduct =
    products.find((p) => /tarjeta.*cr[eé]dito/i.test(p.type)) || products[0];
  const paginationTotal = Math.max(1, Math.ceil(filtered.length / 10));
  function download(items: Transaction[]) {
    csv(items);
    setToast("Tus movimientos se descargaron en CSV.");
  }
  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileMenu ? "mobile-open" : ""}`}>
        <div className="sidebar-brand">
          <Brand />
          <button
            className="icon-button mobile-close"
            aria-label="Cerrar menú"
            onClick={() => setMobileMenu(false)}
          >
            <X size={21} />
          </button>
        </div>
        <span className="sidebar-label">TU ESPACIO PERSONAL</span>
        <nav>
          {nav.map((n) => (
            <button
              className={page === n.id ? "active" : ""}
              key={n.id}
              onClick={() => navigate(n.id)}
            >
              <n.icon size={20} />
              <span>{n.label}</span>
              {page === n.id && <span className="nav-dot" />}
            </button>
          ))}
          <button
            onClick={() => {
              openChat();
              setMobileMenu(false);
            }}
          >
            <MessageCircle size={20} />
            <span>Asistente</span>
            <span className="nav-new">
              {chatStatus.available ? "FLUJO" : "PRONTO"}
            </span>
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-help">
            <span className="help-leaf">
              <Leaf size={21} />
            </span>
            <strong>Todo un poco más claro.</strong>
            <p>
              {chatStatus.available
                ? "Entiende un movimiento con ayuda de tu asistente."
                : "Revisa los detalles de cada cargo en tu historial."}
            </p>
            <button onClick={() => openChat()}>
              {chatStatus.available ? "Hablemos" : "Estado del asistente"}
              <ArrowUpRight size={16} />
            </button>
          </div>
          <button className="sidebar-info" onClick={() => setInfo(true)}>
            <ShieldCheck size={18} />
            Sobre esta experiencia
            <ArrowUpRight size={14} />
          </button>
          <div className="sidebar-profile">
            {profile && (
              <>
                <Avatar name={profile.alias} small />
                <span>
                  <strong>{profile.alias}</strong>
                  <small>Perfil {profile.segment}</small>
                </span>
              </>
            )}
            <button
              className="icon-button"
              aria-label="Cerrar sesión"
              title="Cerrar sesión"
              onClick={logout}
            >
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      {mobileMenu && (
        <button
          className="mobile-shade"
          aria-label="Cerrar menú"
          onClick={() => setMobileMenu(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-title">
            <button
              className="icon-button mobile-menu"
              aria-label="Abrir menú"
              onClick={() => setMobileMenu(true)}
            >
              <Menu size={21} />
            </button>
            <span>{nav.find((n) => n.id === page)?.label}</span>
          </div>
          <div className="topbar-actions">
            <label className="global-search">
              <Search size={17} />
              <input
                aria-label="Buscar movimientos"
                placeholder="Buscar un movimiento"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage("transactions");
                }}
              />
              <kbd>⌕</kbd>
            </label>
            <button className="snapshot-pill" onClick={() => setInfo(true)}>
              <span className="live-dot" />
              {synthetic ? "Escenario sintético" : "Demo con datos reales"}
            </button>
            <button
              className="icon-button help-button"
              aria-label="Información de la demo"
              onClick={() => setInfo(true)}
            >
              <CircleHelp size={20} />
            </button>
            {profile && <Avatar name={profile.alias} small />}
          </div>
        </header>
        <main className="main-content">
          {error ? (
            <div className="error-state">
              <ShieldCheck size={36} />
              <h1>Un momento para reconectar.</h1>
              <p role="alert">{error}</p>
              <button className="button primary" onClick={load}>
                Volver a intentar
                <ArrowRight size={17} />
              </button>
              <button className="text-button" onClick={logout}>
                Cerrar sesión
              </button>
            </div>
          ) : loading || !data ? (
            <div className="loading-state" aria-label="Cargando datos">
              <div className="skeleton skeleton-heading" />
              <div className="skeleton skeleton-hero" />
              <div className="skeleton-row">
                <div className="skeleton" />
                <div className="skeleton" />
                <div className="skeleton" />
              </div>
              <div className="skeleton skeleton-hero" />
            </div>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">
                    {page === "home"
                      ? "UN NUEVO DÍA, CON MÁS CLARIDAD"
                      : page === "products"
                        ? "CADA PLAN TIENE SU LUGAR"
                        : "EL DETALLE HACE LA DIFERENCIA"}
                  </span>
                  <h1>
                    {page === "home" ? (
                      <>
                        Hola, {profile?.alias.split(" ")[0]}
                        <span className="greeting-dot">.</span>
                        <span className="greeting-leaf">
                          <Leaf size={26} />
                        </span>
                      </>
                    ) : page === "products" ? (
                      "Tus productos, juntos."
                    ) : (
                      "Tu dinero en movimiento."
                    )}
                  </h1>
                  <p>
                    {page === "home"
                      ? "Qué bueno tener todo bajo control."
                      : page === "products"
                        ? "Una vista clara de tus cuentas, tarjetas y otros productos."
                        : "Explora, filtra y entiende cada operación."}
                  </p>
                </div>
                <span className="asof">
                  <span>Movimientos registrados hasta</span>
                  <strong>{date(asOf)}</strong>
                </span>
              </div>
              {page === "home" && (
                <>
                  <div className="overview-grid">
                    <section className="balance-panel">
                      <div className="balance-top">
                        <span className="balance-label">
                          Tu saldo en cuentas
                          <button
                            className="icon-button"
                            aria-label={
                              hidden ? "Mostrar saldos" : "Ocultar saldos"
                            }
                            onClick={() => setHidden(!hidden)}
                          >
                            {hidden ? <EyeOff size={17} /> : <Eye size={17} />}
                          </button>
                        </span>
                        <label className="currency-select">
                          <select
                            aria-label="Moneda del resumen"
                            value={currency}
                            onChange={(e) => setCurrency(e.target.value)}
                          >
                            {currencies.map((c) => (
                              <option key={c}>{c}</option>
                            ))}
                          </select>
                          <ChevronDown size={14} />
                        </label>
                      </div>
                      <div className="balance-value">
                        {money(balance?.deposit_balance || 0, currency, hidden)}
                        <span>{currency}</span>
                      </div>
                      <div className="balance-caption">
                        <span className="tiny-leaf">
                          <Leaf size={13} />
                        </span>
                        Saldo del snapshot ·{" "}
                        {
                          products.filter(
                            (p) =>
                              p.currency === currency &&
                              p.balance_kind === "deposit",
                          ).length
                        }{" "}
                        productos en esta moneda
                      </div>
                      <ActivityChart
                        data={data}
                        currency={currency}
                        asOf={asOf}
                        hidden={hidden}
                      />
                      <div className="balance-footer">
                        <span>
                          <ShieldCheck size={14} />
                          Sin conversiones entre monedas
                        </span>
                        <button onClick={() => navigate("products")}>
                          Ver detalle
                          <ArrowUpRight size={15} />
                        </button>
                      </div>
                    </section>
                    <div className="overview-side">
                      <div className="section-line">
                        <span>UN PRODUCTO DESTACADO</span>
                        <button
                          className="text-button"
                          onClick={() => navigate("products")}
                        >
                          Ver todos
                          <ArrowUpRight size={14} />
                        </button>
                      </div>
                      {featureProduct ? (
                        <BankingCard
                          product={featureProduct}
                          alias={profile?.alias || ""}
                          hidden={hidden}
                          onClick={() => setSelectedProduct(featureProduct)}
                        />
                      ) : (
                        <div className="panel">
                          <Empty title="Sin productos">
                            No hay productos en este perfil.
                          </Empty>
                        </div>
                      )}
                      <div className="quick-actions">
                        <button onClick={() => openChat()}>
                          <span>
                            <MessageCircle size={19} />
                          </span>
                          <strong>
                            Consultar
                            <br />
                            un cargo
                          </strong>
                        </button>
                        <button onClick={() => download(transactions)}>
                          <span>
                            <ArrowDownToLine size={19} />
                          </span>
                          <strong>
                            Descargar
                            <br />
                            movimientos
                          </strong>
                        </button>
                        <button onClick={() => navigate("products")}>
                          <span>
                            <Wallet size={19} />
                          </span>
                          <strong>
                            Ver mis
                            <br />
                            productos
                          </strong>
                        </button>
                      </div>
                    </div>
                  </div>
                  <section className="products-section">
                    <div className="section-heading">
                      <h2>
                        Tus productos <span>{products.length}</span>
                      </h2>
                      <button
                        className="text-button"
                        onClick={() => navigate("products")}
                      >
                        Ver todos
                        <ArrowRight size={16} />
                      </button>
                    </div>
                    <div className="product-grid">
                      {products.slice(0, 3).map((p, i) => (
                        <ProductCard
                          key={p.reference}
                          product={p}
                          index={i}
                          hidden={hidden}
                          onSelect={() => setSelectedProduct(p)}
                        />
                      ))}
                    </div>
                    {products.length === 0 && (
                      <Empty title="Aún no hay productos" />
                    )}
                  </section>
                  <div className="history-grid">
                    <section className="panel recent-panel">
                      <div className="panel-title">
                        <h3>Últimos movimientos</h3>
                        <button
                          className="text-button"
                          onClick={() => {
                            setProductFilter("all");
                            navigate("transactions");
                          }}
                        >
                          Ver historial
                          <ArrowRight size={15} />
                        </button>
                      </div>
                      <p className="panel-subtitle">
                        El registro de lo que pasa con tu dinero.
                      </p>
                      <TransactionTable
                        items={transactions.slice(0, 6)}
                        hidden={hidden}
                        onSelect={setSelectedTx}
                        compact
                      />
                      <div className="recent-footer">
                        <span>
                          {number(data.metadata.transactions_total)} movimientos
                          en el historial del perfil
                        </span>
                        <ArrowDownLeft size={15} />
                      </div>
                    </section>
                    <Spending data={data} currency={currency} hidden={hidden} />
                  </div>
                  <section className="clarity-banner">
                    <span className="clarity-icon">
                      <Sparkles size={25} />
                    </span>
                    <div>
                      <h3>¿Un movimiento que no te suena?</h3>
                      <p>
                        Revisa el comercio, la fecha y el monto antes de pedir
                        ayuda.
                      </p>
                    </div>
                    <button
                      className="button subtle"
                      onClick={() => navigate("transactions")}
                    >
                      Ver movimientos
                      <ArrowUpRight size={17} />
                    </button>
                  </section>
                </>
              )}
              {page === "products" && (
                <>
                  <div className="products-toolbar">
                    <span>{products.length} productos en tu perfil</span>
                    <button
                      className="text-button"
                      onClick={() => setHidden(!hidden)}
                    >
                      {hidden ? <EyeOff size={17} /> : <Eye size={17} />}{" "}
                      {hidden ? "Mostrar saldos" : "Ocultar saldos"}
                    </button>
                  </div>
                  <div className="product-grid all-products">
                    {products.map((p, i) => (
                      <ProductCard
                        product={p}
                        key={p.reference}
                        index={i}
                        hidden={hidden}
                        onSelect={() => setSelectedProduct(p)}
                      />
                    ))}
                  </div>
                  <section className="panel currency-summary">
                    <div className="panel-title">
                      <h3>Un resumen por moneda</h3>
                      <ShieldCheck size={19} />
                    </div>
                    <p className="panel-subtitle">
                      Cada moneda mantiene su valor. No se aplican tipos de
                      cambio.
                    </p>
                    <div className="currency-summary-grid">
                      {data.summary.balances_by_currency.map((b) => (
                        <div key={b.currency}>
                          <span className="currency-tag">{b.currency}</span>
                          <dl>
                            <div>
                              <dt>Cuentas</dt>
                              <dd>
                                {money(b.deposit_balance, b.currency, hidden)}
                              </dd>
                            </div>
                            <div>
                              <dt>Crédito</dt>
                              <dd>
                                {money(b.credit_balance, b.currency, hidden)}
                              </dd>
                            </div>
                            <div>
                              <dt>Inversión</dt>
                              <dd>
                                {money(
                                  b.investment_balance,
                                  b.currency,
                                  hidden,
                                )}
                              </dd>
                            </div>
                            {b.other_balance !== 0 && (
                              <div>
                                <dt>Otros productos</dt>
                                <dd>
                                  {money(b.other_balance, b.currency, hidden)}
                                </dd>
                              </div>
                            )}
                          </dl>
                        </div>
                      ))}
                    </div>
                  </section>
                  <div className="inline-note">
                    <ShieldCheck size={20} />
                    <p>
                      Estos son los saldos registrados en el snapshot. Cada
                      producto puede tener una fecha de actualización distinta.
                      Consulta el detalle para verla.
                    </p>
                  </div>
                </>
              )}
              {page === "transactions" && (
                <>
                  <div className="transactions-toolbar">
                    <div>
                      <span className="history-count">
                        {number(filtered.length)}
                      </span>
                      <span>
                        movimientos{" "}
                        {filtered.length !== transactions.length
                          ? "en este filtro"
                          : "en tu historial"}
                      </span>
                    </div>
                    <button
                      className="button outline"
                      onClick={() => download(filtered)}
                      disabled={!filtered.length}
                    >
                      <ArrowDownToLine size={17} />
                      Exportar CSV
                    </button>
                  </div>
                  <section className="panel full-history">
                    <div className="filters">
                      <label className="filter-search">
                        <Search size={18} />
                        <input
                          placeholder="Comercio, operación o moneda"
                          aria-label="Filtrar movimientos"
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                        />
                      </label>
                      <label>
                        <span className="sr-only">Producto</span>
                        <select
                          aria-label="Filtrar por producto"
                          value={productFilter}
                          onChange={(e) => setProductFilter(e.target.value)}
                        >
                          <option value="all">Todos los productos</option>
                          {products.map((p) => (
                            <option key={p.reference} value={p.reference}>
                              {productShort(p.type)} ·{" "}
                              {p.reference.slice(-6).toUpperCase()}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span className="sr-only">Estado</span>
                        <select
                          aria-label="Filtrar por estado"
                          value={status}
                          onChange={(e) => setStatus(e.target.value)}
                        >
                          <option value="all">Todos los estados</option>
                          {["Approved", "Pending", "Declined", "Reversed"].map(
                            (s) => (
                              <option key={s} value={s}>
                                {statusNames[s]}
                              </option>
                            ),
                          )}
                        </select>
                      </label>
                      <label>
                        <span className="sr-only">Mes</span>
                        <select
                          aria-label="Filtrar por mes del movimiento"
                          value={month}
                          onChange={(e) => setMonth(e.target.value)}
                        >
                          <option value="all">Todo el historial</option>
                          {months.map((m) => (
                            <option value={m} key={m}>
                              {date(m + "-01", {
                                month: "long",
                                year: "numeric",
                                timeZone: "UTC",
                              })}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    {(status !== "all" ||
                      productFilter !== "all" ||
                      month !== "all" ||
                      query) && (
                      <div className="active-filters">
                        <SlidersHorizontal size={14} />
                        <span>Filtros aplicados</span>
                        <button
                          onClick={() => {
                            setQuery("");
                            setStatus("all");
                            setProductFilter("all");
                            setMonth("all");
                          }}
                        >
                          Limpiar filtros
                          <X size={13} />
                        </button>
                      </div>
                    )}
                    <TransactionTable
                      items={filtered.slice(
                        (pagination - 1) * 10,
                        pagination * 10,
                      )}
                      hidden={hidden}
                      onSelect={setSelectedTx}
                    />
                    <div className="pagination">
                      <span>
                        {filtered.length
                          ? `${(pagination - 1) * 10 + 1}–${Math.min(pagination * 10, filtered.length)} de ${number(filtered.length)}`
                          : "0 movimientos"}
                      </span>
                      <div>
                        <button
                          className="icon-button"
                          aria-label="Página anterior"
                          disabled={pagination === 1}
                          onClick={() => setPagination(pagination - 1)}
                        >
                          <ChevronLeft size={18} />
                        </button>
                        <span>
                          {pagination} / {paginationTotal}
                        </span>
                        <button
                          className="icon-button"
                          aria-label="Página siguiente"
                          disabled={pagination === paginationTotal}
                          onClick={() => setPagination(pagination + 1)}
                        >
                          <ChevronRight size={18} />
                        </button>
                      </div>
                    </div>
                  </section>
                  <div className="inline-note">
                    <FileText size={18} />
                    <p>
                      Los montos sin signo no tienen una dirección indicada en
                      el origen. Si un comercio no está informado, mostramos el
                      tipo de operación y su canal.
                    </p>
                  </div>
                </>
              )}
              <footer className="content-footer">
                <span>
                  <Leaf size={15} />
                  Savia · Tu dinero, en calma.
                </span>
                <button onClick={() => setInfo(true)}>
                  <span className="live-dot" />
                  {synthetic ? "Prototipo sintético" : "Dataset del hackathon"}
                  <ArrowUpRight size={13} />
                </button>
              </footer>
            </>
          )}
        </main>
      </div>
      {selectedProduct && (
        <ProductDetail
          product={selectedProduct}
          hidden={hidden}
          onClose={closeProduct}
          onTransactions={() => {
            setProductFilter(selectedProduct.reference);
            setPage("transactions");
            setSelectedProduct(null);
            setQuery("");
            setStatus("all");
            setMonth("all");
          }}
        />
      )}
      {selectedTx && (
        <TransactionDetail
          transaction={selectedTx}
          products={products}
          hidden={hidden}
          chatAvailable={chatStatus.available}
          onClose={closeTx}
          onChat={() => openChat(selectedTx)}
        />
      )}
      <Assistant
        open={assistant}
        status={chatStatus}
        selected={chatSelection}
        hidden={hidden}
        synthetic={synthetic}
        onClose={closeAssistant}
        onExpired={expired}
      />
      {info && (
        <Modal
          title={
            synthetic
              ? "Un escenario para explorar"
              : "Una experiencia con datos reales"
          }
          onClose={closeInfo}
        >
          <div className="about-logo">
            <Brand />
          </div>
          <p className="about-intro">
            {synthetic
              ? "Savia es un prototipo de banca personal para el Factored AI & Data Hackathon 2026. Los perfiles, productos, saldos y movimientos de este escenario fueron creados por el equipo y son completamente ficticios."
              : "Savia es una demo de banca personal creada para el Factored AI & Data Hackathon 2026. Los productos, saldos y movimientos corresponden al dataset sintético del organizador."}
          </p>
          <dl className="details-list">
            <div>
              <dt>Fecha más reciente del movimiento</dt>
              <dd>{date(asOf)}</dd>
            </div>
            <div>
              <dt>Fuente</dt>
              <dd>Snapshot silver / gold · DuckDB</dd>
            </div>
            <div>
              <dt>Asistente</dt>
              <dd>
                {chatStatus.available
                  ? "FLUJO conectado"
                  : "Temporalmente no disponible"}
              </dd>
            </div>
            {data && (
              <div>
                <dt>Versión del snapshot</dt>
                <dd className="mono">{data.metadata.build_id}</dd>
              </div>
            )}
          </dl>
          <div className="inline-note">
            <Fingerprint size={21} />
            <p>
              {synthetic
                ? "Cada invitación está ligada en el servidor a un único perfil ficticio. Solo puedes consultar sus productos y movimientos."
                : "Los nombres son alias de demostración. La sesión limita cada consulta a los productos y movimientos del perfil seleccionado."}
            </p>
          </div>
          <p className="about-intro">
            Esta demo no mueve dinero, bloquea tarjetas ni ejecuta acciones en
            un banco. Los saldos son valores suministrados en el snapshot y
            pueden tener fechas distintas a las transacciones.
          </p>
        </Modal>
      )}
      {toast && (
        <div className="toast" role="status">
          <Check size={17} />
          {toast}
        </div>
      )}
    </div>
  );
}
