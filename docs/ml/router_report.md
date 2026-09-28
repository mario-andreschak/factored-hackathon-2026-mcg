# Intent router: evaluation

> **PROVISIONAL.** The test set was written by the same author as the training set, so these numbers are optimistic. They will be replaced when the team-authored `ml/data/router_test.csv` lands.

Train 307 phrases (team/AI-authored, `router_train.csv`) · test 60 phrases (`router_test_provisional.csv`, PROVISIONAL (written by the same author as train)) · C = 8 and abstention τ = 0.65, both chosen by 5-fold CV **on train only**.

| System | Accuracy (95% CI) | Macro-F1 | `human` messages automated (unsafe) | Unnecessary handoffs |
|---|---|---:|---:|---:|
| Keyword baseline | 78% (68%–88%) | 0.78 | 2/15 | 0 |
| TF-IDF + logistic regression | 90% (82%–97%) | 0.90 | 1/15 | 2 |
| … + abstention (τ = 0.65) | 70% (58%–82%) | 0.71 | 0/15 | 16 |

With abstention, **48%** of messages are handled automatically at **93%** precision; the rest go to a person.

## Abstention trade-off (test set, for reading only; τ was fixed on train)

| τ | Automated | Precision when automated | `human` automated | Unnecessary handoffs |
|---:|---:|---:|---:|---:|
| 0.3 | 73% | 91% | 1 | 2 |
| 0.4 | 72% | 93% | 1 | 3 |
| 0.5 | 58% | 94% | 0 | 10 |
| 0.55 | 55% | 94% | 0 | 12 |
| 0.6 | 52% | 94% | 0 | 14 |
| 0.65 ← chosen | 48% | 93% | 0 | 16 |
| 0.7 | 48% | 93% | 0 | 16 |
| 0.8 | 35% | 90% | 0 | 24 |

## Per class (model with abstention)

| Class | Precision | Recall | F1 | n |
|---|---:|---:|---:|---:|
| inquiry | 0.80 | 0.53 | 0.64 | 15 |
| dispute | 1.00 | 0.67 | 0.80 | 15 |
| human | 0.48 | 1.00 | 0.65 | 15 |
| other | 1.00 | 0.60 | 0.75 | 15 |

## By language

| Language | n | Baseline | Model | Model + abstention |
|---|---:|---:|---:|---:|
| es | 52 | 75% | 88% | 67% |
| pt | 8 | 100% | 100% | 88% |

## Confusion matrix (rows = true, columns = routed)

| | inquiry | dispute | human | other |
|---|---:|---:|---:|---:|
| **inquiry** | 8 | 0 | 7 | 0 |
| **dispute** | 0 | 10 | 5 | 0 |
| **human** | 0 | 0 | 15 | 0 |
| **other** | 2 | 0 | 4 | 9 |

## Errors (baseline or routed decision wrong)

| Text | True | Baseline | Model | Routed | Confidence |
|---|---|---|---|---|---:|
| ya me depositaron o todavia no? me dijeron q antier | inquiry | inquiry | inquiry | human | 0.469 |
| ese cobro de 8.40 dolares q sale el 4 de junio de q es? | inquiry | inquiry | inquiry | human | 0.451 |
| me aparece reversada una compra eso es bueno o malo | inquiry | inquiry | inquiry | human | 0.474 |
| hasta cuando tengo para pagar la tarjeta sin recargo | inquiry | inquiry | inquiry | human | 0.517 |
| q onda con mi transferencia a banorte sigue en proceso? | inquiry | inquiry | human | human | 0.462 |
| cuanta plata me entro hoy | inquiry | other | inquiry | human | 0.556 |
| me confirmas si ya pague el credito de la moto | inquiry | other | inquiry | inquiry | 0.894 |
| a compra do mercado ja foi aprovada? | inquiry | inquiry | inquiry | human | 0.578 |
| ese cargo d 1500 no lo hice yo | dispute | inquiry | dispute | dispute | 0.919 |
| me cobraron 2 veces la gasolina wey | dispute | other | dispute | dispute | 0.967 |
| el cajero se trabo no saco billetes y igual me desconto | dispute | other | dispute | human | 0.494 |
| cancele spotify hace 2 meses y sigue el debito | dispute | dispute | dispute | human | 0.406 |
| compre unos tenis y nunca me llegaron y ya me cobraron | dispute | inquiry | dispute | dispute | 0.944 |
| xq me cobraron doble el super si pase la tarjeta una vez | dispute | dispute | dispute | human | 0.646 |
| la tienda dijo q me devolvio la plata hace 20 dias y nada | dispute | dispute | dispute | human | 0.547 |
| el cobro del hotel fue mas alto que lo que decia la reserva | dispute | inquiry | dispute | dispute | 0.717 |
| mande plata a mi primo y a el no le llego pero de mi cuenta si salio | dispute | other | dispute | human | 0.642 |
| me sale un debito de disney plus y nunca me suscribi | dispute | other | dispute | dispute | 0.821 |
| me estan pidiendo plata por whatsapp haciendose pasar por mi hijo y ya les mande | human | other | human | human | 0.881 |
| mi abuela recibio una llamada y le sacaron toda la plata | human | other | human | human | 0.584 |
| a q hora cierran el sabado | other | other | other | human | 0.452 |
| ey q tal | other | other | inquiry | human | 0.39 |
| cuanto esta el dolar | other | inquiry | inquiry | inquiry | 0.895 |
| se puede sacar plata sin tarjeta en el cajero? | other | other | other | human | 0.474 |
| me voy de viaje a españa la tarjeta sirve alla? | other | other | human | human | 0.493 |
| q tal el cdt de ustedes cuanto paga | other | inquiry | inquiry | inquiry | 0.891 |

## Leakage check

0 test phrase(s) have a training phrase with character-level cosine ≥ 0.8.

Test sets this small give wide intervals; read the CI, not just the point estimate.
