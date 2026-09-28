"""Intent router: inquiry | dispute | human | other, from the customer's first message.

    python -m ml.router train      # fit, evaluate on the held-out set, write reports
    python -m ml.router predict "me cobraron dos veces en oxxo"

Why this exists: both label sources in the organizer dataset are unlearnable (see
ml/inspect_texts.py and ml/inspect_fraud.py), so the learned component is trained on
team-authored utterances (ml/data/router_train.csv) and evaluated on a SEPARATE held-out
set written by someone who did not see the training data (ml/data/router_test.csv).
Until that file exists, ml/data/router_test_provisional.csv is used and every report is
labelled PROVISIONAL.

Design
- Baseline: ordered keyword rules (security first), no learning.
- Model: TF-IDF (char 2-5 within word boundaries + word 1-2 grams) -> logistic regression.
  Char n-grams tolerate typos, missing accents and Spanish/Portuguese spelling variants.
- Abstention: if the model's top probability is below tau, the message goes to a human.
  tau and C are chosen with cross-validation on TRAIN ONLY; the test set is touched once.
- Safety metric: a `human` message that gets automated is the costly error, so it is
  reported separately from accuracy.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np

LABELS = ["inquiry", "dispute", "human", "other"]
ROOT = Path(__file__).resolve().parent
TRAIN = ROOT / "data" / "router_train.csv"
TEST = ROOT / "data" / "router_test.csv"
TEST_PROVISIONAL = ROOT / "data" / "router_test_provisional.csv"
MODEL_PATH = Path("data/ml/router.joblib")          # git-ignored
REPORT_DIR = Path("docs/ml")                          # committed, aggregates + test texts only
TARGET_AUTOMATED_PRECISION = 0.95
SEED = 7


# --- text normalisation -------------------------------------------------------------------
_ABBREV = {r"\bq\b": "que", r"\bxq\b": "porque", r"\bpq\b": "porque", r"\bxfa\b": "por favor",
           r"\bporfa\b": "por favor", r"\bpa\b": "para", r"\bd\b": "de", r"\bx\b": "por",
           r"\bk\b": "que", r"\btb\b": "tambien", r"\bvc\b": "voce", r"\bnao\b": "nao"}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"(.)\1{2,}", r"\1", t)            # holaaa -> hola
    t = re.sub(r"[^\w\s]", " ", t)
    for pat, rep in _ABBREV.items():
        t = re.sub(pat, rep, t)
    return re.sub(r"\s+", " ", t).strip()


# --- baseline -----------------------------------------------------------------------------
_RULES = [
    ("human", r"robar|robaron|roubar|roubaram|perdi|perdio|clonar|clonaron|hacke|fraude|estafa|golpe|"
              r"phishing|link|enlace|codigo|clave|contrasena|senha|asesor|persona|humano|atendente|"
              r"supervisor|gerente|demand|denunc|abogado|processar|queja formal|reclamacao|extors|"
              r"amenaz|suplant|identidad|afanaron|chorearon|asaltaron"),
    ("dispute", r"no reconozco|nao reconhe|no hice|nao fiz|no fui yo|nao fui eu|no autorice|dos veces|"
                r"duas vezes|doble|dobro|duplicad|triple|de mas|no me llego|nunca llego|nao chegou|"
                r"reclamar|disputar|contestar|objetar|reembols|estorno|devolv|siguen cobrando|"
                r"continuam cobrando|sigue el cobro|sigue el debito|no corresponde|jamas pedi|nunca contrate"),
    ("inquiry", r"saldo|cuanto|quanto|movimiento|movimento|disponible|disponivel|transferencia|pix|"
                r"deposit|acredit|fecha de corte|vence|fatura|resumen|cargo|cobro|cobranca|compra|"
                r"gaste|gasto|pendiente|pendente|revertid|pago|pagamento|ya me|ja caiu"),
]


def baseline_predict(texts: list[str]) -> list[str]:
    out = []
    for t in texts:
        n = normalize(t)
        out.append(next((label for label, pat in _RULES if re.search(pat, n)), "other"))
    return out


# --- model --------------------------------------------------------------------------------
def build_pipeline(C: float = 4.0):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline
    return Pipeline([
        ("features", FeatureUnion([
            ("char", TfidfVectorizer(preprocessor=normalize, analyzer="char_wb", ngram_range=(2, 5),
                                     min_df=1, sublinear_tf=True)),
            ("word", TfidfVectorizer(preprocessor=normalize, analyzer="word", ngram_range=(1, 2),
                                     min_df=1, sublinear_tf=True)),
        ])),
        ("clf", LogisticRegression(C=C, max_iter=5000, class_weight="balanced")),
    ])


def route(probs: np.ndarray, classes: list[str], tau: float) -> list[str]:
    """Final decision: predicted label, or 'human' when confidence is below tau."""
    idx = probs.argmax(1)
    return [classes[i] if probs[r, i] >= tau else "human" for r, i in enumerate(idx)]


def choose_tau(probs: np.ndarray, y: list[str], classes: list[str]) -> float:
    """Lowest tau whose automated decisions (non-human) reach the target precision."""
    pred = [classes[i] for i in probs.argmax(1)]
    conf = probs.max(1)
    for tau in np.round(np.arange(0.25, 0.96, 0.01), 2):
        auto = [(p, t) for p, t, c in zip(pred, y, conf) if c >= tau and p != "human"]
        if auto and sum(p == t for p, t in auto) / len(auto) >= TARGET_AUTOMATED_PRECISION:
            return float(tau)
    return 0.95


# --- evaluation ---------------------------------------------------------------------------
def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    bad = [r for r in rows if r["label"] not in LABELS]
    if bad:
        raise ValueError(f"{path}: unknown labels {sorted({r['label'] for r in bad})}")
    return rows


def metrics(y: list[str], pred: list[str], langs: list[str], rng: np.random.Generator) -> dict:
    from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support
    y_a, p_a = np.array(y), np.array(pred)
    acc = float((y_a == p_a).mean())
    boots = [float((y_a[i] == p_a[i]).mean()) for i in (rng.integers(0, len(y), len(y)) for _ in range(2000))]
    p, r, f, s = precision_recall_fscore_support(y, pred, labels=LABELS, zero_division=0)
    return {
        "n": len(y),
        "accuracy": round(acc, 3),
        "accuracy_ci95": [round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)],
        "macro_f1": round(float(f1_score(y, pred, labels=LABELS, average="macro", zero_division=0)), 3),
        "per_class": {l: {"precision": round(float(p[i]), 3), "recall": round(float(r[i]), 3),
                          "f1": round(float(f[i]), 3), "support": int(s[i])} for i, l in enumerate(LABELS)},
        "confusion": {"labels": LABELS, "matrix": confusion_matrix(y, pred, labels=LABELS).tolist()},
        "by_lang": {lg: {"n": int((np.array(langs) == lg).sum()),
                         "accuracy": round(float((y_a[np.array(langs) == lg] == p_a[np.array(langs) == lg]).mean()), 3)}
                    for lg in sorted(set(langs))},
        # The costly error: a message that needed a person was handled automatically.
        "human_missed": int(sum(t == "human" and q != "human" for t, q in zip(y, pred))),
        "human_total": int(sum(t == "human" for t in y)),
        # Handing an automatable request to a person costs time, not safety.
        "unnecessary_handoffs": int(sum(t != "human" and q == "human" for t, q in zip(y, pred))),
    }


def near_duplicates(train: list[str], test: list[str], threshold: float = 0.8) -> list[tuple[str, str, float]]:
    """Test phrases too similar to a training phrase (they would inflate the score)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    vec = TfidfVectorizer(preprocessor=normalize, analyzer="char_wb", ngram_range=(3, 5)).fit(train + test)
    sim = cosine_similarity(vec.transform(test), vec.transform(train))
    out = []
    for i, row in enumerate(sim):
        j = int(row.argmax())
        if row[j] >= threshold:
            out.append((test[i], train[j], round(float(row[j]), 3)))
    return out


