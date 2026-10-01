"""Per-profile portal display language over an unchanged published snapshot.

The language a profile opens in is presentation only. Country, currency and
every record keep the values the snapshot supplies, so a Portuguese profile
never implies a Brazilian customer.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from frontend.server.app import create_app
from frontend.server.repository import PROFILE_DEFAULTS
from frontend.tests.test_api import login, settings  # noqa: F401  shared fixture


def test_defaults_describe_every_profile_in_both_languages():
    for profile_id, defaults in PROFILE_DEFAULTS.items():
        descriptions = defaults["description"]
        assert defaults["language"] == "es", profile_id
        assert set(descriptions) == {"es", "pt"}, profile_id
        assert descriptions["es"] and descriptions["pt"], profile_id
        # Real copy per language, not the same string repeated.
        assert descriptions["es"] != descriptions["pt"], profile_id


def test_profiles_endpoint_publishes_both_descriptions_and_language(settings):
    with TestClient(create_app(settings)) as client:
        published = client.get("/api/auth/profiles").json()["profiles"]
    assert published
    for profile in published:
        assert profile["language"] == "es"
        assert set(profile["descriptions"]) == {"es", "pt"}
        assert profile["descriptions"]["pt"]
        # The flat key stays the Spanish copy for existing clients.
        assert profile["description"] == profile["descriptions"]["es"]


def test_portuguese_profile_keeps_snapshot_country_and_currency(settings):
    configured = replace(settings, profiles={**settings.profiles,
        "colombia": {**settings.profiles["colombia"], "language": "pt"}})
    with TestClient(create_app(configured)) as client:
        published = {p["id"]: p for p in client.get("/api/auth/profiles").json()["profiles"]}
        assert login(client).status_code == 200
        overview = client.get("/api/overview").json()
    assert published["colombia"]["language"] == "pt"
    assert published["mexico"]["language"] == "es"
    # A display language must not restate the customer's country or money.
    assert published["colombia"]["country"] == "Colombia"
    assert published["colombia"]["primary_currency"] == "COP"
    assert overview["profile"]["language"] == "pt"
    assert overview["profile"]["country"] == "Colombia"
    assert {b["currency"] for b in overview["summary"]["balances_by_currency"]} == {"COP", "USD"}


def test_operator_description_override_is_shown_as_written(settings):
    configured = replace(settings, profiles={**settings.profiles,
        "colombia": {**settings.profiles["colombia"], "description": "Texto del operador"}})
    with TestClient(create_app(configured)) as client:
        published = {p["id"]: p for p in client.get("/api/auth/profiles").json()["profiles"]}
    assert published["colombia"]["descriptions"] == {"es": "Texto del operador",
                                                     "pt": "Texto del operador"}
    assert published["mexico"]["descriptions"]["pt"] == PROFILE_DEFAULTS["mexico"]["description"]["pt"]


@pytest.mark.parametrize("language", ["en", "pt-BR", "", None, "ES"])
def test_unapproved_profile_language_fails_closed(settings, language):
    with pytest.raises(ValueError):
        replace(settings, profiles={**settings.profiles,
            "colombia": {**settings.profiles["colombia"], "language": language}})
