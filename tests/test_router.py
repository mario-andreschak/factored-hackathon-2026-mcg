"""Router tests: data hygiene, baseline rules, abstention, and the train/evaluate entry point."""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from ml import router


def rows(path):
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_datasets_are_clean_and_disjoint():
    train = rows(router.TRAIN)
    tests = [rows(p) for p in (router.TEST, router.TEST_PROVISIONAL) if p.exists()]
    assert {r["label"] for r in train} == set(router.LABELS)
    norm_train = {router.normalize(r["text"]) for r in train}
    assert len(norm_train) == len(train)                        # no duplicates inside train
    for test in tests:
        assert {r["label"] for r in test} == set(router.LABELS)
        assert {r["lang"] for r in test} <= {"es", "pt"}
        overlap = norm_train & {router.normalize(r["text"]) for r in test}
        assert not overlap, overlap                             # no exact leakage


def test_normalize_handles_whatsapp_spelling():
    assert router.normalize("¿¡Holaaa!! q ONDA, xq me cobraron?") == "hola que onda porque me cobraron"
    assert router.normalize("Não reconheço") == "nao reconheco"


def test_baseline_checks_security_before_disputes():
    got = router.baseline_predict(["no reconozco este cargo, creo que me clonaron la tarjeta",
                                   "me cobraron dos veces", "cual es mi saldo", "hola"])
    assert got == ["human", "dispute", "inquiry", "other"]


def test_low_confidence_routes_to_human():
    probs = np.array([[0.9, 0.05, 0.03, 0.02], [0.4, 0.35, 0.15, 0.10]])
    assert router.route(probs, ["dispute", "human", "inquiry", "other"], tau=0.6) == ["dispute", "human"]


def test_train_and_evaluate_writes_reports(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert router.train_and_evaluate() == 0
    r = json.loads((tmp_path / "docs" / "ml" / "router_metrics.json").read_text(encoding="utf-8"))
    assert r["near_duplicates_train_test"] == []
    assert 0.25 <= r["tau"] <= 0.95
    m = r["model_no_abstention"]
    assert m["n"] == r["test_n"] and set(m["per_class"]) == set(router.LABELS)
    assert r["model_with_abstention"]["human_missed"] <= m["human_missed"]
    router._LOADED = None
    monkeypatch.setattr(router, "MODEL_PATH", tmp_path / "data" / "ml" / "router.joblib")
    out = router.predict("me robaron la tarjeta y estan comprando")
    assert out["route"] == "human" and set(out) == {"route", "label", "confidence", "abstained"}
