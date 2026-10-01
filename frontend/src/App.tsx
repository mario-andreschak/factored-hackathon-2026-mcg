import { useCallback, useEffect, useId, useRef, useState } from "react";
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
  ActionFacts,
  ActionResult,
  ChatMessage,
  ChatStatus,
  HandoffPacket,
  IntakeReceipt,
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
  { id: "home" as Page, label: "Inicio", pt: "Início", icon: Home },
  {
    id: "products" as Page,
    label: "Mis productos",
    pt: "Meus produtos",
    icon: Wallet,
  },
  {
    id: "transactions" as Page,
    label: "Movimientos",
    pt: "Movimentos",
    icon: ArrowDownLeft,
  },
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
function Badge({
  status,
  language = "es",
}: {
  status: string;
  language?: ActionLanguage;
}) {
  return (
    <span className={`badge ${status.toLowerCase()}`}>
      <span />
      {language === "pt"
        ? ptStatus[status] || statusNames[status] || status
        : statusNames[status] || status}
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
function Amount({
  t,
  hidden,
  language = "es",
}: {
  t: Transaction;
  hidden?: boolean;
  language?: ActionLanguage;
}) {
  return (
    <span
      className={`amount ${t.direction === "credit" && t.status === "Approved" ? "incoming" : ""}`}
    >
      {!hidden && t.direction !== "unknown" && t.status === "Approved"
        ? t.direction === "credit"
          ? "+"
          : "−"
        : ""}
      {language === "pt" && !hidden
        ? new Intl.NumberFormat("pt-BR", {
            style: "currency",
            currency: t.currency,
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          }).format(t.amount)
        : money(t.amount, t.currency, hidden)}
      <small>{t.currency}</small>
    </span>
  );
}

type LoginError = "" | "connection" | "invalid" | "submit";
const loginCopy = {
  es: {
    language: "Idioma de acceso",
    eyebrow: "TU BANCA, A TU RITMO",
    story: ["Tu dinero.", "Tus planes.", "Tu tranquilidad."],
    storyIntro: "Una forma más clara de ver tus finanzas.",
    storyOutro: "Todo lo que necesitas, en un solo lugar.",
    card: "Tu mundo, conectado",
    float: "Todo en su lugar",
    storyFooter: "Hecho para moverte con confianza.",
    inviteTitle: "Tu acceso, solo tuyo.",
    demoTitle: "Qué bueno verte.",
    inviteIntro:
      "Ingresa la invitación que recibiste para explorar tu espacio.",
    demoIntro: "Entra a tu espacio personal.",
    retry: "Reintentar",
    loading: "Preparando tu acceso…",
    profile: "Elige un perfil de demostración",
    inviteCode: "Código de invitación",
    demoCode: "Código de acceso",
    invitePlaceholder: "Pega tu invitación",
    demoPlaceholder: "Ingresa tu código",
    submit: "Entrar a mi banca",
    submitting: "Iniciando sesión…",
    trust: "Sesión privada · Demostración con datos sintéticos",
    inviteDisclosure:
      "Prototipo con datos sintéticos creados por el equipo. Cada invitación abre un único perfil ficticio.",
    demoDisclosure:
      "Experiencia de demostración con los datos sintéticos del hackathon. Los nombres son alias; los productos y movimientos provienen del dataset.",
    footer: "Tu dinero, en calma.",
    portalLanguageNotice: "",
    sessionNotice:
      "Se retiró el acceso de este navegador, pero no pudimos confirmar el cierre completo de la sesión y el asistente. Solicita ayuda antes de usar otra cuenta.",
    errors: {
      connection:
        "La conexión con los datos no está disponible. Intenta de nuevo.",
      invalid: "El código no es correcto. Revisa e intenta de nuevo.",
      submit: "No pudimos iniciar tu sesión. Intenta de nuevo.",
    },
  },
  pt: {
    language: "Idioma de acesso",
    eyebrow: "SEU BANCO, NO SEU RITMO",
    story: ["Seu dinheiro.", "Seus planos.", "Sua tranquilidade."],
    storyIntro: "Uma maneira mais clara de acompanhar suas finanças.",
    storyOutro: "Tudo de que você precisa, em um só lugar.",
    card: "Seu mundo, conectado",
    float: "Tudo em seu lugar",
    storyFooter: "Feito para você seguir com confiança.",
    inviteTitle: "Seu acesso é só seu.",
    demoTitle: "Que bom ter você aqui.",
    inviteIntro:
      "Digite o código do convite que você recebeu para explorar seu espaço.",
    demoIntro: "Entre no seu espaço pessoal.",
    retry: "Tentar novamente",
    loading: "Preparando seu acesso…",
    profile: "Escolha um perfil de demonstração",
    inviteCode: "Código do convite",
    demoCode: "Código de acesso",
    invitePlaceholder: "Cole seu convite",
    demoPlaceholder: "Digite seu código",
    submit: "Entrar no meu banco",
    submitting: "Entrando…",
    trust: "Sessão privada · Demonstração com dados sintéticos",
    inviteDisclosure:
      "Protótipo com dados sintéticos criados pela equipe. Cada convite abre um único perfil fictício.",
    demoDisclosure:
      "Experiência de demonstração com dados sintéticos do hackathon. Os nomes são apelidos; os produtos e lançamentos vêm do conjunto de dados.",
    footer: "Seu dinheiro, com tranquilidade.",
    portalLanguageNotice:
      "Após entrar, a navegação e a consulta de movimentos estarão em português. Início, produtos, seus detalhes e as informações da demonstração continuam em espanhol; o Assistente segue o idioma escolhido aqui.",
    sessionNotice:
      "O acesso deste navegador foi removido, mas não foi possível confirmar o encerramento completo da sessão e do Assistente. Peça ajuda antes de usar outra conta.",
    errors: {
      connection: "A conexão com os dados está indisponível. Tente novamente.",
      invalid: "O código está incorreto. Confira e tente novamente.",
      submit: "Não foi possível iniciar sua sessão. Tente novamente.",
    },
  },
} as const;

export function Login({
  onLogin,
  notice,
  initialLanguage = savedActionLanguage(),
  onLanguageChange,
}: {
  onLogin: (mode: "demo" | "invite") => void;
  notice: "" | "session-revoke-unconfirmed";
  initialLanguage?: ActionLanguage;
  onLanguageChange?: (language: ActionLanguage) => void;
}) {
  const [locale, setLocale] = useState<ActionLanguage>(initialLanguage);
  const [profiles, setProfiles] = useState<Profile[]>([]),
    [mode, setMode] = useState<"loading" | "demo" | "invite">("loading"),
    [profileId, setProfileId] = useState(""),
    [code, setCode] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<LoginError>("");
  const copy = loginCopy[locale];
  useEffect(() => {
    document.documentElement.lang = locale === "pt" ? "pt-BR" : "es";
    document.title =
      locale === "pt"
        ? "Savia · Seu banco pessoal"
        : "Savia · Tu banca personal";
    return () => {
      document.documentElement.lang = "es";
      document.title = "Savia · Tu banca personal";
    };
  }, [locale]);
  function changeLocale(next: ActionLanguage) {
    setLocale(next);
    onLanguageChange?.(next);
    try {
      window.localStorage.setItem(ACTION_LANGUAGE_STORAGE, next);
    } catch {
      // The choice still applies to this sign-in when storage is unavailable.
    }
  }
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
      .catch(() => setError("connection"));
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
        e instanceof ApiError && e.status === 401 ? "invalid" : "submit",
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
            {copy.eyebrow}
          </span>
          <h1>
            {copy.story[0]}
            <br />
            {copy.story[1]}
            <br />
            <em>{copy.story[2]}</em>
          </h1>
          <p>
            {copy.storyIntro}
            <br />
            {copy.storyOutro}
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
                <span>{copy.card}</span>
                <Globe2 size={25} />
              </div>
            </div>
            <div className="art-float">
              <span>
                <Check size={15} />
              </span>
              {copy.float}
            </div>
          </div>
        </div>
        <div className="story-footer">
          <span>{copy.storyFooter}</span>
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
          <label className="login-language">
            <span>{copy.language}</span>
            <select
              value={locale}
              onChange={(event) =>
                changeLocale(event.target.value as ActionLanguage)
              }
            >
              <option value="es" lang="es">
                Español
              </option>
              <option value="pt" lang="pt-BR">
                Português (Brasil)
              </option>
            </select>
          </label>
          <span className="login-lock">
            <LockKeyhole size={24} />
          </span>
          <h2>{mode === "invite" ? copy.inviteTitle : copy.demoTitle}</h2>
          <p className="login-intro">
            {mode === "invite" ? copy.inviteIntro : copy.demoIntro}
          </p>
          {mode === "loading" ? (
            <div className="login-loading">
              {error ? (
                <p className="form-error" role="alert">
                  {copy.errors[error]}{" "}
                  <button type="button" className="text-button" onClick={load}>
                    {copy.retry}
                  </button>
                </p>
              ) : (
                <>
                  <LoaderCircle size={18} className="spin" /> {copy.loading}
                </>
              )}
            </div>
          ) : (
            <form onSubmit={submit}>
              {mode === "demo" && (
                <>
                  <p className="field-label">{copy.profile}</p>
                  <div
                    className="profile-options"
                    role="group"
                    aria-label={copy.profile}
                  >
                    {profiles.map((p) => (
                      <button
                        type="button"
                        key={p.id}
                        className={`profile-option ${profileId === p.id ? "selected" : ""}`}
                        onClick={() => setProfileId(p.id || "")}
                        aria-pressed={profileId === p.id}
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
                {mode === "invite" ? copy.inviteCode : copy.demoCode}
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
                      ? copy.invitePlaceholder
                      : copy.demoPlaceholder
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
                  {copy.errors[error]}
                </p>
              )}
              <button
                className="button primary login-submit"
                disabled={busy || (mode === "demo" && !profileId)}
              >
                {busy ? (
                  <>
                    <LoaderCircle className="spin" size={19} />
                    {copy.submitting}
                  </>
                ) : (
                  <>
                    {copy.submit}
                    <ArrowRight size={18} />
                  </>
                )}
              </button>
            </form>
          )}
          <div className="login-trust">
            <ShieldCheck size={17} />
            <span>{copy.trust}</span>
          </div>
          {notice && (
            <p className="login-warning" role="alert">
              {copy.sessionNotice}
            </p>
          )}
          <p className="login-disclosure">
            {mode === "invite" ? copy.inviteDisclosure : copy.demoDisclosure}
          </p>
          {copy.portalLanguageNotice && (
            <p className="login-disclosure login-language-note">
              {copy.portalLanguageNotice}
            </p>
          )}
        </div>
        <footer className="login-footer">
          <span>© 2026 Savia</span>
          <span>{copy.footer}</span>
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
  language = "es",
}: {
  items: Transaction[];
  hidden: boolean;
  onSelect: (t: Transaction) => void;
  compact?: boolean;
  language?: ActionLanguage;
}) {
  const pt = language === "pt";
  return (
    <div className="transaction-table" lang={pt ? "pt-BR" : "es"}>
      <div className="table-heading">
        <span>{pt ? "Movimento" : "Movimiento"}</span>
        <span>{pt ? "Data" : "Fecha"}</span>
        <span>{pt ? "Status" : "Estado"}</span>
        <span>{pt ? "Valor" : "Monto"}</span>
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
              <strong lang={t.merchant ? "" : pt ? "pt-BR" : "es"}>
                {t.merchant || portalType(t.type, language)}
              </strong>
              <small>
                {t.merchant ? (
                  portalType(t.type, language)
                ) : (
                  <span lang="">{t.channel}</span>
                )}{" "}
                {!compact && (
                  <span>
                    · Ref. {t.product_reference.slice(-6).toUpperCase()}
                  </span>
                )}
              </small>
              <span className="transaction-mini-status">
                <Badge status={t.status} language={language} />
              </span>
            </span>
          </span>
          <span className="transaction-date">
            {pt
              ? new Intl.DateTimeFormat("pt-BR", {
                  day: "2-digit",
                  month: "short",
                  timeZone: "UTC",
                }).format(new Date(t.occurred_at.slice(0, 10) + "T12:00:00Z"))
              : date(t.occurred_at, {
                  day: "2-digit",
                  month: "short",
                  timeZone: "UTC",
                })}
            <small>{t.occurred_at.slice(0, 4)}</small>
          </span>
          <span className="transaction-status">
            <Badge status={t.status} language={language} />
          </span>
          <Amount t={t} hidden={hidden} language={language} />
        </button>
      ))}
      {items.length === 0 && (
        <Empty
          title={pt ? "Nenhum movimento encontrado" : "No hay movimientos aquí"}
        >
          {pt
            ? "Experimente outro filtro para consultar seu histórico."
            : "Prueba otro filtro para explorar tu historial."}
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
  titleLang,
  closeLabel = "Cerrar",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  titleLang?: string;
  closeLabel?: string;
}) {
  const titleId = useId();
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
      aria-labelledby={titleId}
      className={`modal ${wide ? "wide" : ""}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal-top">
        <h2 id={titleId} lang={titleLang}>
          {title}
        </h2>
        <button
          className="icon-button"
          onClick={onClose}
          aria-label={closeLabel}
          lang={titleLang}
        >
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
  language = "es",
}: {
  transaction: Transaction;
  products: Product[];
  hidden: boolean;
  chatAvailable: boolean;
  onClose: () => void;
  onChat: () => void;
  language?: ActionLanguage;
}) {
  const pt = language === "pt";
  const product = products.find((p) => p.reference === t.product_reference);
  const isCharge = t.type === "Purchase";
  return (
    <Modal
      title={pt ? "Detalhes do movimento" : "Detalle del movimiento"}
      titleLang={pt ? "pt-BR" : "es"}
      closeLabel={pt ? "Fechar" : "Cerrar"}
      onClose={onClose}
    >
      <div lang={pt ? "pt-BR" : "es"}>
        <div className="transaction-detail-head">
          <TxIcon transaction={t} />
          <h3 lang={t.merchant ? "" : pt ? "pt-BR" : "es"}>
            {t.merchant || portalType(t.type, language)}
          </h3>
          <Amount t={t} hidden={hidden} language={language} />
          <Badge status={t.status} language={language} />
        </div>
        <dl className="details-list">
          <div>
            <dt>{pt ? "Data do movimento" : "Fecha del movimiento"}</dt>
            <dd>
              {portalDate(t.occurred_at, language)} ·{" "}
              {t.occurred_at.slice(11, 16)}
            </dd>
          </div>
          {t.process_date.slice(0, 10) !== t.occurred_at.slice(0, 10) && (
            <div>
              <dt>{pt ? "Data do processamento" : "Fecha de procesamiento"}</dt>
              <dd>{portalDate(t.process_date, language)}</dd>
            </div>
          )}
          <div>
            <dt>{pt ? "Produto" : "Producto"}</dt>
            <dd>
              {product
                ? portalProduct(product.type, language)
                : pt
                  ? "Produto"
                  : "Producto"}{" "}
              · {t.product_reference.slice(-6).toUpperCase()}
            </dd>
          </div>
          <div>
            <dt>{pt ? "Tipo de operação" : "Tipo de operación"}</dt>
            <dd>{portalType(t.type, language)}</dd>
          </div>
          <div>
            <dt>Canal</dt>
            <dd lang="">{t.channel}</dd>
          </div>
          <div>
            <dt>{pt ? "Estabelecimento" : "Comercio"}</dt>
            <dd lang={t.merchant ? "" : undefined}>
              {t.merchant ||
                (pt ? "Não informado na origem" : "No informado en el origen")}
            </dd>
          </div>
          <div>
            <dt>{pt ? "Localização" : "Ubicación"}</dt>
            <dd lang={t.city ? "" : undefined}>
              {[t.city, t.country].filter(Boolean).join(", ") ||
                (pt ? "Não informada" : "No informada")}
            </dd>
          </div>
          <div>
            <dt>{pt ? "Referência" : "Referencia"}</dt>
            <dd className="mono">{t.reference}</dd>
          </div>
        </dl>
        {t.direction === "unknown" && (
          <p className="data-footnote">
            {pt
              ? "A origem não informa se este movimento é entrada ou saída; o valor aparece sem sinal."
              : "El origen no indica si este movimiento es entrada o salida; su monto se presenta sin signo."}
          </p>
        )}
        {isCharge && (
          <div className="charge-review">
            <span className="charge-review-icon">
              <ShieldCheck size={20} />
            </span>
            <div>
              <strong>
                {pt
                  ? "Não reconhece esta cobrança?"
                  : "¿No reconoces este cargo?"}
              </strong>
              <p>
                {chatAvailable
                  ? pt
                    ? "Confira o estabelecimento, a data e o valor. A Savia pode ajudar você a revisar o movimento antes de solicitar atendimento humano."
                    : "Comprueba el comercio, la fecha y el monto. Savia puede ayudarte a revisar el movimiento antes de solicitar atención humana."
                  : pt
                    ? "Confira o estabelecimento, a data, o valor e o produto associado. Este protótipo ainda não registra análises nem casos."
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
          {isCharge
            ? pt
              ? "Revisar esta cobrança"
              : "Revisar este cargo"
            : pt
              ? "Consultar este movimento"
              : "Consultar este movimiento"}
          <ArrowRight size={18} />
        </button>
        <p className="modal-disclosure">
          {chatAvailable
            ? pt
              ? "A consulta é somente leitura. Uma solicitação de atendimento humano só é registrada após uma confirmação verificável."
              : "La consulta es de solo lectura. Un caso humano solo se registra cuando recibes una confirmación verificable."
            : pt
              ? "A revisão assistida ainda não está disponível neste protótipo. Nenhum caso foi registrado."
              : "La revisión asistida aún no está disponible en este prototipo. No se ha registrado un caso."}
        </p>
      </div>
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

type ActionLanguage = "es" | "pt";
const ptStatus: Record<string, string> = {
  Approved: "Aprovado",
  Pending: "Pendente",
  Declined: "Recusado",
  Reversed: "Estornado",
  Active: "Ativo",
  Blocked: "Bloqueado",
  Closed: "Encerrado",
  Suspended: "Suspenso",
  Inactive: "Inativo",
};
const ptTypes: Record<string, string> = {
  Purchase: "Compra",
  Withdrawal: "Saque",
  Transfer: "Transferência",
  Payment: "Pagamento",
  Deposit: "Depósito",
  Adjustment: "Ajuste",
};
const ptProducts: Record<string, string> = {
  "Cuenta Ahorro": "Conta poupança",
  "Cuenta Corriente": "Conta corrente",
  "Tarjeta Crédito": "Cartão de crédito",
  "Tarjeta Débito": "Cartão de débito",
};
const portalType = (value: string, language: ActionLanguage) =>
  language === "pt"
    ? ptTypes[value] || typeNames[value] || value
    : typeNames[value] || value;
const portalProduct = (value: string, language: ActionLanguage) =>
  language === "pt"
    ? ptProducts[value] || productShort(value)
    : productShort(value);
const portalDate = (
  value: string,
  language: ActionLanguage,
  options?: Intl.DateTimeFormatOptions,
) => (language === "pt" ? actionDate(value, "pt") : date(value, options));
const portalNumber = (value: number, language: ActionLanguage) =>
  language === "pt"
    ? new Intl.NumberFormat("pt-BR").format(value)
    : number(value);
const ACTION_LANGUAGE_STORAGE = "flujo-bank-action-language";
const assistantCopy = {
  es: {
    title: "Tu asistente Savia",
    close: "Cerrar",
    language: "Idioma de la interfaz",
    tagline: "Un poco de claridad, cuando la necesitas.",
    connectedIntake:
      "Conectado a FLUJO · Recepción simulada disponible tras confirmación",
    connectedReadOnly: "Conectado a FLUJO · Consulta de solo lectura",
    unavailable: "El asistente no está disponible ahora",
    historyLimited:
      "Mostramos los mensajes más recientes. El asistente mantiene el contexto de esta conversación.",
    recovering: "Recuperando tu conversación…",
    welcome: "Vamos a entender tus movimientos.",
    selectedHelp:
      "Puedes preguntarme por este movimiento, su estado o los siguientes pasos si no lo reconoces.",
    generalHelp:
      "Consulta tus movimientos y aclara una operación usando los datos de tu perfil.",
    selectedPrompts: [
      "¿Qué significa el estado de este movimiento?",
      "No reconozco este cargo. ¿Qué puedo hacer?",
    ],
    generalPrompts: [
      "Muéstrame mis movimientos recientes",
      "¿Cómo puedo consultar un cargo que no reconozco?",
    ],
    you: "Tú",
    thinking: "Consultando tus datos con FLUJO…",
    recover: "Recuperar conversación",
    historyError:
      "No pudimos recuperar tu conversación. Vuelve a intentar antes de enviar una consulta.",
    sendError:
      "La consulta no pudo completarse. Puedes intentar de nuevo; tu historial sigue disponible.",
    messageLabel: "Mensaje para el asistente",
    messagePlaceholder: "Escribe tu consulta…",
    disconnectedPlaceholder: "Asistente temporalmente desconectado",
    sendLabel: "Enviar mensaje",
    syntheticDisclosure:
      "Las respuestas usan un escenario sintético del equipo. Una respuesta del asistente no confirma un caso ni una acción bancaria.",
    dataDisclosure:
      "Las respuestas se basan en el dataset del hackathon. Los casos y acciones bancarias requieren atención humana.",
  },
  pt: {
    title: "Seu assistente Savia",
    close: "Fechar",
    language: "Idioma da interface",
    tagline: "Um pouco de clareza quando você precisa.",
    connectedIntake:
      "Conectado ao FLUJO · Registro simulado disponível após confirmação",
    connectedReadOnly: "Conectado ao FLUJO · Consulta somente de leitura",
    unavailable: "O assistente não está disponível agora",
    historyLimited:
      "Mostramos as mensagens mais recentes. O assistente mantém o contexto desta conversa.",
    recovering: "Recuperando sua conversa…",
    welcome: "Vamos entender seus lançamentos.",
    selectedHelp:
      "Você pode perguntar sobre este lançamento, seu estado ou os próximos passos caso não o reconheça.",
    generalHelp:
      "Consulte seus lançamentos e esclareça uma operação usando os dados do seu perfil.",
    selectedPrompts: [
      "O que significa o estado deste lançamento?",
      "Não reconheço esta cobrança. O que posso fazer?",
    ],
    generalPrompts: [
      "Mostre meus lançamentos recentes",
      "Como posso consultar uma cobrança que não reconheço?",
    ],
    you: "Você",
    thinking: "Consultando seus dados com o FLUJO…",
    recover: "Recuperar conversa",
    historyError:
      "Não foi possível recuperar sua conversa. Tente novamente antes de enviar uma pergunta.",
    sendError:
      "Não foi possível concluir a consulta. Você pode tentar novamente; seu histórico continua disponível.",
    messageLabel: "Mensagem para o assistente",
    messagePlaceholder: "Escreva sua pergunta…",
    disconnectedPlaceholder: "Assistente temporariamente desconectado",
    sendLabel: "Enviar mensagem",
    syntheticDisclosure:
      "As respostas usam um cenário sintético da equipe. Uma resposta do assistente não confirma um caso nem uma ação bancária.",
    dataDisclosure:
      "As respostas se baseiam no conjunto de dados do hackathon. Casos e ações bancárias exigem atendimento humano.",
  },
} as const;

function savedActionLanguage(): ActionLanguage {
  if (typeof window === "undefined") return "es";
  try {
    return window.localStorage.getItem(ACTION_LANGUAGE_STORAGE) === "pt"
      ? "pt"
      : "es";
  } catch {
    return "es";
  }
}

const actionCopy = {
  es: {
    title: "¿No reconoces un cargo?",
    disclosure:
      "La recepción es una simulación. No bloquea tarjetas, devuelve dinero ni resuelve una disputa.",
    language: "Idioma de esta respuesta",
    pendingCharge: "Solicitud pendiente para este cargo",
    pendingReview: "Solicitud de revisión pendiente",
    noCharge: "Revisión general sin cargo asociado.",
    otherCharge:
      "La solicitud anterior sigue vinculada al cargo indicado. El cargo que ves seleccionado no puede confirmarla ni reemplazarla.",
    returnCharge: " Vuelve a ese cargo para continuar.",
    checkOtherCharge: " Consulta su estado antes de realizar otra acción.",
    backToCharge: "Volver al cargo pendiente",
    verifyFirst:
      "Verifica el estado de la solicitud antes de iniciar o confirmar otra acción.",
    checkStatus: "Consultar estado de la solicitud",
    reviewIntake: "Revisar recepción simulada",
    confirmIntake: "Confirmo la recepción simulada para",
    chargeReference: "Referencia del cargo",
    eventDate: "Fecha del movimiento",
    merchantNotReported: "Comercio no informado",
    dateNotReported: "Fecha no informada",
    showConsentAmount: "Mostrar monto para confirmar",
    existingCase: "Ya hay una recepción simulada registrada para este cargo",
    existingCaseNote:
      "Este comprobante local acredita el registro simulado. No indica una devolución, una disputa resuelta ni atención humana.",
    preparedEvidenceUnavailable:
      "No pudimos vincular los datos preparados con este cargo y snapshot. Consulta el estado antes de confirmar.",
    receiptLabel: "Comprobante local",
    priorReceiptLabel: "Comprobante local anterior",
    priorReceiptTitle: "Recepción simulada anterior verificada",
    priorReceiptNote:
      "Este es el registro simulado anterior. No confirma el resultado de una nueva solicitud.",
    savedReview: "Solicitud de revisión guardada",
    savedReviewNote:
      "El paquete de revisión está guardado. No hay respuesta humana registrada; esto no confirma que una persona haya tomado la solicitud.",
    handoffLabel: "Referencia de revisión",
    priorHandoffLabel: "Referencia de revisión anterior",
    priorHandoffTitle: "Solicitud general anterior guardada",
    priorHandoffNote:
      "Esta es la solicitud guardada anterior. No confirma el resultado de una nueva solicitud.",
    savedAt: "Registrado el",
    snapshot: "Snapshot histórico",
    servingSnapshot: "Snapshot de esta consulta",
    receiptSnapshot: "Snapshot del registro original",
    simulatedStatus: "Estado del registro simulado",
    received: "Recibido",
    factsAsOf: "Snapshot consultado el",
    snapshotReadNotice:
      "Esta consulta del snapshot no actualiza los registros bancarios.",
    factsSource: "Origen de los hechos",
    ownedSnapshot: "Lectura de tu movimiento en el snapshot",
    currentness: {
      same_snapshot:
        "Los hechos corresponden al snapshot disponible en la lectura verificada.",
      different_snapshot:
        "Los hechos se guardaron con un snapshot anterior. No confirman el estado actual del movimiento.",
      unknown:
        "No se pudo verificar si el snapshot guardado coincide con el disponible.",
      not_applicable: "Solicitud general sin movimiento asociado.",
    },
    processDate: "Fecha de procesamiento",
    status: "Estado registrado del movimiento",
    reasonLabel: "Motivo de la revisión",
    questions: "Preguntas pendientes registradas",
    noQuestions: "No se registraron preguntas pendientes en este paquete.",
    questionDraft: "Preguntas para la revisión (opcional)",
    questionDraftHint:
      "Una pregunta por línea; hasta 8 preguntas de 240 caracteres. Se guardan solo cuando solicitas la revisión.",
    questionDraftInvalid: "Usa hasta 8 preguntas, de 240 caracteres cada una.",
    retryHandoff: "Verificar revisión humana pendiente",
    preferHuman: "Prefiero revisión humana",
    preparing: "Estamos verificando la preparación de esta solicitud.",
    pendingConfirmation:
      "La recepción simulada está preparada. Confirma solo si quieres registrarla para este cargo.",
    intakeVerified: "La recepción simulada quedó verificada.",
    handoffVerified:
      "La solicitud de revisión quedó guardada. No hay respuesta humana registrada.",
    unverified:
      "No pudimos verificar la solicitud anterior. Consulta su estado antes de continuar.",
    recoveryExhausted:
      "Se agotó la recuperación segura. La solicitud sigue sin resolver y bloqueada. La referencia visible no avisa al equipo ni indica que alguien la haya tomado.",
    recoveryExhaustedWithoutReference:
      "Se agotó la recuperación segura. La solicitud sigue sin resolver y bloqueada. Pide ayuda al equipo que te dio acceso a la demo.",
    reviewReference: "Referencia para revisión",
    shareReviewReference:
      "Copia esta referencia y compártela con el equipo que te dio acceso a la demo.",
    statusFailed: "No pudimos verificar el estado. Intenta de nuevo más tarde.",
    initialStatusFailed:
      "No pudimos verificar la solicitud anterior. Consulta su estado antes de iniciar otra.",
    wrongCharge:
      "La solicitud recibida corresponde a otro cargo. Consulta su estado antes de continuar.",
    previousUnresolved:
      "Hay una solicitud anterior sin resolver. Revisa el cargo indicado y consulta su estado antes de continuar.",
    confirmUnverified:
      "No pudimos verificar la confirmación. Consulta el estado; no la repitas.",
    requestUnverified:
      "No pudimos verificar la solicitud. Consulta su estado antes de iniciar otra.",
    actionFailed:
      "No pudimos verificar esta acción. Consulta el estado antes de volver a intentarlo.",
    previousNotVerified:
      "Aún no pudimos verificar la solicitud anterior. No inicies otra.",
  },
  pt: {
    title: "Não reconhece uma cobrança?",
    disclosure:
      "O registro é uma simulação. Não bloqueia cartões, devolve dinheiro nem resolve uma contestação.",
    language: "Idioma desta resposta",
    pendingCharge: "Solicitação pendente para este lançamento",
    pendingReview: "Solicitação de análise pendente",
    noCharge: "Análise geral sem lançamento associado.",
    otherCharge:
      "A solicitação anterior continua vinculada ao lançamento indicado. O lançamento selecionado não pode confirmá-la nem substituí-la.",
    returnCharge: " Volte a esse lançamento para continuar.",
    checkOtherCharge: " Consulte o estado antes de realizar outra ação.",
    backToCharge: "Voltar ao lançamento pendente",
    verifyFirst:
      "Verifique o estado da solicitação antes de iniciar ou confirmar outra ação.",
    checkStatus: "Consultar estado da solicitação",
    reviewIntake: "Revisar registro simulado",
    confirmIntake: "Confirmo o registro simulado para",
    chargeReference: "Referência do lançamento",
    eventDate: "Data do lançamento",
    merchantNotReported: "Estabelecimento não informado",
    dateNotReported: "Data não informada",
    showConsentAmount: "Mostrar valor para confirmar",
    existingCase: "Já existe um registro simulado para este lançamento",
    existingCaseNote:
      "Este comprovante local confirma o registro simulado. Não indica uma devolução, uma contestação resolvida nem atendimento humano.",
    preparedEvidenceUnavailable:
      "Não foi possível vincular os dados preparados a este lançamento e snapshot. Consulte o estado antes de confirmar.",
    receiptLabel: "Comprovante local",
    priorReceiptLabel: "Comprovante local anterior",
    priorReceiptTitle: "Registro simulado anterior verificado",
    priorReceiptNote:
      "Este é o registro simulado anterior. Não confirma o resultado de uma nova solicitação.",
    savedReview: "Solicitação de análise salva",
    savedReviewNote:
      "O pacote de análise está salvo. Não há resposta humana registrada; isso não confirma que uma pessoa assumiu a solicitação.",
    handoffLabel: "Referência da análise",
    priorHandoffLabel: "Referência da análise anterior",
    priorHandoffTitle: "Solicitação geral anterior salva",
    priorHandoffNote:
      "Esta é a solicitação salva anterior. Não confirma o resultado de uma nova solicitação.",
    savedAt: "Registrado em",
    snapshot: "Snapshot histórico",
    servingSnapshot: "Snapshot desta consulta",
    receiptSnapshot: "Snapshot do registro original",
    simulatedStatus: "Estado do registro simulado",
    received: "Recebido",
    factsAsOf: "Snapshot consultado em",
    snapshotReadNotice:
      "Esta consulta do snapshot não atualiza os registros bancários.",
    factsSource: "Origem dos fatos",
    ownedSnapshot: "Consulta do seu lançamento no snapshot",
    currentness: {
      same_snapshot:
        "Os fatos correspondem ao snapshot disponível na consulta verificada.",
      different_snapshot:
        "Os fatos foram salvos com um snapshot anterior. Não confirmam o estado atual do lançamento.",
      unknown:
        "Não foi possível verificar se o snapshot salvo coincide com o disponível.",
      not_applicable: "Solicitação geral sem lançamento associado.",
    },
    processDate: "Data de processamento",
    status: "Estado registrado do lançamento",
    reasonLabel: "Motivo da análise",
    questions: "Perguntas pendentes registradas",
    noQuestions: "Nenhuma pergunta pendente foi registrada neste pacote.",
    questionDraft: "Perguntas para a análise (opcional)",
    questionDraftHint:
      "Uma pergunta por linha; até 8 perguntas de 240 caracteres. São salvas apenas quando você solicita a análise.",
    questionDraftInvalid: "Use até 8 perguntas, com 240 caracteres cada.",
    retryHandoff: "Verificar análise humana pendente",
    preferHuman: "Prefiro análise humana",
    preparing: "Estamos verificando a preparação desta solicitação.",
    pendingConfirmation:
      "O registro simulado está preparado. Confirme apenas se quiser registrá-lo para este lançamento.",
    intakeVerified: "O registro simulado foi verificado.",
    handoffVerified:
      "A solicitação de análise foi salva. Não há resposta humana registrada.",
    unverified:
      "Não foi possível verificar a solicitação anterior. Consulte o estado antes de continuar.",
    recoveryExhausted:
      "A recuperação segura se esgotou. A solicitação continua sem resolução e bloqueada. A referência visível não avisa a equipe nem indica que alguém assumiu o caso.",
    recoveryExhaustedWithoutReference:
      "A recuperação segura se esgotou. A solicitação continua sem resolução e bloqueada. Peça ajuda à equipe que lhe deu acesso à demonstração.",
    reviewReference: "Referência para análise",
    shareReviewReference:
      "Copie esta referência e compartilhe com a equipe que lhe deu acesso à demonstração.",
    statusFailed:
      "Não foi possível verificar o estado. Tente novamente mais tarde.",
    initialStatusFailed:
      "Não foi possível verificar a solicitação anterior. Consulte o estado antes de iniciar outra.",
    wrongCharge:
      "A solicitação recebida corresponde a outro lançamento. Consulte o estado antes de continuar.",
    previousUnresolved:
      "Há uma solicitação anterior sem resolução. Confira o lançamento indicado e consulte o estado antes de continuar.",
    confirmUnverified:
      "Não foi possível verificar a confirmação. Consulte o estado; não a repita.",
    requestUnverified:
      "Não foi possível verificar a solicitação. Consulte o estado antes de iniciar outra.",
    actionFailed:
      "Não foi possível verificar esta ação. Consulte o estado antes de tentar novamente.",
    previousNotVerified:
      "Ainda não foi possível verificar a solicitação anterior. Não inicie outra.",
  },
} as const;

const handoffReasons = {
  es: {
    customer_request: "Solicitaste revisión humana",
    out_of_policy:
      "La solicitud requiere revisión fuera de la recepción simulada",
    emergency: "Solicitaste ayuda urgente",
    clarification_exhausted: "Quedan datos por aclarar",
    high_risk: "Se necesita revisión adicional",
    missing_evidence: "Faltan datos verificables",
    duplicate_review: "Los movimientos similares requieren revisión",
    action_unverified: "La acción anterior sigue sin verificarse",
    no_match_exhausted: "No se pudo identificar el movimiento",
    tool_failure: "No se pudo completar la consulta de los datos",
  },
  pt: {
    customer_request: "Você solicitou análise humana",
    out_of_policy: "A solicitação requer análise fora do registro simulado",
    emergency: "Você solicitou ajuda urgente",
    clarification_exhausted: "Ainda há dados a esclarecer",
    high_risk: "É necessária uma análise adicional",
    missing_evidence: "Faltam dados verificáveis",
    duplicate_review: "Os lançamentos semelhantes requerem análise",
    action_unverified: "A ação anterior continua sem verificação",
    no_match_exhausted: "Não foi possível identificar o lançamento",
    tool_failure: "Não foi possível concluir a consulta dos dados",
  },
} as const;

const actionStatuses = {
  es: {
    Approved: "Aprobado",
    Pending: "Pendiente",
    Declined: "Rechazado",
    Reversed: "Revertido",
  },
  pt: {
    Approved: "Aprovado",
    Pending: "Pendente",
    Declined: "Recusado",
    Reversed: "Estornado",
  },
} as const;

const boundedText = (value: unknown, maximum: number): value is string =>
  typeof value === "string" && value.length <= maximum;
const plainQuestionCharacters = (value: string) =>
  Array.from(value).every((character) => {
    const point = character.codePointAt(0)!;
    return point >= 32 && (point < 0xd800 || point > 0xdfff);
  });
const questionText = (value: unknown): value is string =>
  typeof value === "string" &&
  value.length > 0 &&
  value.trim() === value &&
  Array.from(value).length <= 240 &&
  plainQuestionCharacters(value);
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const timestamp = (value: unknown): value is string =>
  boundedText(value, 40) &&
  /^\d{4}-\d{2}-\d{2}(?:T|$)/.test(value) &&
  Number.isFinite(Date.parse(value)) &&
  new Date(value.slice(0, 10) + "T12:00:00Z").toISOString().slice(0, 10) ===
    value.slice(0, 10);
const utcTimestamp = (value: unknown): value is string =>
  timestamp(value) && /T.*(?:Z|\+00:00)$/.test(value);
const snapshotName = (value: unknown): value is string =>
  typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value);

function verifiedFacts(value: unknown): value is ActionFacts {
  return (
    record(value) &&
    typeof value.transaction_reference === "string" &&
    /^txn_[a-f0-9]{12}$/.test(value.transaction_reference) &&
    timestamp(value.transaction_date) &&
    timestamp(value.process_date) &&
    typeof value.amount === "string" &&
    /^\d{1,18}(?:\.\d{1,8})?$/.test(value.amount) &&
    Number.isFinite(Number(value.amount)) &&
    typeof value.currency === "string" &&
    /^[A-Z]{3}$/.test(value.currency) &&
    typeof value.status === "string" &&
    Object.hasOwn(actionStatuses.es, value.status) &&
    (value.merchant === null || boundedText(value.merchant, 160)) &&
    boundedText(value.transaction_type, 80) &&
    boundedText(value.channel, 80) &&
    (value.product === null || boundedText(value.product, 80))
  );
}

function verifiedReceipt(value: unknown): value is IntakeReceipt {
  return (
    record(value) &&
    typeof value.id === "string" &&
    /^CMP-SBX-[A-Za-z0-9_-]{8}$/.test(value.id) &&
    value.kind === "simulated_intake" &&
    value.simulated === true &&
    value.status === "received" &&
    snapshotName(value.snapshot) &&
    utcTimestamp(value.created_at) &&
    verifiedFacts(value.transaction)
  );
}

function verifiedHandoff(action: ActionResult | null): HandoffPacket | null {
  const nested = action?.handoff;
  const packet: unknown =
    action?.state === "handoff_verified"
      ? nested
      : action?.state === "action_unverified" &&
          record(nested) &&
          nested.state === "handoff_verified"
        ? nested.handoff
        : null;
  if (
    !record(packet) ||
    typeof packet.id !== "string" ||
    !/^HOF-[A-Za-z0-9_-]{8}$/.test(packet.id) ||
    typeof packet.reason !== "string" ||
    !Object.hasOwn(handoffReasons.es, packet.reason) ||
    packet.human_responded !== false ||
    !utcTimestamp(packet.created_at) ||
    !record(packet.facts) ||
    !Array.isArray(packet.unanswered_questions) ||
    packet.unanswered_questions.length > 8 ||
    !packet.unanswered_questions.every(questionText) ||
    !(
      (verifiedFacts(packet.facts) &&
        snapshotName(packet.snapshot) &&
        record(packet.transaction_provenance) &&
        packet.transaction_provenance.source === "owned_serving_snapshot" &&
        packet.transaction_provenance.snapshot === packet.snapshot &&
        utcTimestamp(packet.transaction_provenance.as_of) &&
        ["same_snapshot", "different_snapshot", "unknown"].includes(
          String(packet.transaction_currentness),
        )) ||
      (Object.keys(packet.facts).length === 0 &&
        packet.snapshot === null &&
        packet.transaction_provenance === null &&
        packet.transaction_currentness === "not_applicable")
    )
  )
    return null;
  if (
    verifiedFacts(packet.facts) &&
    !(
      typeof action?.target_reference === "string" &&
      /^txn_[a-f0-9]{24}$/.test(action.target_reference)
    )
  )
    return null;
  return packet as HandoffPacket;
}

function priorReceiptForTarget(action: ActionResult | null, target?: string) {
  const prior = action?.prior_receipt;
  return record(prior) &&
    typeof prior.target_reference === "string" &&
    /^txn_[a-f0-9]{24}$/.test(prior.target_reference) &&
    prior.target_reference === target &&
    action?.target_reference === prior.target_reference &&
    verifiedReceipt(prior.receipt)
    ? prior
    : null;
}

function priorGeneralHandoff(action: ActionResult | null) {
  const prior = action?.prior_handoff;
  if (
    !record(prior) ||
    prior.target_reference !== null ||
    action?.target_reference
  )
    return null;
  const packet = verifiedHandoff({
    state: "handoff_verified",
    handoff: prior.handoff,
  });
  return packet && !verifiedFacts(packet.facts) ? packet : null;
}

function retainedEvidence(
  action: ActionResult | null,
  target?: string,
): Pick<ActionResult, "prior_receipt" | "prior_handoff"> {
  const previousReceipt = priorReceiptForTarget(action, target);
  const receipt =
    (action?.state === "intake_verified" ||
      action?.state === "existing_case_verified") &&
    typeof target === "string" &&
    /^txn_[a-f0-9]{24}$/.test(target) &&
    action.target_reference === target &&
    verifiedReceipt(action.receipt)
      ? { target_reference: target, receipt: action.receipt }
      : previousReceipt;
  const currentPacket =
    !target && !action?.target_reference ? verifiedHandoff(action) : null;
  const packet =
    currentPacket && !verifiedFacts(currentPacket.facts)
      ? currentPacket
      : !target
        ? priorGeneralHandoff(action)
        : null;
  return {
    ...(receipt ? { prior_receipt: receipt } : {}),
    ...(packet
      ? { prior_handoff: { target_reference: null, handoff: packet } }
      : {}),
  };
}

function evidenceAmount(
  facts: ActionFacts,
  language: ActionLanguage,
  hidden: boolean,
): string {
  if (hidden) return "••••••";
  const locale = language === "pt" ? "pt-BR" : "es-MX";
  const [whole, fraction = ""] = facts.amount.split(".");
  const decimal =
    new Intl.NumberFormat(locale)
      .formatToParts(1.1)
      .find((part) => part.type === "decimal")?.value || ".";
  return `${new Intl.NumberFormat(locale).format(BigInt(whole))}${decimal}${fraction.padEnd(2, "0")}`;
}

function preparedMatchesSelection(
  facts: ActionFacts,
  transaction: Transaction,
): boolean {
  const normalizedAmount = (amount: string) => {
    if (!/^\d+(?:\.\d+)?$/.test(amount)) return null;
    const [whole, fraction = ""] = amount.split(".");
    return `${BigInt(whole)}.${fraction.replace(/0+$/, "")}`;
  };
  return (
    facts.transaction_date.slice(0, 10) ===
      transaction.occurred_at.slice(0, 10) &&
    facts.process_date.slice(0, 10) === transaction.process_date.slice(0, 10) &&
    normalizedAmount(facts.amount) ===
      normalizedAmount(String(transaction.amount)) &&
    facts.currency === transaction.currency &&
    facts.status === transaction.status &&
    facts.merchant === ((transaction.merchant || "").slice(0, 160) || null) &&
    facts.transaction_type === (transaction.type || "").slice(0, 80) &&
    facts.channel === (transaction.channel || "").slice(0, 80)
  );
}

function EvidenceFacts({
  facts,
  language,
  hidden,
}: {
  facts: ActionFacts;
  language: ActionLanguage;
  hidden: boolean;
}) {
  const copy = actionCopy[language];
  return (
    <>
      <strong lang={facts.merchant ? "" : undefined}>
        {facts.merchant || copy.merchantNotReported}
      </strong>
      <dl>
        <div>
          <dt>{copy.eventDate}</dt>
          <dd>{actionDate(facts.transaction_date, language)}</dd>
        </div>
        <div>
          <dt>{copy.processDate}</dt>
          <dd>{actionDate(facts.process_date, language)}</dd>
        </div>
        <div>
          <dt>{facts.currency}</dt>
          <dd>
            {evidenceAmount(facts, language, hidden)} {facts.currency}
          </dd>
        </div>
        <div>
          <dt>{copy.status}</dt>
          <dd>
            {
              actionStatuses[language][
                facts.status as keyof typeof actionStatuses.es
              ]
            }
          </dd>
        </div>
      </dl>
    </>
  );
}

function ReceiptEvidence({
  receipt,
  targetReference,
  servingSnapshot,
  language,
  hidden,
  previous = false,
}: {
  receipt: IntakeReceipt;
  targetReference: string;
  servingSnapshot?: string;
  language: ActionLanguage;
  hidden: boolean;
  previous?: boolean;
}) {
  const copy = actionCopy[language];
  return (
    <section
      className={`action-evidence${previous ? " action-evidence-prior" : ""}`}
      aria-label={previous ? copy.priorReceiptLabel : copy.receiptLabel}
      lang={language === "pt" ? "pt-BR" : "es"}
    >
      <h4>{previous ? copy.priorReceiptTitle : copy.existingCase}</h4>
      {previous && <p>{copy.priorReceiptNote}</p>}
      <p>
        <strong>{copy.receiptLabel}:</strong> <code>{receipt.id}</code>
      </p>
      <p>
        <strong>{copy.chargeReference}:</strong> <code>{targetReference}</code>
      </p>
      <EvidenceFacts
        facts={receipt.transaction}
        language={language}
        hidden={hidden}
      />
      <dl>
        <div>
          <dt>{copy.simulatedStatus}</dt>
          <dd>{copy.received}</dd>
        </div>
        <div>
          <dt>{copy.receiptSnapshot}</dt>
          <dd>
            <code>{receipt.snapshot}</code>
          </dd>
        </div>
        {snapshotName(servingSnapshot) && (
          <div>
            <dt>{copy.servingSnapshot}</dt>
            <dd>
              <code>{servingSnapshot}</code>
            </dd>
          </div>
        )}
        <div>
          <dt>{copy.savedAt}</dt>
          <dd>{actionDate(receipt.created_at, language)}</dd>
        </div>
      </dl>
      <p>{copy.existingCaseNote}</p>
    </section>
  );
}

function HandoffEvidence({
  packet,
  targetReference,
  language,
  hidden,
  previous = false,
}: {
  packet: HandoffPacket;
  targetReference?: string;
  language: ActionLanguage;
  hidden: boolean;
  previous?: boolean;
}) {
  const copy = actionCopy[language];
  return (
    <section
      className={`action-evidence${previous ? " action-evidence-prior" : ""}`}
      aria-label={previous ? copy.priorHandoffLabel : copy.handoffLabel}
      lang={language === "pt" ? "pt-BR" : "es"}
    >
      <h4>{previous ? copy.priorHandoffTitle : copy.savedReview}</h4>
      {previous && <p>{copy.priorHandoffNote}</p>}
      <p>
        <strong>{copy.handoffLabel}:</strong> <code>{packet.id}</code>
      </p>
      {targetReference && (
        <p>
          <strong>{copy.chargeReference}:</strong>{" "}
          <code>{targetReference}</code>
        </p>
      )}
      <p>
        <strong>{copy.reasonLabel}:</strong>{" "}
        {
          handoffReasons[language][
            packet.reason as keyof typeof handoffReasons.es
          ]
        }
      </p>
      {verifiedFacts(packet.facts) && (
        <EvidenceFacts
          facts={packet.facts}
          language={language}
          hidden={hidden}
        />
      )}
      <dl>
        {packet.snapshot && (
          <div>
            <dt>{copy.snapshot}</dt>
            <dd>
              <code>{packet.snapshot}</code>
            </dd>
          </div>
        )}
        {packet.transaction_provenance && (
          <>
            <div>
              <dt>{copy.factsSource}</dt>
              <dd>{copy.ownedSnapshot}</dd>
            </div>
            <div>
              <dt>{copy.factsAsOf}</dt>
              <dd>
                {actionMoment(packet.transaction_provenance.as_of, language)}
              </dd>
            </div>
          </>
        )}
        <div>
          <dt>{copy.savedAt}</dt>
          <dd>{actionDate(packet.created_at, language)}</dd>
        </div>
      </dl>
      <p>{copy.currentness[packet.transaction_currentness]}</p>
      {packet.transaction_provenance && <p>{copy.snapshotReadNotice}</p>}
      {packet.unanswered_questions.length ? (
        <>
          <strong>{copy.questions}</strong>
          <ul>
            {packet.unanswered_questions.map((question, i) => (
              <li key={i} lang="">
                {question}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p>{copy.noQuestions}</p>
      )}
      <p>{copy.savedReviewNote}</p>
    </section>
  );
}

function actionDate(value: string, language: ActionLanguage): string {
  const eventDate = new Date(value.slice(0, 10) + "T12:00:00Z");
  return Number.isNaN(eventDate.valueOf())
    ? actionCopy[language].dateNotReported
    : new Intl.DateTimeFormat(language === "pt" ? "pt-BR" : "es-MX", {
        day: "2-digit",
        month: "long",
        year: "numeric",
        timeZone: "UTC",
      }).format(eventDate);
}

function actionMoment(value: string, language: ActionLanguage): string {
  return (
    new Intl.DateTimeFormat(language === "pt" ? "pt-BR" : "es-MX", {
      dateStyle: "long",
      timeStyle: "medium",
      timeZone: "UTC",
      hourCycle: "h23",
    }).format(new Date(value)) + " UTC"
  );
}

function fallbackActionMessage(
  action: ActionResult,
  language: ActionLanguage,
): string {
  const copy = actionCopy[language];
  if (action.recovery_exhausted)
    return action.review_reference
      ? copy.recoveryExhausted
      : copy.recoveryExhaustedWithoutReference;
  if (action.state === "preparing") return copy.preparing;
  if (action.state === "pending_confirmation") return copy.pendingConfirmation;
  if (action.state === "intake_verified" && verifiedReceipt(action.receipt))
    return copy.intakeVerified;
  if (
    action.state === "existing_case_verified" &&
    verifiedReceipt(action.receipt)
  )
    return copy.existingCase;
  if (action.state === "handoff_verified" && verifiedHandoff(action))
    return copy.handoffVerified;
  return copy.unverified;
}

const actionIsTerminal = (action: ActionResult | null) =>
  (action?.state === "intake_verified" && verifiedReceipt(action.receipt)) ||
  (action?.state === "handoff_verified" && Boolean(verifiedHandoff(action))) ||
  (action?.state === "existing_case_verified" &&
    typeof action.target_reference === "string" &&
    /^txn_[a-f0-9]{24}$/.test(action.target_reference) &&
    verifiedReceipt(action.receipt));

export function Assistant({
  open,
  status,
  selected,
  transactions,
  onSelectTransaction,
  hidden,
  synthetic,
  onClose,
  onExpired,
  initialLanguage = savedActionLanguage(),
  onLanguageChange,
}: {
  open: boolean;
  status: ChatStatus;
  selected: Transaction | null;
  transactions: Transaction[];
  onSelectTransaction: (transaction: Transaction) => void;
  hidden: boolean;
  synthetic: boolean;
  onClose: () => void;
  onExpired: () => void;
  initialLanguage?: ActionLanguage;
  onLanguageChange?: (language: ActionLanguage) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]),
    [input, setInput] = useState(""),
    [action, setAction] = useState<ActionResult | null>(null),
    [actionReady, setActionReady] = useState(false),
    [actionBusy, setActionBusy] = useState(false),
    [actionStatusLoading, setActionStatusLoading] = useState(false),
    [actionLanguage, setActionLanguage] =
      useState<ActionLanguage>(initialLanguage),
    [handoffRequestId, setHandoffRequestId] = useState<string>(() =>
      crypto.randomUUID(),
    ),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [historyReady, setHistoryReady] = useState(false),
    [historyLimited, setHistoryLimited] = useState(false),
    [historyAttempt, setHistoryAttempt] = useState(0),
    [consentAmountVisible, setConsentAmountVisible] = useState(false),
    [handoffQuestionDraft, setHandoffQuestionDraft] = useState("");
  const consentSummaryId = useId();
  const end = useRef<HTMLDivElement>(null),
    controller = useRef<AbortController | null>(null),
    alive = useRef(true),
    actionLanguageRef = useRef(actionLanguage),
    actionStatusSequence = useRef(0);
  const copy = actionCopy[actionLanguage];
  const ui = assistantCopy[actionLanguage];
  const uiLang = actionLanguage === "pt" ? "pt-BR" : "es";
  useEffect(() => {
    actionLanguageRef.current = actionLanguage;
    try {
      window.localStorage.setItem(ACTION_LANGUAGE_STORAGE, actionLanguage);
    } catch {
      // Private browsing may deny storage; the current visit still works.
    }
  }, [actionLanguage]);
  useEffect(() => {
    if (open) end.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy, open]);
  useEffect(() => {
    // A pending action belongs to its original charge, even when the visitor
    // opens another charge. Rotate only a completed or unused request ID.
    if (!action || actionIsTerminal(action))
      setHandoffRequestId(crypto.randomUUID());
    setHandoffQuestionDraft("");
  }, [selected?.reference]);
  useEffect(() => {
    setConsentAmountVisible(false);
  }, [
    action?.target_reference,
    action?.snapshot,
    action?.transaction?.amount,
    hidden,
  ]);
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
    setActionReady(false);
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
          if (!result.active && status.sandbox_intake_available) {
            const requestedLanguage = actionLanguageRef.current;
            const sequence = ++actionStatusSequence.current;
            setActionStatusLoading(true);
            api<ActionResult>(
              `/api/action/status?language=${requestedLanguage}`,
              {
                signal: historyController.signal,
              },
            )
              .then((recovered) => {
                if (
                  historyController.signal.aborted ||
                  !alive.current ||
                  sequence !== actionStatusSequence.current ||
                  requestedLanguage !== actionLanguageRef.current
                )
                  return;
                if (recovered.state !== "none") {
                  setAction(recovered);
                  if (recovered.request_id && !actionIsTerminal(recovered))
                    setHandoffRequestId(recovered.request_id);
                } else {
                  setAction((current) =>
                    current && !actionIsTerminal(current) ? current : null,
                  );
                }
                setActionReady(true);
              })
              .catch(() => {
                if (
                  !historyController.signal.aborted &&
                  alive.current &&
                  sequence === actionStatusSequence.current &&
                  requestedLanguage === actionLanguageRef.current
                ) {
                  setActionReady(false);
                  setError(actionCopy[requestedLanguage].initialStatusFailed);
                }
              })
              .finally(() => {
                if (alive.current && sequence === actionStatusSequence.current)
                  setActionStatusLoading(false);
              });
          } else if (!status.sandbox_intake_available) {
            setActionReady(true);
          }
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
            setError(assistantCopy[actionLanguageRef.current].historyError);
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
        setError(assistantCopy[actionLanguageRef.current].sendError);
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function loadActionStatus(
    language: ActionLanguage = actionLanguageRef.current,
  ) {
    const sequence = ++actionStatusSequence.current;
    setActionStatusLoading(true);
    try {
      const recovered = await api<ActionResult>(
        `/api/action/status?language=${language}`,
      );
      if (
        alive.current &&
        sequence === actionStatusSequence.current &&
        language === actionLanguageRef.current
      ) {
        if (recovered.state !== "none") {
          setAction(recovered);
          if (recovered.request_id && !actionIsTerminal(recovered))
            setHandoffRequestId(recovered.request_id);
        } else {
          // A transiently empty status cannot prove a local uncertain write safe.
          setAction((current) =>
            current && !actionIsTerminal(current) ? current : null,
          );
        }
        setActionReady(true);
      }
      return recovered;
    } finally {
      if (alive.current && sequence === actionStatusSequence.current)
        setActionStatusLoading(false);
    }
  }
  function changeActionLanguage(language: ActionLanguage) {
    const previousLanguage = actionLanguageRef.current;
    if (language === previousLanguage) return;
    actionLanguageRef.current = language;
    setActionLanguage(language);
    onLanguageChange?.(language);
    setAction((current) =>
      current ? { ...current, message: undefined } : current,
    );
    if (
      !status.available ||
      !status.sandbox_intake_available ||
      !historyReady
    ) {
      setError((current) =>
        current === assistantCopy[previousLanguage].historyError
          ? assistantCopy[language].historyError
          : current === assistantCopy[previousLanguage].sendError
            ? assistantCopy[language].sendError
            : current,
      );
      return;
    }
    setActionReady(false);
    setError("");
    void loadActionStatus(language).catch((e) => {
      if (!alive.current || language !== actionLanguageRef.current) return;
      if (e instanceof ApiError && e.status === 401) onExpired();
      else {
        setActionReady(false);
        setError(actionCopy[language].statusFailed);
      }
    });
  }
  async function runAction(path: string, body: Record<string, unknown>) {
    if (actionBusy || busy || !historyReady || !actionReady) return;
    const requestedReference =
      typeof body.transaction_reference === "string"
        ? body.transaction_reference
        : undefined;
    const continuesPendingHandle =
      typeof body.pending_handle === "string" &&
      body.pending_handle === action?.pending_handle;
    setActionBusy(true);
    setError("");
    try {
      const result = await api<ActionResult>(path, {
        method: "POST",
        body: JSON.stringify({ ...body, language: actionLanguage }),
      });
      if (alive.current) {
        if (
          requestedReference &&
          result.target_reference &&
          result.target_reference !== requestedReference
        ) {
          // Keep the server's saved target visible; never relabel it with the
          // newly selected charge when a response disagrees with the request.
          setAction(result);
          setActionReady(false);
          setError(copy.wrongCharge);
          return;
        }
        setAction({
          ...result,
          target_reference:
            result.target_reference ??
            requestedReference ??
            (continuesPendingHandle ? action?.target_reference : undefined),
        });
        if (actionIsTerminal(result)) setHandoffRequestId(crypto.randomUUID());
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        onExpired();
      } else if (alive.current) {
        if (e instanceof ApiError && e.status === 409) {
          // The server keeps the original pending charge. Recover that target
          // instead of replacing it with the newly selected charge.
          setActionReady(false);
          try {
            await loadActionStatus();
          } catch {
            setActionReady(false);
          }
          setError(copy.previousUnresolved);
        } else {
          const uncertain =
            !(e instanceof ApiError) ||
            e.status >= 500 ||
            path === "/api/action/confirm";
          if (uncertain) {
            setActionReady(false);
            setAction((current) => {
              if (current && !actionIsTerminal(current)) {
                return path === "/api/action/confirm"
                  ? {
                      ...current,
                      state: "action_unverified",
                      message: copy.confirmUnverified,
                    }
                  : current;
              }
              return {
                ...retainedEvidence(current, requestedReference),
                state:
                  path === "/api/action/prepare"
                    ? "prepare_unverified"
                    : "handoff_unverified",
                target_reference: requestedReference,
                request_id:
                  typeof body.request_id === "string"
                    ? body.request_id
                    : undefined,
                message: copy.requestUnverified,
              };
            });
          }
          setError(copy.actionFailed);
        }
      }
    } finally {
      if (alive.current) setActionBusy(false);
    }
  }
  async function refreshAction() {
    if (actionBusy || actionStatusLoading || busy || !historyReady) return;
    setActionBusy(true);
    try {
      const recovered = await loadActionStatus();
      if (alive.current && recovered.state !== "none") {
        setError("");
      } else if (alive.current && action && !actionIsTerminal(action)) {
        setActionReady(false);
        setError(copy.previousNotVerified);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onExpired();
      else if (alive.current) {
        setActionReady(false);
        setError(copy.statusFailed);
      }
    } finally {
      if (alive.current) setActionBusy(false);
    }
  }
  const actionBlocksNewCharge =
    action !== null && action.state !== "none" && !actionIsTerminal(action);
  const actionTarget = transactions.find(
    (transaction) => transaction.reference === action?.target_reference,
  );
  const selectedIsActionTarget =
    Boolean(actionTarget) && selected?.reference === action?.target_reference;
  const canUsePendingTarget =
    actionReady && selectedIsActionTarget && Boolean(action?.pending_handle);
  const preparedFacts =
    actionTarget &&
    verifiedFacts(action?.transaction) &&
    snapshotName(action?.snapshot) &&
    preparedMatchesSelection(action.transaction, actionTarget)
      ? action.transaction
      : null;
  const canConfirmPendingTarget = canUsePendingTarget && Boolean(preparedFacts);
  const existingSelectedCase =
    (action?.state === "existing_case_verified" ||
      action?.state === "intake_verified") &&
    selected?.reference === action.target_reference &&
    verifiedReceipt(action.receipt);
  const needsFreshReceiptReview =
    existingSelectedCase && action?.state === "intake_verified";
  const canStartAction =
    actionReady && !actionBlocksNewCharge && !existingSelectedCase;
  const receipt =
    (action?.state === "existing_case_verified" ||
      action?.state === "intake_verified") &&
    typeof action.target_reference === "string" &&
    /^txn_[a-f0-9]{24}$/.test(action.target_reference) &&
    verifiedReceipt(action.receipt)
      ? action.receipt
      : null;
  const handoffPacket = verifiedHandoff(action);
  const priorReceipt = priorReceiptForTarget(action, selected?.reference);
  const priorHandoff = priorGeneralHandoff(action);
  const canRetryHandoff =
    actionReady &&
    (action?.state === "handoff_unverified" ||
      (action?.state === "action_unverified" &&
        action.handoff?.state === "handoff_unverified" &&
        action.reason === "action_unverified")) &&
    Boolean(action.reason) &&
    (action.target_reference
      ? canUsePendingTarget
      : Boolean(action.request_id) && !action.pending_handle);
  const canRequestHandoff =
    canStartAction ||
    (canUsePendingTarget &&
      (action?.state === "pending_confirmation" || existingSelectedCase)) ||
    canRetryHandoff;
  const handoffQuestionLines = handoffQuestionDraft.split(/\r?\n/);
  const handoffQuestions = handoffQuestionLines
    .map((question) => question.trim())
    .filter(Boolean);
  const handoffQuestionsValid =
    handoffQuestionLines.every(plainQuestionCharacters) &&
    handoffQuestions.length <= 8 &&
    handoffQuestions.every(questionText);
  // Closing the dialog keeps this authenticated component alive. A running
  // query can finish and its visible transcript will be here on reopening.
  if (!open) return null;
  return (
    <Modal
      title={ui.title}
      titleLang={uiLang}
      closeLabel={ui.close}
      onClose={onClose}
      wide
    >
      <label className="assistant-language" lang={uiLang}>
        <span>{ui.language}</span>
        <select
          value={actionLanguage}
          disabled={actionBusy || busy}
          onChange={(e) =>
            changeActionLanguage(e.target.value as ActionLanguage)
          }
        >
          <option value="es" lang="es">
            Español
          </option>
          <option value="pt" lang="pt-BR">
            Português
          </option>
        </select>
      </label>
      <div className="assistant-status" lang={uiLang}>
        <span className="assistant-orb">
          <Sparkles size={18} />
        </span>
        <div>
          <strong>{ui.tagline}</strong>
          <span>
            {status.available
              ? status.sandbox_intake_available
                ? ui.connectedIntake
                : ui.connectedReadOnly
              : ui.unavailable}
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
      {status.sandbox_intake_available &&
        historyReady &&
        (messages.length > 0 || action) && (
          <div className="action-panel" lang={uiLang}>
            <strong lang={uiLang}>{copy.title}</strong>
            <p lang={uiLang}>{copy.disclosure}</p>
            {action && (
              <p role="status" className="action-result">
                {action.message ||
                  fallbackActionMessage(action, actionLanguage)}
              </p>
            )}
            {receipt && action?.target_reference && (
              <ReceiptEvidence
                receipt={receipt}
                targetReference={action.target_reference}
                servingSnapshot={action.snapshot}
                language={actionLanguage}
                hidden={hidden}
              />
            )}
            {handoffPacket && (
              <HandoffEvidence
                packet={handoffPacket}
                targetReference={action?.target_reference}
                language={actionLanguage}
                hidden={hidden}
              />
            )}
            {priorReceipt && priorReceipt.receipt.id !== receipt?.id && (
              <ReceiptEvidence
                previous
                receipt={priorReceipt.receipt}
                targetReference={priorReceipt.target_reference}
                language={actionLanguage}
                hidden={hidden}
              />
            )}
            {priorHandoff && priorHandoff.id !== handoffPacket?.id && (
              <HandoffEvidence
                previous
                packet={priorHandoff}
                language={actionLanguage}
                hidden={hidden}
              />
            )}
            {action?.recovery_exhausted && action.review_reference && (
              <p className="action-result">
                <strong>{copy.reviewReference}:</strong>{" "}
                <code>{action.review_reference}</code>
                <br />
                {copy.shareReviewReference}
              </p>
            )}
            {actionBlocksNewCharge && (
              <div
                className="chat-selection action-charge-summary"
                role="status"
                id={consentSummaryId}
              >
                {actionTarget && <TxIcon transaction={actionTarget} />}
                <span>
                  <strong>
                    {action?.target_reference
                      ? copy.pendingCharge
                      : copy.pendingReview}
                  </strong>
                  <small>
                    {preparedFacts ? (
                      <>
                        <span lang={preparedFacts.merchant ? "" : undefined}>
                          {preparedFacts.merchant || copy.merchantNotReported}
                        </span>
                        <span>
                          {copy.eventDate}:{" "}
                          {actionDate(
                            preparedFacts.transaction_date,
                            actionLanguage,
                          )}
                        </span>
                        <span>
                          {evidenceAmount(
                            preparedFacts,
                            actionLanguage,
                            hidden && !consentAmountVisible,
                          )}{" "}
                          {preparedFacts.currency}
                        </span>
                        <span>
                          {copy.snapshot}: <code>{action!.snapshot}</code>
                        </span>
                        <span>
                          {copy.chargeReference}:{" "}
                          <code>{action!.target_reference}</code>
                        </span>
                      </>
                    ) : (
                      action?.target_reference || copy.noCharge
                    )}
                  </small>
                </span>
              </div>
            )}
            {actionBlocksNewCharge &&
              action?.target_reference &&
              !selectedIsActionTarget && (
                <p className="modal-disclosure">
                  {copy.otherCharge}
                  {actionTarget ? copy.returnCharge : copy.checkOtherCharge}
                </p>
              )}
            {actionBlocksNewCharge &&
              actionTarget &&
              !selectedIsActionTarget && (
                <button
                  type="button"
                  className="button outline"
                  onClick={() => onSelectTransaction(actionTarget)}
                >
                  {copy.backToCharge}
                </button>
              )}
            {!actionReady && (
              <p className="modal-disclosure">{copy.verifyFirst}</p>
            )}
            {action?.state === "pending_confirmation" &&
              canUsePendingTarget &&
              !preparedFacts && (
                <p className="modal-disclosure" role="alert">
                  {copy.preparedEvidenceUnavailable}
                </p>
              )}
            <button
              type="button"
              className="button outline"
              disabled={actionBusy || actionStatusLoading || busy}
              onClick={refreshAction}
            >
              {copy.checkStatus}
            </button>
            {selected && canStartAction && (
              <button
                type="button"
                className="button outline"
                disabled={actionBusy || busy}
                onClick={() =>
                  runAction("/api/action/prepare", {
                    transaction_reference: selected.reference,
                    request_id: handoffRequestId,
                  })
                }
              >
                {copy.reviewIntake}
              </button>
            )}
            {action?.state === "pending_confirmation" &&
              canConfirmPendingTarget &&
              preparedFacts && (
                <>
                  {hidden && !consentAmountVisible && (
                    <button
                      type="button"
                      className="button outline"
                      onClick={() => setConsentAmountVisible(true)}
                    >
                      {copy.showConsentAmount}
                    </button>
                  )}
                  <button
                    type="button"
                    className="button primary action-confirm"
                    aria-describedby={consentSummaryId}
                    disabled={
                      actionBusy || busy || (hidden && !consentAmountVisible)
                    }
                    onClick={() =>
                      runAction("/api/action/confirm", {
                        pending_handle: action.pending_handle,
                        transaction_reference: action.target_reference,
                        confirmed: true,
                      })
                    }
                  >
                    <span>
                      {copy.confirmIntake}{" "}
                      <span lang={preparedFacts.merchant ? "" : undefined}>
                        {preparedFacts.merchant || copy.merchantNotReported}
                      </span>
                    </span>
                    <small>
                      {copy.chargeReference}: {action.target_reference}
                    </small>
                  </button>
                </>
              )}
            {canRequestHandoff && (
              <>
                {!canRetryHandoff && (
                  <label className="action-questions">
                    <span id={`${consentSummaryId}-questions-label`}>
                      {copy.questionDraft}
                    </span>
                    <textarea
                      rows={3}
                      value={handoffQuestionDraft}
                      lang=""
                      aria-labelledby={`${consentSummaryId}-questions-label`}
                      disabled={actionBusy || busy}
                      aria-describedby={`${consentSummaryId}-questions-hint`}
                      aria-invalid={!handoffQuestionsValid}
                      onChange={(event) =>
                        setHandoffQuestionDraft(event.target.value)
                      }
                    />
                    <small id={`${consentSummaryId}-questions-hint`}>
                      {copy.questionDraftHint}
                    </small>
                    {!handoffQuestionsValid && (
                      <span role="alert">{copy.questionDraftInvalid}</span>
                    )}
                  </label>
                )}
                <button
                  type="button"
                  className="button outline"
                  disabled={
                    actionBusy ||
                    busy ||
                    (!canRetryHandoff && !handoffQuestionsValid)
                  }
                  onClick={() => {
                    if (canRetryHandoff && action?.reason) {
                      runAction("/api/action/handoff", {
                        reason: action.reason,
                        ...(action.request_id
                          ? { request_id: action.request_id }
                          : {}),
                        ...(action.pending_handle
                          ? { pending_handle: action.pending_handle }
                          : {}),
                        ...(action.target_reference
                          ? { transaction_reference: action.target_reference }
                          : {}),
                      });
                      return;
                    }
                    runAction("/api/action/handoff", {
                      reason: "customer_request",
                      ...(needsFreshReceiptReview
                        ? {}
                        : {
                            request_id:
                              canStartAction && !selected
                                ? crypto.randomUUID()
                                : handoffRequestId,
                          }),
                      unanswered_questions: handoffQuestions,
                      ...(canUsePendingTarget &&
                      action?.pending_handle &&
                      !needsFreshReceiptReview
                        ? {
                            pending_handle: action.pending_handle,
                            transaction_reference: action.target_reference,
                          }
                        : selected
                          ? { transaction_reference: selected.reference }
                          : {}),
                    });
                  }}
                >
                  {canRetryHandoff ? copy.retryHandoff : copy.preferHuman}
                </button>
              </>
            )}
          </div>
        )}
      <div className="chat-messages" aria-live="polite">
        {historyLimited && (
          <p className="modal-disclosure" lang={uiLang}>
            {ui.historyLimited}
          </p>
        )}
        {status.available && !historyReady && !error ? (
          <div className="chat-thinking" lang={uiLang}>
            <LoaderCircle size={16} className="spin" />
            {ui.recovering}
          </div>
        ) : messages.length === 0 && !busy ? (
          <div className="chat-welcome" lang={uiLang}>
            <MessageCircle size={30} />
            <h3>{ui.welcome}</h3>
            <p>{selected ? ui.selectedHelp : ui.generalHelp}</p>
            <div className="chat-prompts">
              {(selected ? ui.selectedPrompts : ui.generalPrompts).map(
                (text) => (
                  <button
                    key={text}
                    disabled={!status.available || !historyReady}
                    onClick={() => send(text)}
                  >
                    {text}
                    <ArrowUpRight size={16} />
                  </button>
                ),
              )}
            </div>
          </div>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={`chat-message ${m.role}`}>
              <span lang={uiLang}>
                {m.role === "assistant" ? "Savia" : ui.you}
              </span>
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
          <div className="chat-thinking" lang={uiLang}>
            <LoaderCircle size={16} className="spin" />
            {ui.thinking}
          </div>
        )}
        {error && (
          <div role="alert" className="form-error" lang={uiLang}>
            <p>{error}</p>
            {!historyReady && (
              <button
                className="button outline"
                onClick={() => setHistoryAttempt((attempt) => attempt + 1)}
              >
                {ui.recover}
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
          aria-label={ui.messageLabel}
          lang={uiLang}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            status.available
              ? ui.messagePlaceholder
              : ui.disconnectedPlaceholder
          }
          maxLength={2000}
          disabled={!status.available || !historyReady || busy}
        />
        <button
          aria-label={ui.sendLabel}
          lang={uiLang}
          disabled={!status.available || !historyReady || busy || !input.trim()}
        >
          <Send size={19} />
        </button>
      </form>
      <p className="modal-disclosure" lang={uiLang}>
        {synthetic ? ui.syntheticDisclosure : ui.dataDisclosure}
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
    [actionLanguagePreference, setActionLanguagePreference] =
      useState<ActionLanguage>(savedActionLanguage),
    [loginNotice, setLoginNotice] = useState<"" | "session-revoke-unconfirmed">(
      "",
    );
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
        setLoginNotice("session-revoke-unconfirmed");
        expired();
        setPage("home");
        return;
      }
      setToast(
        actionLanguagePreference === "pt"
          ? "Não foi possível encerrar a sessão. Tente novamente."
          : "No pudimos cerrar la sesión. Intenta de nuevo.",
      );
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
        initialLanguage={actionLanguagePreference}
        onLanguageChange={setActionLanguagePreference}
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
  const pt = actionLanguagePreference === "pt";
  const shellLang = pt ? "pt-BR" : "es";
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
          ptTypes[t.type],
          t.channel,
          t.currency,
          t.reference,
        ]
          .join(" ")
          .toLocaleLowerCase(pt ? "pt-BR" : "es")
          .includes(query.toLocaleLowerCase(pt ? "pt-BR" : "es"))),
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
    setToast(
      pt
        ? "Seus movimentos foram baixados em CSV."
        : "Tus movimientos se descargaron en CSV.",
    );
  }
  return (
    <div className="app-shell">
      <aside
        className={`sidebar ${mobileMenu ? "mobile-open" : ""}`}
        lang={shellLang}
      >
        <div className="sidebar-brand">
          <Brand />
          <button
            className="icon-button mobile-close"
            aria-label={pt ? "Fechar menu" : "Cerrar menú"}
            onClick={() => setMobileMenu(false)}
          >
            <X size={21} />
          </button>
        </div>
        <span className="sidebar-label">
          {pt ? "SEU ESPAÇO PESSOAL" : "TU ESPACIO PERSONAL"}
        </span>
        <nav>
          {nav.map((n) => (
            <button
              className={page === n.id ? "active" : ""}
              key={n.id}
              onClick={() => navigate(n.id)}
            >
              <n.icon size={20} />
              <span>{pt ? n.pt : n.label}</span>
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
            <span>{pt ? "Assistente" : "Asistente"}</span>
            <span className="nav-new">
              {chatStatus.available ? "FLUJO" : pt ? "EM BREVE" : "PRONTO"}
            </span>
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-help">
            <span className="help-leaf">
              <Leaf size={21} />
            </span>
            <strong>
              {pt ? "Tudo um pouco mais claro." : "Todo un poco más claro."}
            </strong>
            <p>
              {chatStatus.available
                ? pt
                  ? "Entenda um movimento com a ajuda do Assistente."
                  : "Entiende un movimiento con ayuda de tu asistente."
                : pt
                  ? "Confira os detalhes de cada cobrança no seu histórico."
                  : "Revisa los detalles de cada cargo en tu historial."}
            </p>
            <button onClick={() => openChat()}>
              {chatStatus.available
                ? pt
                  ? "Vamos conversar"
                  : "Hablemos"
                : pt
                  ? "Status do Assistente"
                  : "Estado del asistente"}
              <ArrowUpRight size={16} />
            </button>
          </div>
          <button className="sidebar-info" onClick={() => setInfo(true)}>
            <ShieldCheck size={18} />
            {pt ? "Sobre esta experiência" : "Sobre esta experiencia"}
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
              aria-label={pt ? "Encerrar sessão" : "Cerrar sesión"}
              title={pt ? "Encerrar sessão" : "Cerrar sesión"}
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
          aria-label={pt ? "Fechar menu" : "Cerrar menú"}
          onClick={() => setMobileMenu(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar" lang={shellLang}>
          <div className="topbar-title">
            <button
              className="icon-button mobile-menu"
              aria-label={pt ? "Abrir menu" : "Abrir menú"}
              onClick={() => setMobileMenu(true)}
            >
              <Menu size={21} />
            </button>
            <span>
              {pt
                ? nav.find((n) => n.id === page)?.pt
                : nav.find((n) => n.id === page)?.label}
            </span>
          </div>
          <div className="topbar-actions">
            <label className="global-search">
              <Search size={17} />
              <input
                aria-label={pt ? "Buscar movimentos" : "Buscar movimientos"}
                placeholder={
                  pt ? "Buscar um movimento" : "Buscar un movimiento"
                }
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
              {synthetic
                ? pt
                  ? "Cenário sintético"
                  : "Escenario sintético"
                : pt
                  ? "Dados sintéticos do organizador"
                  : "Datos sintéticos del organizador"}
            </button>
            <button
              className="icon-button help-button"
              aria-label={
                pt ? "Informações da demonstração" : "Información de la demo"
              }
              onClick={() => setInfo(true)}
            >
              <CircleHelp size={20} />
            </button>
            {profile && <Avatar name={profile.alias} small />}
          </div>
        </header>
        <main
          className="main-content"
          lang={page === "transactions" ? shellLang : "es"}
        >
          {pt && page !== "transactions" && (
            <p className="data-footnote" lang="pt-BR">
              Esta área e as informações da demonstração continuam em espanhol.
              A interface de movimentos e do Assistente usa português quando
              disponível.
            </p>
          )}
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
                        : pt
                          ? "OS DETALHES FAZEM A DIFERENÇA"
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
                    ) : pt ? (
                      "Seu dinheiro em movimento."
                    ) : (
                      "Tu dinero en movimiento."
                    )}
                  </h1>
                  <p>
                    {page === "home"
                      ? "Qué bueno tener todo bajo control."
                      : page === "products"
                        ? "Una vista clara de tus cuentas, tarjetas y otros productos."
                        : pt
                          ? "Explore, filtre e entenda cada operação."
                          : "Explora, filtra y entiende cada operación."}
                  </p>
                </div>
                <span className="asof">
                  <span>
                    {page === "transactions" && pt
                      ? "Movimentos registrados até"
                      : "Movimientos registrados hasta"}
                  </span>
                  <strong>
                    {portalDate(
                      asOf,
                      page === "transactions" ? actionLanguagePreference : "es",
                    )}
                  </strong>
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
                  {pt && (
                    <p className="data-footnote" lang="pt-BR">
                      Início, a área de produtos, seus detalhes e as informações
                      da demonstração continuam em espanhol. Nomes de
                      estabelecimentos e dados da origem são exibidos como
                      recebidos.
                    </p>
                  )}
                  <div className="transactions-toolbar">
                    <div>
                      <span className="history-count">
                        {portalNumber(
                          filtered.length,
                          actionLanguagePreference,
                        )}
                      </span>
                      <span>
                        {pt ? "movimentos" : "movimientos"}{" "}
                        {filtered.length !== transactions.length
                          ? pt
                            ? "neste filtro"
                            : "en este filtro"
                          : pt
                            ? "no seu histórico"
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
                          placeholder={
                            pt
                              ? "Estabelecimento, operação ou moeda"
                              : "Comercio, operación o moneda"
                          }
                          aria-label={
                            pt ? "Filtrar movimentos" : "Filtrar movimientos"
                          }
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                        />
                      </label>
                      <label>
                        <span className="sr-only">
                          {pt ? "Produto" : "Producto"}
                        </span>
                        <select
                          aria-label={
                            pt ? "Filtrar por produto" : "Filtrar por producto"
                          }
                          value={productFilter}
                          onChange={(e) => setProductFilter(e.target.value)}
                        >
                          <option value="all">
                            {pt ? "Todos os produtos" : "Todos los productos"}
                          </option>
                          {products.map((p) => (
                            <option key={p.reference} value={p.reference}>
                              {portalProduct(p.type, actionLanguagePreference)}{" "}
                              · {p.reference.slice(-6).toUpperCase()}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span className="sr-only">
                          {pt ? "Status" : "Estado"}
                        </span>
                        <select
                          aria-label={
                            pt ? "Filtrar por status" : "Filtrar por estado"
                          }
                          value={status}
                          onChange={(e) => setStatus(e.target.value)}
                        >
                          <option value="all">
                            {pt ? "Todos os status" : "Todos los estados"}
                          </option>
                          {["Approved", "Pending", "Declined", "Reversed"].map(
                            (s) => (
                              <option key={s} value={s}>
                                {pt ? ptStatus[s] : statusNames[s]}
                              </option>
                            ),
                          )}
                        </select>
                      </label>
                      <label>
                        <span className="sr-only">{pt ? "Mês" : "Mes"}</span>
                        <select
                          aria-label={
                            pt
                              ? "Filtrar por mês do movimento"
                              : "Filtrar por mes del movimiento"
                          }
                          value={month}
                          onChange={(e) => setMonth(e.target.value)}
                        >
                          <option value="all">
                            {pt ? "Todo o histórico" : "Todo el historial"}
                          </option>
                          {months.map((m) => (
                            <option value={m} key={m}>
                              {pt
                                ? new Intl.DateTimeFormat("pt-BR", {
                                    month: "long",
                                    year: "numeric",
                                    timeZone: "UTC",
                                  }).format(new Date(m + "-01T12:00:00Z"))
                                : date(m + "-01", {
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
                          {pt ? "Limpar filtros" : "Limpiar filtros"}
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
                      language={actionLanguagePreference}
                    />
                    <div className="pagination">
                      <span>
                        {filtered.length
                          ? `${(pagination - 1) * 10 + 1}–${Math.min(pagination * 10, filtered.length)} de ${portalNumber(filtered.length, actionLanguagePreference)}`
                          : pt
                            ? "0 movimentos"
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
                          aria-label={
                            pt ? "Próxima página" : "Página siguiente"
                          }
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
                      {pt
                        ? "Valores sem sinal não têm direção informada na origem. Se o estabelecimento não constar, mostramos o tipo de operação e o canal."
                        : "Los montos sin signo no tienen una dirección indicada en el origen. Si un comercio no está informado, mostramos el tipo de operación y su canal."}
                    </p>
                  </div>
                </>
              )}
              <footer className="content-footer" lang={shellLang}>
                <span>
                  <Leaf size={15} />
                  {pt
                    ? "Savia · Seu dinheiro, com tranquilidade."
                    : "Savia · Tu dinero, en calma."}
                </span>
                <button onClick={() => setInfo(true)}>
                  <span className="live-dot" />
                  {synthetic
                    ? pt
                      ? "Protótipo sintético"
                      : "Prototipo sintético"
                    : pt
                      ? "Dados do hackathon"
                      : "Dataset del hackathon"}
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
          language={actionLanguagePreference}
          onClose={closeTx}
          onChat={() => openChat(selectedTx)}
        />
      )}
      <Assistant
        open={assistant}
        status={chatStatus}
        selected={chatSelection}
        transactions={transactions}
        onSelectTransaction={setChatSelection}
        hidden={hidden}
        synthetic={synthetic}
        onClose={closeAssistant}
        onExpired={expired}
        initialLanguage={actionLanguagePreference}
        onLanguageChange={setActionLanguagePreference}
      />
      {info && (
        <Modal
          title={
            synthetic
              ? "Un escenario para explorar"
              : "Datos sintéticos del organizador"
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
