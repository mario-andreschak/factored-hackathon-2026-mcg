import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ApiError, api } from "./lib";
import "./InquiryPanel.css";

type Language = "es" | "pt";
type Worker = { role: string; state: string; suggestion: string | null };
type InquiryEvent = {
  id: string | number;
  kind: string;
  at: number;
  message: string;
  role?: string;
};
type InquiryCase = {
  id: string;
  message: string;
  state: string;
  created_at: number;
  updated_at: number;
  next_check_at: number | null;
  next_step: string;
  status_message: string;
  workers: Worker[];
  events: InquiryEvent[];
  informational_only: true;
  bank_authority: false;
};
type CaseList = { items: InquiryCase[] };

const copy = {
  es: {
    title: "Ayuda con tu consulta",
    intro: "Puedes enviar una consulta informativa sobre un movimiento.",
    newInquiry: "Pedir ayuda a un equipo",
    prompt: "¿Qué necesitas aclarar?",
    submit: "Enviar consulta",
    submitting: "Enviando…",
    helpful: "Esta respuesta resolvió mi consulta",
    loading: "Cargando consultas…",
    empty: "Aún no tienes consultas.",
    events: "Actualizaciones",
    suggestions: "Sugerencias del equipo",
    next: "Siguiente paso",
    refreshError: "No pudimos cargar las consultas. Intenta de nuevo.",
    serviceError:
      "El servicio de ayuda no está disponible ahora. Intenta más tarde.",
    genericError: "No pudimos enviar la consulta. Intenta de nuevo.",
    states: {
      queued: "En espera",
      team_working: "En revisión",
      human_working: "En revisión por una persona",
      team_completed: "Respuesta disponible",
      awaiting_customer: "Esperando tu respuesta",
      needs_attention: "Requiere tu atención",
      informational_resolved: "Consulta informativa completada",
    },
    resolved: "Marcaste esta respuesta como útil para tu consulta.",
    status: "Estado informado por el equipo",
    updated: "Actualización de tu consulta",
  },
  pt: {
    title: "Ajuda com sua consulta",
    intro: "Você pode enviar uma consulta informativa sobre uma movimentação.",
    newInquiry: "Pedir ajuda a uma equipe",
    prompt: "O que você precisa esclarecer?",
    submit: "Enviar consulta",
    submitting: "Enviando…",
    helpful: "Esta resposta resolveu minha consulta",
    loading: "Carregando consultas…",
    empty: "Você ainda não tem consultas.",
    events: "Atualizações",
    suggestions: "Sugestões da equipe",
    next: "Próximo passo",
    refreshError: "Não foi possível carregar as consultas. Tente novamente.",
    serviceError:
      "O serviço de ajuda não está disponível agora. Tente mais tarde.",
    genericError: "Não foi possível enviar a consulta. Tente novamente.",
    states: {
      queued: "Na fila",
      team_working: "Em análise",
      human_working: "Em análise por uma pessoa",
      team_completed: "Resposta disponível",
      awaiting_customer: "Aguardando sua resposta",
      needs_attention: "Precisa da sua atenção",
      informational_resolved: "Consulta informativa concluída",
    },
    resolved: "Você marcou esta resposta como útil para sua consulta.",
    status: "Status informado pela equipe",
    updated: "Atualização da sua consulta",
  },
};

function stateLabel(state: string, language: Language) {
  return copy[language].states[state as keyof typeof copy.es.states] ?? state;
}