def train_and_evaluate() -> int:
    import joblib
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    rng = np.random.default_rng(SEED)
    train = read_csv(TRAIN)
    provisional = not TEST.exists()
    test = read_csv(TEST_PROVISIONAL if provisional else TEST)
    Xtr, ytr = [r["text"] for r in train], [r["label"] for r in train]
    Xte, yte, lte = [r["text"] for r in test], [r["label"] for r in test], [r["lang"] for r in test]

    # Model selection on TRAIN only (5-fold CV): regularisation C, then the abstention tau.
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
    from sklearn.metrics import f1_score
    grid = {}
    for C in (0.5, 1, 2, 4, 8, 16):
        oof = cross_val_predict(build_pipeline(C), Xtr, ytr, cv=cv)
        grid[C] = round(float(f1_score(ytr, oof, average="macro")), 3)
    C = max(grid, key=lambda c: (grid[c], -c))
    oof_probs = cross_val_predict(build_pipeline(C), Xtr, ytr, cv=cv, method="predict_proba")
    classes = sorted(set(ytr))
    tau = choose_tau(oof_probs, ytr, classes)

    model = build_pipeline(C).fit(Xtr, ytr)
    classes = list(model.classes_)
    probs = model.predict_proba(Xte)
    raw = [classes[i] for i in probs.argmax(1)]
    routed = route(probs, classes, tau)
    base = baseline_predict(Xte)

    results = {
        "test_set": "PROVISIONAL (written by the same author as train)" if provisional
                    else "held-out, team-authored",
        "test_file": (TEST_PROVISIONAL if provisional else TEST).name,
        "train_n": len(train), "test_n": len(test),
        "selected_C": C, "cv_macro_f1_by_C": grid, "tau": tau,
        "target_automated_precision": TARGET_AUTOMATED_PRECISION,
        "near_duplicates_train_test": [
            {"test": a, "train": b, "cosine": s} for a, b, s in near_duplicates(Xtr, Xte)],
        "baseline_keywords": metrics(yte, base, lte, rng),
        "model_no_abstention": metrics(yte, raw, lte, rng),
        "model_with_abstention": metrics(yte, routed, lte, rng),
    }
    auto = [(p, t) for p, t in zip(routed, yte) if p != "human"]
    results["model_with_abstention"]["automated_share"] = round(len(auto) / len(yte), 3)
    results["model_with_abstention"]["automated_precision"] = (
        round(sum(p == t for p, t in auto) / len(auto), 3) if auto else None)
    # Operating curve on the test set, for reading the trade-off only (tau is NOT picked here).
    results["abstention_curve"] = []
    for t in (0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8):
        rt = route(probs, classes, t)
        a = [(p, q) for p, q in zip(rt, yte) if p != "human"]
        results["abstention_curve"].append({
            "tau": t, "automated_share": round(len(a) / len(yte), 3),
            "automated_precision": round(sum(p == q for p, q in a) / len(a), 3) if a else None,
            "human_missed": int(sum(q == "human" and p != "human" for p, q in zip(rt, yte))),
            "unnecessary_handoffs": int(sum(q != "human" and p == "human" for p, q in zip(rt, yte)))})
    results["errors"] = [
        {"text": x, "label": t, "baseline": b, "model": m, "routed": r, "confidence": round(float(pr.max()), 3)}
        for x, t, b, m, r, pr in zip(Xte, yte, base, raw, routed, probs) if r != t or b != t]

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "tau": tau, "labels": LABELS}, MODEL_PATH)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "router_metrics.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
    (REPORT_DIR / "router_report.md").write_text(render(results), encoding="utf-8")
    print(render_console(results))
    print(f"\nwrote {REPORT_DIR / 'router_report.md'} and {MODEL_PATH}")
    return 0


