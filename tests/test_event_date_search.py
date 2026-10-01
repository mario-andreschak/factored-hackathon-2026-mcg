"""Generated fiction only: event-date windows, pinned lineage and owner paging."""
from __future__ import annotations

import json
import shutil
import time
from datetime import date

import duckdb
import pytest

from banking_mcp.config import Config
from banking_mcp.repository import Repository
from banking_mcp.security import BankError, Principal, StateStore
from pipeline.__main__ import main
from pipeline.bronze import fingerprint
from pipeline.common import current_build, load_contracts, sql_path
from pipeline.fixture import _part, _row, _write, cid, write_base


@pytest.fixture(scope="module")
def event_dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("fictional-event-dates")
    source, output = root / "source", root / "output"
    contracts = load_contracts()
    _write(source / "customers.csv", contracts, "customers", [
        _row(contracts, "customers", customer_id=cid(i)) for i in range(5)])
    _write(source / "products.csv", contracts, "products", [
        _row(contracts, "products", product_id=f"PRD{i:06d}", customer_id=cid(i)) for i in range(5)])

    def transaction(identifier, event, owner=3, **overrides):
        values = {"transaction_id": identifier, "customer_id": cid(owner), "product_id": f"PRD{owner:06d}",
                  "transaction_date": event, "process_date": "2026-06-17",
                  "merchant_name": identifier, "amount": "12.00", **overrides}
        return _row(contracts, "transactions", **values)

    # Every row is physically stored in June17. One null event is quarantined by
    # the actual required-date contract and cannot advance the serving anchor.
    rows = [transaction(f"FICTION-{i:02d}", f"2026-04-{i + 1:02d} 12:00:00") for i in range(20)]
    rows += [transaction("AT-START", "2026-03-21 00:00:00"),
             transaction("BEFORE-START", "2026-03-20 23:59:59.999999"),
             transaction("AT-END-EARLY", "2026-06-18 00:00:00"),
             transaction("AT-END-LATE", "2026-06-18 23:59:59.999999"),
             transaction("AT-END-TIE", "2026-06-18 23:59:59.999999"),
             transaction("FOREIGN", "2026-06-18 23:59:59.999999", owner=4),
             transaction("BAD-OWNER-FUTURE", "2027-12-31 00:00:00", product_id="PRD000004"),
             transaction("MISSING-EVENT", "")]
    _write(_part(source, "transactions", "2026-06-17"), contracts, "transactions", rows)
    assert main(["run", "--source", str(source), "--out", str(output),
                 "--reports", str(root / "reports"), "--tables", "customers", "products", "transactions"]) == 0
    return output


@pytest.fixture
def repository(event_dataset, tmp_path):
    config = Config(mode="operator-test", data_dir=event_dataset, state_db=tmp_path / "state.sqlite",
                    service_token="fiction-only-token-" + "x" * 32, approved_customers={cid(3), cid(4)})
    repo = Repository(config, StateStore(config.state_db, require_ledger_generation=False))
    yield repo
    repo.close()


def owner(customer=3, **overrides):
    values = {"subject": "fiction", "customer": cid(customer), "session": "fiction-session",
              "conversation": "fiction-conversation", "expires": int(time.time()) + 60}
    return Principal(**{**values, **overrides})


def search(repo, start=None, end=None, limit=20, cursor=None, principal=None):
    return repo.list_transactions(principal or owner(), start, end, limit, cursor)


def test_default_window_is_exactly_90_event_calendar_days_and_discloses_anchor(repository):
    result = search(repository)
    assert result["date_window"] == {
        "start": "2026-03-21", "end": "2026-06-18", "basis": "transaction_date",
        "calendar": "source_timestamp_calendar_date", "anchor": "2026-06-18", "max_calendar_days": 90}
    assert result["snapshot_event_dates"] == {
        "first": "2026-03-20", "last": "2026-06-18", "basis": "transaction_date",
        "calendar": "source_timestamp_calendar_date"}
    assert (date.fromisoformat(result["date_window"]["end"])
            - date.fromisoformat(result["date_window"]["start"])).days + 1 == 90
    assert result["read_only"] is True and result["freshness"] == "derived_snapshot"
    assert result["snapshot"] == current_build(repository.config.data_dir).name


