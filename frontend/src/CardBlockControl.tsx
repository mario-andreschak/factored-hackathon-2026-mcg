import { useEffect, useRef, useState } from "react";
import { api } from "./lib";
import type { Product } from "./types";

type Result = {
  state: string;
  product_reference: string;
  pending_handle?: string;
  pending_handle_current?: boolean;
  message: string;
  simulated: true;
  real_bank_action: false;
  receipt?: {
    schema: string;
    id: string;
    status: string;
    simulated: boolean;
    real_bank_action: boolean;
    created_at: string;
  };
};

export function CardBlockControl({
  products,
  language,
  profileId = "",
  requested = false,
  onResult,
}: {
  products: Product[];
  language: "es" | "pt";
  profileId?: string;
  requested?: boolean;
  onResult?: (message: string) => void;
}) {
  const cards = products.filter(
    (p) => /tarjeta|cart[aã]o/i.test(p.type) && p.status === "Active",
  );
  const [reference, setReference] = useState(cards[0]?.reference || "");
  const [result, setResult] = useState<Result | null>(null);
  const [handle, setHandle] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(crypto.randomUUID());
  const pt = language === "pt";
  const storageKey = `savia.card-block.${profileId}.${reference}`;
  const verified =
    result?.state === "card_block_verified" &&
    result.product_reference === reference &&
    result.simulated === true &&
    result.real_bank_action === false &&
    result.receipt?.schema === "savia-simulated-card-block/v1" &&
    result.receipt.status === "blocked" &&
    result.receipt.simulated === true &&
    result.receipt.real_bank_action === false &&
    /^BLK-SBX-[A-Za-z0-9_-]{8}$/.test(result.receipt.id);

  async function run(
    operation: "prepare" | "confirm" | "receipt" | "status" | "cancel",
    savedHandle = handle,
  ) {
    setBusy(true);
    setError("");
    try {
      const next = await api<Result>("/api/cards/block", {
        method: "POST",
        body: JSON.stringify({
          product_reference: reference,
          operation,
          language,
          ...(operation === "prepare"
            ? { request_id: requestId.current }
            : operation === "status"
              ? savedHandle
                ? { pending_handle: savedHandle }
                : {}
              : { pending_handle: savedHandle }),
          ...(operation === "confirm" ? { confirmed: true } : {}),
        }),
      });
      if (
        next.product_reference !== reference ||
        next.simulated !== true ||
        next.real_bank_action !== false
      )
        throw new Error("Unverified response");
      if (
        next.state === "card_block_verified" &&
        (next.receipt?.schema !== "savia-simulated-card-block/v1" ||
          next.receipt.status !== "blocked" ||
          next.receipt.simulated !== true ||
          next.receipt.real_bank_action !== false ||
          !/^BLK-SBX-[A-Za-z0-9_-]{8}$/.test(next.receipt.id))
      )
        throw new Error("Unverified receipt");
      if (next.pending_handle) {
        setHandle(next.pending_handle);
        sessionStorage.setItem(storageKey, next.pending_handle);
      }
      setResult(next);
      if (
        operation === "status" &&
        next.state === "card_unblocked" &&
        next.pending_handle_current === false
      ) {
        // Server verified that this capability belongs to an earlier session.
        sessionStorage.removeItem(storageKey);
        setHandle(null);
        requestId.current = crypto.randomUUID();
      }
      if (next.state === "cancelled") {
        sessionStorage.removeItem(storageKey);
        setHandle(null);
        requestId.current = crypto.randomUUID();
      }
      if (
        operation !== "status" &&
        next.state === "card_block_verified" &&
        next.receipt?.status === "blocked" &&
        next.receipt.schema === "savia-simulated-card-block/v1" &&
        next.receipt.simulated === true &&
        next.receipt.real_bank_action === false &&
        /^BLK-SBX-[A-Za-z0-9_-]{8}$/.test(next.receipt.id)
      )
        onResult?.(next.message);
    } catch {
      setResult(null);
      setError(
        pt
          ? "Não foi possível verificar o bloqueio. Consulte o estado antes de continuar."
          : "No se pudo verificar el bloqueo. Consulta el estado antes de continuar.",
      );
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!cards.some((card) => card.reference === reference))
      setReference(cards[0]?.reference || "");
  }, [products, reference]);

  useEffect(() => {
    if (!reference) return;
    setResult(null);
    setError("");
    requestId.current = crypto.randomUUID();
    const saved = sessionStorage.getItem(storageKey);
    setHandle(saved);
    void run("status", saved);
  }, [storageKey]);

  if (!cards.length) return null;
  return (
    <details
      className="action-panel card-block-panel"
      open={requested || Boolean(handle)}
      lang={pt ? "pt-BR" : "es"}
    >
      <summary>
        <strong>
          {pt ? "Bloquear meu cartão agora" : "Bloquear mi tarjeta ahora"}
        </strong>
      </summary>
      <p>
        {pt
          ? "Proteção imediata no ambiente de demonstração. A ação altera o estado persistido do seu cartão fictício; não há conexão com um banco real."
          : "Protección inmediata en la demostración. La acción cambia el estado persistido de tu tarjeta ficticia; no hay conexión con un banco real."}
      </p>
      <label>
        {pt ? "Seu cartão" : "Tu tarjeta"}
        <select
          value={reference}
          disabled={busy || Boolean(handle)}
          onChange={(e) => setReference(e.target.value)}
        >
          {cards.map((p) => (
            <option key={p.reference} value={p.reference}>
              {p.type} · {p.currency} · Ref.{" "}
              {p.reference.slice(-6).toUpperCase()}
            </option>
          ))}
        </select>
      </label>
      {error && <p role="alert">{error}</p>}
      {verified ? (
        <div role="status">
          <strong>
            {pt
              ? "Bloqueado · estado verificado"
              : "Bloqueada · estado verificado"}
          </strong>
          <p>{result?.message}</p>
          <p>
            {pt ? "Recibo" : "Recibo"}: <code>{result?.receipt?.id}</code>
          </p>
        </div>
      ) : result?.state === "pending_confirmation" && handle ? (
        <div>
          <p>
            {pt
              ? "Confirme o bloqueio imediato deste cartão na demonstração."
              : "Confirma el bloqueo inmediato de esta tarjeta en la demostración."}
          </p>
          <button
            className="button primary"
            disabled={busy}
            onClick={() => void run("confirm")}
          >
            {pt
              ? "Confirmar bloqueio do meu cartão"
              : "Confirmar bloqueo de mi tarjeta"}
          </button>
          <button
            className="button secondary"
            disabled={busy}
            onClick={() => void run("cancel")}
          >
            {pt ? "Cancelar" : "Cancelar"}
          </button>
        </div>
      ) : (
        !handle && (
          <button
            className="button primary"
            disabled={busy}
            onClick={() => void run("prepare")}
          >
            {pt ? "Preparar bloqueio" : "Preparar bloqueo"}
          </button>
        )
      )}
      {handle && (
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void run("receipt")}
        >
          {pt ? "Consultar estado salvo" : "Consultar estado guardado"}
        </button>
      )}
      {handle && !verified && (
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void run("status")}
        >
          {pt ? "Consultar proteção atual" : "Consultar protección actual"}
        </button>
      )}
      {result?.state === "expired" && handle && (
        <button
          className="button primary"
          disabled={busy}
          onClick={() => {
            sessionStorage.removeItem(storageKey);
            setHandle(null);
            setResult(null);
            requestId.current = crypto.randomUUID();
            void run("prepare", null);
          }}
        >
          {pt ? "Preparar nova confirmação" : "Preparar nueva confirmación"}
        </button>
      )}
      {busy && <p role="status">{pt ? "Verificando…" : "Verificando…"}</p>}
    </details>
  );
}
