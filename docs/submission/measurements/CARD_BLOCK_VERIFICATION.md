# Immediate card protection: reproducible acceptance

Savia now changes the persisted status of an owned fictional card after an
explicit customer confirmation, and shows an independently reread `BLK-SBX-…`
receipt. This is a working simulated bank action; it does not call a real bank.

## Customer journey

1. Log into a demo profile with an active card.
2. Ask Savia **“bloquea mi tarjeta”** or **“bloqueie meu cartão”**. Native voice
   requests delegated to Savia use the same authenticated chat path.
3. In **Bloquear mi tarjeta ahora / Bloquear meu cartão agora**, select the owned
   card, prepare the action, and press the explicit confirmation button.
4. Observe the verified blocked status and saved receipt. The existing voice
   surface can narrate this server-verified outcome.
5. Read the saved state again, reload the page, or log back into the same profile.
   The original persisted block remains visible. The products overview also
   shows a separate simulated protection status alongside the source snapshot.

The language model has no commit capability. Banking MCP exposes host-only
`prepare_card_block`, `confirm_card_block`, and `read_card_block` tools. The
trusted application resolves opaque product references from the current
customer's products, validates session/ledger authority, and fences operations
against logout. Preparation does not block the card.

## Measured local acceptance

The generated-data RC API test exercises the actual authenticated application,
owned-product repository, trusted host and SQLite banking ledger without a
network or model stub supplying an action result. It verifies Spanish and
Portuguese requests, explicit confirmation, receipt readback, durable status
after re-login, preserved receipt after a new pipeline snapshot, and refusal of
another customer's reference. It also exercises a pending handle left by an
earlier session.

The banking safety suite submits **100 concurrent confirmations** of one
prepared card. All return one identical verified receipt; the database contains
exactly one block. This is a concurrency/idempotency test of the bank action,
separate from the 100-model-call Luna evaluation.

Additional tests verify:

- No block before explicit consent; false consent, foreign ownership, expired
  handles and revoked sessions cannot write.
- Lost post-commit readback is held as uncertain, then recovered through the
  persisted record without a second write.
- Tampering with receipt card facts, snapshot, ID, timestamp, schema or bytes
  cannot produce a verified success. The atomically stored receipt digest and
  original prepared intent preserve provenance.
- Cancellation invalidates the server capability. A stale cancellation cannot
  undo an already committed block.
- The UI does not speak or display success for an invalid receipt, reads durable
  status in a fresh browser, reconciles server-rejected old-session handles, and
  allows an explicitly expired preparation to be renewed.

## Reproduce

```powershell
python -m pytest tests/test_card_block.py tests/test_card_block_api.py tests/test_dispute_action_host.py tests/test_connect_banking_mcp.py -q
cd frontend
npm ci
npm test
npm run build
```

These checks establish local source acceptance. Public deployment and browser
acceptance require a separately recorded runtime revision and receipt; they are
not implied by this report.