def test_june18_events_in_june17_partition_and_both_day_edges_are_included(repository):
    result = search(repository, "2026-06-18", "2026-06-18")
    assert {row["merchant"] for row in result["transactions"]} == {
        "AT-END-EARLY", "AT-END-LATE", "AT-END-TIE"}
    assert all(row["process_date"] == "2026-06-17" for row in result["transactions"])
    assert all(row["transaction_date"].startswith("2026-06-18") for row in result["transactions"])
    assert result["next_cursor"] is None
    start = search(repository, "2026-03-21", "2026-03-21")
    assert [row["merchant"] for row in start["transactions"]] == ["AT-START"]


def test_explicit_older_window_is_honored_without_clipping_to_default(repository):
    default_start = search(repository)["date_window"]["start"]
    assert default_start == "2026-03-21"
    result = search(repository, "2026-03-20", "2026-03-21")
    assert result["date_window"]["start"] == "2026-03-20"
    assert result["date_window"]["end"] == "2026-03-21"
    assert {row["merchant"] for row in result["transactions"]} == {"BEFORE-START", "AT-START"}
    first_day = search(repository, "2026-03-20", "2026-03-20")
    assert [row["merchant"] for row in first_day["transactions"]] == ["BEFORE-START"]
    assert first_day["date_window"]["end"] != first_day["date_window"]["anchor"]


def test_short_snapshot_default_starts_at_first_actual_event_date(tmp_path):
    source, output = tmp_path / "fiction-only-source", tmp_path / "fiction-only-output"
    write_base(source)
    assert main(["run", "--source", str(source), "--out", str(output),
                 "--reports", str(tmp_path / "reports"),
                 "--tables", "customers", "products", "transactions"]) == 0
    config = Config(mode="operator-test", data_dir=output, state_db=tmp_path / "state.sqlite",
                    service_token="fiction-only-token-" + "x" * 32, approved_customers={cid(3), cid(4)})
    repo = Repository(config, StateStore(config.state_db, require_ledger_generation=False))
    try:
        result = search(repo)
        assert result["date_window"]["start"] == result["snapshot_event_dates"]["first"] == "2026-06-01"
        assert result["date_window"]["end"] == result["date_window"]["anchor"] == "2026-06-02"
        assert result["date_window"]["max_calendar_days"] == 90
        assert (date.fromisoformat(result["date_window"]["end"])
                - date.fromisoformat(result["date_window"]["start"])).days + 1 == 2
        with pytest.raises(BankError, match="invalid_date_window"):
            search(repo, "2026-05-31", "2026-06-02")
    finally:
        repo.close()


@pytest.mark.parametrize("start,end", [
    ("2026-06-18", None), (None, "2026-06-18"),
])
def test_single_explicit_date_requires_clarification_without_filling_other_date(repository, start, end):
    with pytest.raises(BankError, match="invalid_date_window"):
        search(repository, start, end)


def test_paging_is_stable_complete_and_bound_to_owner_window_and_conversation(repository):
    first = search(repository, limit=1)
    for principal in (owner(4), owner(conversation="different-conversation")):
        with pytest.raises(BankError, match="reference_unavailable"):
            search(repository, limit=1, cursor=first["next_cursor"], principal=principal)
    with pytest.raises(BankError, match="reference_unavailable"):
        search(repository, "2026-06-18", "2026-06-18", 1, first["next_cursor"])
    items, page = [], first
    while True:
        items.extend(page["transactions"])
        if not page["next_cursor"]:
            break
        page = search(repository, limit=1, cursor=page["next_cursor"])
    merchants = [row["merchant"] for row in items]
    assert len(items) == len(set(row["transaction_reference"] for row in items)) == 24
    assert "AT-START" in merchants
    assert {"BEFORE-START", "FOREIGN", "BAD-OWNER-FUTURE", "MISSING-EVENT"}.isdisjoint(merchants)
    selected = repository.get_transaction(owner(), first["transactions"][0]["selection_handle"], False)
    assert selected["transaction"]["transaction_reference"] == first["transactions"][0]["transaction_reference"]
    with pytest.raises(BankError, match="reference_unavailable"):
        repository.get_transaction(owner(4), first["transactions"][0]["selection_handle"], False)


