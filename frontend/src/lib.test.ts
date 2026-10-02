import { describe, expect, it } from "vitest";
import { csvText } from "./lib";
import type { Transaction } from "./types";

const transaction: Transaction = {
  reference: "tx-001",
  product_reference: "card-001",
  occurred_at: "2026-06-17T10:30:00Z",
  process_date: "2026-06-18",
  type: "Purchase",
  category: "Shopping",
  amount: 12.5,
  currency: "BRL",
  status: "Approved",
  channel: "Card",
  merchant: null,
  country: "BR",
  city: "São Paulo",
  direction: "debit",
};

describe("transaction CSV locale", () => {
  it("exports Portuguese headers and portal terms, including a missing merchant fallback", () => {
    const rows = csvText([transaction], "pt").split("\r\n");
    expect(rows[0]).toBe(
      '\ufeff"Referência","Data do movimento","Data de processamento","Descrição","Tipo","Valor","Moeda","Status","Canal"',
    );
    expect(rows[1]).toBe(
      '"tx-001","2026-06-17T10:30:00Z","2026-06-18","Compra","Compra","12.5","BRL","Aprovado","Card"',
    );
  });

  it("exports Spanish headers and known type and status labels", () => {
    const rows = csvText(
      [{ ...transaction, merchant: "Loja Central" }],
      "es",
    ).split("\r\n");
    expect(rows[0]).toBe(
      '\ufeff"Referencia","Fecha del movimiento","Fecha de procesamiento","Descripción","Tipo","Monto","Moneda","Estado","Canal"',
    );
    expect(rows[1]).toBe(
      '"tx-001","2026-06-17T10:30:00Z","2026-06-18","Loja Central","Compra","12.5","BRL","Aprobado","Card"',
    );
  });

  it("preserves unknown values and CSV formula and quote protection", () => {
    const rows = csvText(
      [
        {
          ...transaction,
          reference: "=HYPERLINK(1)",
          merchant: '+"cobrança"',
          type: "Unknown type",
          status: "Unknown status",
          channel: "@terminal",
          amount: -12.5,
        },
      ],
      "pt",
    ).split("\r\n");
    expect(rows[1]).toBe(
      '"\'=HYPERLINK(1)","2026-06-17T10:30:00Z","2026-06-18","\'+""cobrança""","Unknown type","\'-12.5","BRL","Unknown status","\'@terminal"',
    );
  });
});
