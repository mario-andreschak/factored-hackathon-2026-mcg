export type Profile = {
  id?: string;
  alias: string;
  country: string;
  city?: string;
  segment: string;
  primary_currency: string;
  description?: string;
};
export type Product = {
  reference: string;
  type: string;
  currency: string;
  balance: number;
  balance_kind: "deposit" | "credit" | "investment" | "other";
  credit_limit: number | null;
  interest_rate: number | null;
  status: string;
  opened_at: string;
  last_updated: string;
  last_transaction_at?: string | null;
  masked_number?: string | null;
};
export type Transaction = {
  reference: string;
  product_reference: string;
  occurred_at: string;
  process_date: string;
  type: string;
  category: string | null;
  amount: number;
  currency: string;
  status: string;
  channel: string;
  merchant: string | null;
  country: string;
  city: string | null;
  direction: "credit" | "debit" | "unknown";
};
export type Overview = {
  profile: Profile;
  products: Product[];
  transactions: Transaction[];
  summary: {
    balances_by_currency: {
      currency: string;
      deposit_balance: number;
      credit_balance: number;
      investment_balance: number;
      other_balance: number;
    }[];
    transaction_count: number;
    monthly_activity: {
      month: string;
      currency: string;
      inflow: number;
      outflow: number;
      unclassified: number;
      count: number;
    }[];
  };
  metadata: {
    dataset: string;
    build_id: string;
    source_fingerprint: string;
    snapshot_created_at: string;
    data_as_of: string;
    balances_note: string;
    amounts_note: string;
    transactions_returned: number;
    transactions_total: number;
    filtered_count: number;
    transactions_limit: number;
    transactions_offset: number;
    transactions_truncated: boolean;
    next_offset: number | null;
  };
};
export type ChatStatus = {
  available: boolean;
  mode?: string;
  reason?: string;
  read_only?: boolean;
  sandbox_intake_available?: boolean;
};
export type ChatSelection = Pick<
  Transaction,
  "reference" | "occurred_at" | "type" | "amount" | "currency" | "status"
>;
export type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  selection?: ChatSelection;
};

export type ActionFacts = {
  transaction_reference: string;
  transaction_date: string;
  process_date: string;
  amount: string;
  currency: string;
  status: string;
  merchant: string | null;
  transaction_type: string;
  channel: string;
  product: string | null;
};
export type IntakeReceipt = {
  id: string;
  kind: "simulated_intake";
  simulated: true;
  status: "received";
  snapshot: string;
  created_at: string;
  transaction: ActionFacts;
};
export type HandoffPacket = {
  state?: never;
  id: string;
  reason: string;
  snapshot: string | null;
  created_at: string;
  facts: ActionFacts | Record<string, never>;
  human_responded: false;
  transaction_currentness:
    "same_snapshot" | "different_snapshot" | "unknown" | "not_applicable";
  transaction_provenance: {
    source: "owned_serving_snapshot";
    snapshot: string;
    as_of: string;
  } | null;
  unanswered_questions: string[];
};
export type ActionResult = {
  state: string;
  query_id?: string;
  message?: string;
  pending_handle?: string;
  request_id?: string;
  reason?: string;
  target_reference?: string;
  recovery_exhausted?: boolean;
  review_reference?: string;
  snapshot?: string;
  transaction?: ActionFacts;
  receipt?: IntakeReceipt;
  handoff?: HandoffPacket | { state?: string; handoff?: HandoffPacket };
  prior_receipt?: { target_reference: string; receipt: IntakeReceipt };
  prior_handoff?: { target_reference: null; handoff: HandoffPacket };
};