@pytest.mark.parametrize("start,end", [
    ("2026-03-20", "2026-06-18"), ("2026-03-19", "2026-03-21"),
    ("2026-06-18", "2026-06-19"), ("2026-06-18", "2026-06-17"),
    ("2026-02-30", "2026-06-18"), ("20260618", None),
    ("2026-06-18T00:00:00Z", None), (None, "2026-06-18+00:00"),
])
def test_invalid_and_91_day_or_outside_snapshot_searches_fail_closed(repository, start, end):
    with pytest.raises(BankError, match="invalid_date_window"):
        search(repository, start, end)


def test_missing_customer_never_reads_any_owned_rows(repository):
    with pytest.raises(BankError, match="authorization_denied"):
        search(repository, principal=owner(999))


def test_known_empty_customer_returns_no_rows_with_disclosed_window(repository):
    result = search(repository, principal=owner(0))
    assert result["transactions"] == [] and result["next_cursor"] is None
    assert result["snapshot_event_dates"]["last"] == result["date_window"]["anchor"] == "2026-06-18"


def test_pipeline_records_event_dates_from_gold_not_partition_or_build_date(event_dataset):
    build = current_build(event_dataset)
    manifest = json.loads((build / "snapshot.json").read_text(encoding="utf-8"))
    quality = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    event = manifest["transaction_event_dates"]
    assert event["first"] == "2026-03-20" and event["last"] == "2026-06-18"
    assert event["ownership_valid_rows"] == 26 and event["missing_event_dates"] == 0
    assert event["source_fingerprint"] == manifest["source_fingerprint"]
    assert {k: v for k, v in event.items() if k != "source_fingerprint"} == (
        quality["gold"]["transactions_by_customer"]["transaction_event_dates"])
    assert quality["tables"]["transactions"]["silver"]["quarantined_rows"] == 1


def copied_repository(event_dataset, tmp_path):
    output = tmp_path / "copied-fiction-only"
    shutil.copytree(event_dataset, output)
    config = Config(mode="operator-test", data_dir=output, state_db=tmp_path / "state.sqlite",
                    service_token="fiction-only-token-" + "x" * 32, approved_customers={cid(3), cid(4)})
    return Repository(config, StateStore(config.state_db, require_ledger_generation=False)), current_build(output)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def test_existing_snapshot_without_event_aggregate_derives_exact_gold_range(event_dataset, tmp_path):
    repo, build = copied_repository(event_dataset, tmp_path)
    try:
        path = build / "snapshot.json"
        manifest = read_json(path)
        manifest.pop("transaction_event_dates")
        manifest["created_at"] = "2099-01-01T00:00:00+00:00"
        write_json(path, manifest)
        assert search(repo)["date_window"]["anchor"] == "2026-06-18"
    finally:
        repo.close()