# --- reporting ----------------------------------------------------------------------------
def _row(name, m):
    ci = m["accuracy_ci95"]
    return (f"| {name} | {m['accuracy']:.0%} ({ci[0]:.0%}–{ci[1]:.0%}) | {m['macro_f1']:.2f} | "
            f"{m['human_missed']}/{m['human_total']} | {m['unnecessary_handoffs']} |")


def render(r: dict) -> str:
    b, raw, ab = r["baseline_keywords"], r["model_no_abstention"], r["model_with_abstention"]
    L = ["# Intent router: evaluation", ""]
    if r["test_set"].startswith("PROVISIONAL"):
        L += ["> **PROVISIONAL.** The test set was written by the same author as the training set, "
              "so these numbers are optimistic. They will be replaced when the team-authored "
              "`ml/data/router_test.csv` lands.", ""]
    L += [f"Train {r['train_n']} phrases (team/AI-authored, `router_train.csv`) · test {r['test_n']} phrases "
          f"(`{r['test_file']}`, {r['test_set']}) · C = {r['selected_C']} and abstention τ = {r['tau']}, "
          f"both chosen by 5-fold CV **on train only**.", "",
          "| System | Accuracy (95% CI) | Macro-F1 | `human` messages automated (unsafe) | Unnecessary handoffs |",
          "|---|---|---:|---:|---:|",
          _row("Keyword baseline", b), _row("TF-IDF + logistic regression", raw),
          _row(f"… + abstention (τ = {r['tau']})", ab), "",
          f"With abstention, **{ab['automated_share']:.0%}** of messages are handled automatically at "
          f"**{ab['automated_precision']:.0%}** precision; the rest go to a person.", "",
          "## Abstention trade-off (test set, for reading only; τ was fixed on train)", "",
          "| τ | Automated | Precision when automated | `human` automated | Unnecessary handoffs |",
          "|---:|---:|---:|---:|---:|"]
    for c in r["abstention_curve"]:
        mark = " ← chosen" if abs(c["tau"] - r["tau"]) < 1e-9 else ""
        prec = "—" if c["automated_precision"] is None else f"{c['automated_precision']:.0%}"
        L.append(f"| {c['tau']}{mark} | {c['automated_share']:.0%} | {prec} | {c['human_missed']} | "
                 f"{c['unnecessary_handoffs']} |")
    L += ["", "## Per class (model with abstention)", "", "| Class | Precision | Recall | F1 | n |", "|---|---:|---:|---:|---:|"]
    for lab, m in ab["per_class"].items():
        L.append(f"| {lab} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} | {m['support']} |")
    L += ["", "## By language", "", "| Language | n | Baseline | Model | Model + abstention |", "|---|---:|---:|---:|---:|"]
    for lg in ab["by_lang"]:
        L.append(f"| {lg} | {ab['by_lang'][lg]['n']} | {b['by_lang'][lg]['accuracy']:.0%} | "
                 f"{raw['by_lang'][lg]['accuracy']:.0%} | {ab['by_lang'][lg]['accuracy']:.0%} |")
    L += ["", "## Confusion matrix (rows = true, columns = routed)", "",
          "| | " + " | ".join(LABELS) + " |", "|---|" + "---:|" * len(LABELS)]
    for lab, row in zip(LABELS, ab["confusion"]["matrix"]):
        L.append(f"| **{lab}** | " + " | ".join(str(v) for v in row) + " |")
    L += ["", "## Errors (baseline or routed decision wrong)", "",
          "| Text | True | Baseline | Model | Routed | Confidence |", "|---|---|---|---|---|---:|"]
    for e in r["errors"]:
        L.append(f"| {e['text']} | {e['label']} | {e['baseline']} | {e['model']} | {e['routed']} | {e['confidence']} |")
    nd = r["near_duplicates_train_test"]
    L += ["", f"## Leakage check", "",
          f"{len(nd)} test phrase(s) have a training phrase with character-level cosine ≥ 0.8"
          + (":" if nd else ".")]
    L += [f"- `{d['test']}` ≈ `{d['train']}` ({d['cosine']})" for d in nd]
    L += ["", "Test sets this small give wide intervals; read the CI, not just the point estimate.", ""]
    return "\n".join(L)