function formatUnix(value: number, language: Language) {
  const date = new Date(value * 1000);
  if (!Number.isFinite(value) || Number.isNaN(date.getTime())) return null;
  return {
    dateTime: date.toISOString(),
    label: new Intl.DateTimeFormat(language === "es" ? "es-ES" : "pt-BR", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(date),
  };
}

function friendlyError(error: unknown, language: Language, fallback: string) {
  if (error instanceof ApiError && error.status === 401) return null;
  if (error instanceof ApiError && error.status === 503)
    return copy[language].serviceError;
  return fallback;
}

export function InquiryPanel({
  language,
  transactionReference,
  message,
  onExpired,
  onContextUpdate,
}: {
  language: Language;
  transactionReference?: string | null;
  message?: string;
  onExpired: () => void;
  onContextUpdate?: () => void;
}) {
  const t = copy[language];
  const [items, setItems] = useState<InquiryCase[]>([]);
  const [draft, setDraft] = useState(message ?? "");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const previousStates = useRef<Map<string, string> | null>(null);
  const voiceEventCursors = useRef<Map<string, number>>(new Map());
  const hasLoadedCases = useRef(false);
  const [formOpen, setFormOpen] = useState(Boolean(message));
  const pollDelay = items.some((item) =>
    ["queued", "team_working"].includes(item.state),
  )
    ? 2_000
    : 15_000;

  const notifyVoiceHost = useCallback(
    (cases: InquiryCase[], fromCreate = false) => {
      const isVoiceCase = (item: InquiryCase) => {
        const eventId = item.events?.at(-1)?.id;
        return (
          /^i_[a-f0-9]{32}$/.test(item.id) &&
          typeof eventId === "number" &&
          Number.isSafeInteger(eventId) &&
          eventId > 0
        );
      };
      const initialCaseId = cases.find(isVoiceCase)?.id;
      for (const item of cases) {
        if (!/^i_[a-f0-9]{32}$/.test(item.id)) continue;
        const lastEvent = item.events?.at(-1);
        if (
          !lastEvent ||
          typeof lastEvent.id !== "number" ||
          !Number.isSafeInteger(lastEvent.id) ||
          lastEvent.id <= 0
        )
          continue;
        const previousEventId = voiceEventCursors.current.get(item.id);
        const isNewEvent =
          previousEventId !== undefined && previousEventId !== lastEvent.id;
        const isInitialCase =
          previousEventId === undefined &&
          !hasLoadedCases.current &&
          item.id === initialCaseId;
        const isNewCase =
          previousEventId === undefined && hasLoadedCases.current;
        if (
          window.parent !== window &&
          (isInitialCase || isNewCase || isNewEvent)
        ) {
          window.parent.postMessage(
            {
              type: "savia:inquiry-update",
              case_id: item.id,
              event_id: lastEvent.id,
            },
            window.location.origin,
          );
        }
        voiceEventCursors.current.set(item.id, lastEvent.id);
      }
      if (!fromCreate) hasLoadedCases.current = true;
    },
    [],
  );

  const refresh = useCallback(async () => {
    try {
      const result = await api<CaseList>(
        `/api/assistant/cases?language=${language}`,
      );
      const nextItems = Array.isArray(result.items) ? result.items : [];
      notifyVoiceHost(nextItems);
      const priorStates = previousStates.current;
      const changedItems = priorStates
        ? nextItems.filter(
            (item) =>
              priorStates.has(item.id) &&
              priorStates.get(item.id) !== item.state,
          )
        : [];
      if (changedItems.length) {
        const changed = changedItems[0];
        setNotice(changed.status_message || t.updated);
        window.dispatchEvent(
          new CustomEvent("savia:inquiries", {
            detail: {
              items: changedItems.map((item) => ({
                message: item.message,
                state: item.state,
                status_message: item.status_message,
                next_step: item.next_step,
                suggestions: [
                  "team_completed",
                  "awaiting_customer",
                  "informational_resolved",
                ].includes(item.state)
                  ? item.workers
                      .filter(
                        (worker) =>
                          worker.state === "completed" && worker.suggestion,
                      )
                      .map((worker) => worker.suggestion as string)
                  : [],
              })),
            },
          }),
        );
      }
      previousStates.current = new Map(
        nextItems.map((item) => [item.id, item.state]),
      );
      setItems(nextItems);
      setError("");
    } catch (reason) {
      const friendly = friendlyError(reason, language, t.refreshError);
      if (friendly === null) onExpired();
      else setError(friendly);
    } finally {
      setLoading(false);
    }
  }, [language, notifyVoiceHost, onExpired, t.refreshError, t.updated]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), pollDelay);
    return () => window.clearInterval(timer);
  }, [pollDelay, refresh]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    setError("");
    setNotice("");
    try {
      const created = await api<CaseList & { id: string }>(
        "/api/assistant/cases",
        {
          method: "POST",
          body: JSON.stringify({
            message: text,
            language,
            ...(transactionReference
              ? { transaction_reference: transactionReference }
              : {}),
          }),
        },
      );
      const createdCase = created.items?.find((item) => item.id === created.id);
      if (createdCase) notifyVoiceHost([createdCase], true);
      setDraft("");
      setFormOpen(false);
      onContextUpdate?.();
      await refresh();
    } catch (reason) {
      const friendly = friendlyError(reason, language, t.genericError);
      if (friendly === null) onExpired();
      else setError(friendly);
    } finally {
      setSending(false);
    }
  }

  async function markHelpful(id: string) {
    setError("");
    setNotice("");
    try {
      await api(`/api/assistant/cases/${encodeURIComponent(id)}/resolve`, {
        method: "POST",
        body: JSON.stringify({ resolved: true }),
      });
      setNotice(t.resolved);
      await refresh();
    } catch (reason) {
      const friendly = friendlyError(reason, language, t.genericError);
      if (friendly === null) onExpired();
      else setError(friendly);
    }
  }

  return (
    <section className="inquiry-panel" aria-labelledby="inquiry-title">
      <header className="inquiry-panel__header">
        <div>
          <h2 id="inquiry-title">{t.title}</h2>
          <p>{t.intro}</p>
        </div>
      </header>
      {error && (
        <p className="inquiry-panel__error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="inquiry-panel__notice" role="status" aria-live="polite">
          {notice}
        </p>
      )}
      {loading ? (
        <p className="inquiry-panel__muted">{t.loading}</p>
      ) : items.length === 0 ? (
        <p className="inquiry-panel__muted">{t.empty}</p>
      ) : (
        <div className="inquiry-panel__list">
          {items.map((item) => (
            <article className="inquiry-card" key={item.id}>
              <div className="inquiry-card__top">
                <p className="inquiry-card__message">{item.message}</p>
                <span className="inquiry-card__state">
                  {stateLabel(item.state, language)}
                </span>
              </div>
              {item.status_message && (
                <p className="inquiry-card__status-message">
                  {item.status_message}
                </p>
              )}
              {item.next_step && item.next_step !== item.status_message && (
                <p className="inquiry-card__next">
                  <strong>{t.next}:</strong> {item.next_step}
                </p>
              )}
              {item.events?.length > 0 && (
                <details>
                  <summary>
                    {t.events} ({item.events.length})
                  </summary>
                  <ol className="inquiry-card__events">
                    {item.events.map((entry) => {
                      const timestamp = formatUnix(entry.at, language);
                      return (
                        <li key={entry.id}>
                          <p>{entry.message}</p>
                          {timestamp && (
                            <time dateTime={timestamp.dateTime}>
                              {timestamp.label}
                            </time>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                </details>
              )}
              {[
                "team_completed",
                "awaiting_customer",
                "informational_resolved",
              ].includes(item.state) &&
                item.workers?.some(
                  (worker) => worker.state === "completed" && worker.suggestion,
                ) && (
                  <ul
                    className="inquiry-card__suggestions"
                    aria-label={t.suggestions}
                  >
                    {item.workers
                      .filter(
                        (worker) =>
                          worker.state === "completed" && worker.suggestion,
                      )
                      .map((worker, index) => (
                        <li key={`${worker.role}-${index}`}>
                          {worker.suggestion}
                        </li>
                      ))}
                  </ul>
                )}
              {["team_completed", "awaiting_customer"].includes(item.state) && (
                <button
                  className="inquiry-card__helpful"
                  type="button"
                  onClick={() => void markHelpful(item.id)}
                >
                  {t.helpful}
                </button>
              )}
            </article>
          ))}
        </div>
      )}
      <details
        className="inquiry-panel__new"
        open={formOpen}
        onToggle={(event) => setFormOpen(event.currentTarget.open)}
      >
        <summary>{t.newInquiry}</summary>
        <form className="inquiry-panel__form" onSubmit={submit}>
          <label htmlFor="inquiry-message">{t.prompt}</label>
          <textarea
            id="inquiry-message"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={3}
          />
          <button type="submit" disabled={!draft.trim() || sending}>
            {sending ? t.submitting : t.submit}
          </button>
        </form>
      </details>
    </section>
  );
}