@pytest.mark.parametrize("change", [
    "manifest-event", "manifest-fingerprint", "inventory-fingerprint", "object-etag",
    "object-duplicate", "missing-master", "quality-build", "quality-validation", "quality-fingerprint",
    "null-inventory", "null-quality", "malformed-event-count",
])
def test_incoherent_snapshot_metadata_or_source_lineage_is_unavailable(event_dataset, tmp_path, change):
    repo, build = copied_repository(event_dataset, tmp_path)
    try:
        manifest_path, inventory_path, quality_path = (
            build / "snapshot.json", build / "source_objects.json", build / "manifest.json")
        manifest, inventory, quality = map(read_json, (manifest_path, inventory_path, quality_path))
        if change == "null-inventory":
            inventory = None
        elif change == "null-quality":
            quality = None
        elif change == "malformed-event-count":
            manifest["transaction_event_dates"]["missing_event_dates"] = False
        elif change == "manifest-event":
            manifest["transaction_event_dates"]["last"] = "2026-06-17"
        elif change == "manifest-fingerprint":
            manifest["source_fingerprint"] = "foreign-inventory"
        elif change == "inventory-fingerprint":
            inventory["fingerprint"] = "foreign-inventory"
        elif change == "object-etag":
            inventory["tables"]["transactions"]["objects"][0]["etag"] = "changed-object"
        elif change == "object-duplicate":
            inventory["tables"]["transactions"]["objects"].append(
                inventory["tables"]["transactions"]["objects"][0])
        elif change == "missing-master":
            inventory["tables"]["customers"]["objects"] = []
        elif change == "quality-build":
            quality["run_id"] = "foreign-build"
        elif change == "quality-validation":
            quality["source_validation"] = "foreign-validation"
        else:
            quality["source_fingerprint"] = "foreign-inventory"
        for path, content in zip((manifest_path, inventory_path, quality_path), (manifest, inventory, quality)):
            write_json(path, content)
        with pytest.raises(BankError, match="dataset_unavailable"):
            search(repo)
    finally:
        repo.close()


@pytest.mark.parametrize("change", ["null-event", "missing-source", "foreign-owner-flag", "zoned-timestamp"])
def test_invalid_serving_rows_cannot_supply_an_anchor(event_dataset, tmp_path, change):
    repo, build = copied_repository(event_dataset, tmp_path)
    try:
        # Pick the actual bucket containing the selected fiction owner.
        from pipeline.common import bucket_for
        file = next((build / "gold" / "transactions_by_customer" / f"bucket={bucket_for(cid(3))}").glob("*.parquet"))
        with duckdb.connect() as con:
            con.execute(f"CREATE TABLE changed AS SELECT * FROM read_parquet('{sql_path(file)}')")
            if change == "null-event":
                con.execute("UPDATE changed SET transaction_date=NULL WHERE transaction_id='AT-END-EARLY'")
            elif change == "missing-source":
                con.execute("UPDATE changed SET _source_file='transactions/year=2026/month=06/day=18/absent.csv'")
            elif change == "foreign-owner-flag":
                con.execute("UPDATE changed SET ownership_valid=true WHERE transaction_id='BAD-OWNER-FUTURE'")
            else:
                con.execute("ALTER TABLE changed ALTER transaction_date TYPE TIMESTAMPTZ")
            changed = tmp_path / "changed-fiction.parquet"
            con.execute(f"COPY changed TO '{sql_path(changed)}' (FORMAT parquet)")
        shutil.copyfile(changed, file)
        manifest = read_json(build / "snapshot.json")
        manifest["gold_files"][file.relative_to(build / "gold").as_posix()] = file.stat().st_size
        write_json(build / "snapshot.json", manifest)
        with pytest.raises(BankError, match="dataset_unavailable"):
            search(repo)
    finally:
        repo.close()


def test_missing_actual_source_key_is_rejected_even_with_coherent_fingerprints(event_dataset, tmp_path):
    repo, build = copied_repository(event_dataset, tmp_path)
    try:
        inventory = read_json(build / "source_objects.json")
        inventory["tables"]["transactions"]["objects"] = []
        inventory["tables"]["transactions"]["fingerprint"] = fingerprint([])
        inventory["fingerprint"] = fingerprint([o for table in inventory["tables"].values() for o in table["objects"]])
        write_json(build / "source_objects.json", inventory)
        for name in ("snapshot.json", "manifest.json"):
            value = read_json(build / name)
            value["source_fingerprint"] = inventory["fingerprint"]
            if "transaction_event_dates" in value:
                value["transaction_event_dates"]["source_fingerprint"] = inventory["fingerprint"]
            write_json(build / name, value)
        with pytest.raises(BankError, match="dataset_unavailable"):
            search(repo)
    finally:
        repo.close()
