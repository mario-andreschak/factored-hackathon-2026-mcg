# Intent router: labeling guide

The router reads the customer's **first message** and picks how the assistant proceeds.
It is not a banking decision; it only decides which flow opens.

| Label | Meaning | Assistant does | Examples |
|---|---|---|---|
| `inquiry` | Asks for information about their own account or transactions **without claiming anything is wrong**. | Look up and explain (read-only). | "¿Cuál es mi saldo?", "¿Ya me llegó la transferencia de ayer?", "¿Qué es el cargo de Rappi del martes?" |
| `dispute` | Says a charge or movement **is wrong**: not recognized, charged twice, wrong amount, paid but not received, refund never arrived. | Identify the transaction, confirm, open a dispute-intake case. | "No reconozco un cobro de 45 mil", "Me cobraron dos veces en Oxxo", "Pagué y el comercio dice que no le llegó" |
| `human` | Needs a person now: **security or fraud risk** (stolen or lost card, someone else using the account, phishing), explicit request for an agent, legal threats, or a vulnerable situation. | Hand off with a summary. Do not try to resolve. | "Me robaron la tarjeta", "Alguien entró a mi cuenta", "Quiero hablar con un asesor", "Los voy a demandar" |
| `other` | Anything outside this workflow: product questions, opening accounts, loans, branch hours, greetings, chit-chat. | Say what the assistant can help with. | "¿Qué requisitos piden para un préstamo?", "¿A qué hora abre la sucursal?", "Hola" |

## Tie-breakers

1. **Security beats everything.** "No reconozco este cargo, creo que me clonaron la tarjeta" → `human` (possible fraud), not `dispute`.
2. **Claim beats question.** "¿Por qué me cobraron dos veces?" → `dispute`: the customer asserts a double charge.
3. **Question without a claim** → `inquiry`. "¿Qué es este cargo de Netflix?" asks for an explanation, so it is `inquiry`. If they add "yo no tengo Netflix", it becomes `dispute`.
4. An explicit request for a person → `human`, even if they also describe a dispute.
5. A greeting plus a request → label the request.

## How to write test phrases

- Write like a real customer on WhatsApp: typos, no accents, abbreviations ("q", "xq", "plata", "lana", "guita", "luca"), run-on sentences.
- Mix the variants: Mexico, Colombia, Argentina. Add about 15% in **Portuguese**.
- Include hard cases near the tie-breakers, not only easy ones.
- **Do not look at `router_train.csv`** before writing. The test is only fair if its author has not seen the training set.
- Save as `ml/data/router_test.csv` with columns `text,label,lang,author`. `lang` is `es` or `pt`.
