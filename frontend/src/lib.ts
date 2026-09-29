import type { Transaction } from "./types";
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}
export async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      typeof body.detail === "string"
        ? body.detail
        : "No pudimos completar la solicitud. Intenta de nuevo.",
      response.status,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const money = (value: number, currency: string, hidden = false) =>
  hidden
    ? "••••••"
    : new Intl.NumberFormat("es-MX", {
        style: "currency",
        currency,
        maximumFractionDigits: 2,
        minimumFractionDigits: 2,
      }).format(value);
export const number = (value: number) =>
  new Intl.NumberFormat("es-MX").format(value);
export function date(value: string, options?: Intl.DateTimeFormatOptions) {
  if (!value || Number.isNaN(Date.parse(value))) return "Sin fecha informada";
  return new Intl.DateTimeFormat(
    "es-MX",
    options || {
      day: "2-digit",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    },
  ).format(new Date(value.slice(0, 10) + "T12:00:00Z"));
}
export const typeNames: Record<string, string> = {
  Purchase: "Compra",
  Withdrawal: "Retiro",
  Transfer: "Transferencia",
  Payment: "Pago",
  Deposit: "Depósito",
  Adjustment: "Ajuste",
};
export const statusNames: Record<string, string> = {
  Approved: "Aprobado",
  Pending: "Pendiente",
  Declined: "Rechazado",
  Reversed: "Revertido",
  Active: "Activo",
  Blocked: "Bloqueado",
  Closed: "Cerrado",
  Suspended: "Suspendido",
  Inactive: "Inactivo",
};
export const categoryNames: Record<string, string> = {
  Food: "Alimentación",
  Other: "Otros",
  Services: "Servicios",
  Transport: "Transporte",
  Shopping: "Compras",
  Health: "Salud",
  Entertainment: "Entretenimiento",
  Travel: "Viajes",
  Utilities: "Servicios públicos",
};
export const label = (t: Transaction) =>
  t.merchant || typeNames[t.type] || t.type;
export const productShort = (type: string) =>
  ({
    "Cuenta Ahorro": "Cuenta de ahorro",
    "Cuenta Corriente": "Cuenta corriente",
    "Tarjeta Crédito": "Tarjeta de crédito",
    "Tarjeta Débito": "Tarjeta de débito",
    "Préstamo Personal": "Préstamo personal",
    "Préstamo Hipotecario": "Préstamo hipotecario",
    "Crédito Hipotecario": "Crédito hipotecario",
    Inversión: "Inversión",
  })[type] || type;
export function csv(transactions: Transaction[]) {
  const escape = (value: unknown) =>
    '"' +
    String(value ?? "")
      .replace(/^[=+@\-]/, "'$&")
      .replaceAll('"', '""') +
    '"';
  const rows = [
    [
      "Referencia",
      "Fecha del movimiento",
      "Fecha de procesamiento",
      "Descripción",
      "Tipo",
      "Monto",
      "Moneda",
      "Estado",
      "Canal",
    ],
    ...transactions.map((t) => [
      t.reference,
      t.occurred_at,
      t.process_date,
      label(t),
      t.type,
      t.amount,
      t.currency,
      t.status,
      t.channel,
    ]),
  ];
  const url = URL.createObjectURL(
    new Blob(
      ["\ufeff" + rows.map((r) => r.map(escape).join(",")).join("\r\n")],
      { type: "text/csv;charset=utf-8" },
    ),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "savia-movimientos.csv";
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