def render_console(r: dict) -> str:
    out = [f"test set: {r['test_set']} ({r['test_n']} phrases) | C={r['selected_C']} tau={r['tau']}",
           f"{'system':<34} {'acc':>5} {'95% CI':>13} {'macroF1':>8} {'human missed':>13} {'extra handoffs':>15}"]
    for name, key in (("keyword baseline", "baseline_keywords"), ("tfidf + logreg", "model_no_abstention"),
                      ("tfidf + logreg + abstention", "model_with_abstention")):
        m = r[key]
        out.append(f"{name:<34} {m['accuracy']:>5.0%} {m['accuracy_ci95'][0]:>6.0%}-{m['accuracy_ci95'][1]:<5.0%} "
                   f"{m['macro_f1']:>8.2f} {m['human_missed']:>7}/{m['human_total']:<5} {m['unnecessary_handoffs']:>15}")
    ab = r["model_with_abstention"]
    out.append(f"automated {ab['automated_share']:.0%} of messages at {ab['automated_precision']:.0%} precision")
    out.append(f"near-duplicates train/test: {len(r['near_duplicates_train_test'])}")
    return "\n".join(out)


# --- serving ------------------------------------------------------------------------------
_LOADED = None


def predict(text: str) -> dict:
    """{'route': label, 'label': model_top, 'confidence': p, 'abstained': bool}. Used by the MCP."""
    global _LOADED
    if _LOADED is None:
        import joblib
        _LOADED = joblib.load(MODEL_PATH)
    model, tau = _LOADED["model"], _LOADED["tau"]
    probs = model.predict_proba([text])[0]
    i = int(probs.argmax())
    label = model.classes_[i]
    return {"route": label if probs[i] >= tau else "human", "label": label,
            "confidence": round(float(probs[i]), 3), "abstained": bool(probs[i] < tau)}


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not argv or argv[0] == "train":
        return train_and_evaluate()
    if argv[0] == "predict" and len(argv) > 1:
        print(json.dumps(predict(" ".join(argv[1:])), ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
