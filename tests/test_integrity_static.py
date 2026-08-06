from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).parents[1]


def test_no_future_daily_high_prefilter_in_signal_stage():
    source = (ROOT / "app" / "processors.py").read_text()
    decision = source[source.index("def process_decision_snapshot"):source.index("def process_signal_verify")]
    assert "ts + timedelta(minutes=1) <= decision_ts" in decision
    assert "proxy_high" in decision
    assert "daily_bars" not in decision.split("exact_required =", 1)[1].split("values.append", 1)[0]
    assert 'end = parse_timestamp(target["session_close"])' not in decision


def test_confirmation_is_hash_and_gate_locked():
    source = (ROOT / "app" / "orchestrator.py").read_text()
    assert 'if not run["primary_gate_passed"]' in source
    assert 'if run["protocol_hash"] != protocol_hash()' in source
    assert "confirmation_unlocked_at" in source


def test_queue_uses_skip_locked_and_stale_recovery():
    source = (ROOT / "app" / "queue.py").read_text().lower()
    assert "for update skip locked" in source
    assert "reclaimed stale running partition" in source
    assert "next_attempt_at" in source


def test_schema_enforces_idempotent_partitions_and_one_full_run():
    schema = (ROOT / "migrations" / "001_initial.sql").read_text().lower()
    assert "one_full_research_run" in schema
    assert "unique(run_id,phase,stage,partition_key)" in schema.replace(" ", "")
    assert "unique(execution_target_id,data_type,page_index)" in schema.replace(" ", "")


def test_templates_parse():
    env = Environment(loader=FileSystemLoader(ROOT / "app" / "templates"))
    env.get_template("login.html")
    env.get_template("dashboard.html")


def test_render_blueprint_is_separate_web_and_worker():
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text())
    services = blueprint["services"]
    assert [service["type"] for service in services] == ["web", "worker"]
    assert services[0]["name"] == "alpaca-138-research-web"
    assert services[1]["name"] == "alpaca-138-research-worker"
    assert services[1]["dockerCommand"] == "python -m app.worker"


def test_confirmation_protocol_is_rechecked_after_unlock():
    source = (ROOT / "app" / "orchestrator.py").read_text()
    assert 'run.get("confirmation_protocol_hash") != current_hash' in source
    assert "Protocol hash changed after confirmation unlock" in source


def test_duplicate_sensitivity_targets_share_one_raw_sip_cache():
    orchestrator = (ROOT / "app" / "orchestrator.py").read_text()
    processors = (ROOT / "app" / "processors.py").read_text()
    assert "raw_source_target_id" in orchestrator
    assert "same symbol-day may appear" in orchestrator.lower()
    assert '_iter_raw(raw_source_target_id, "trades")' in processors
    assert '_iter_raw(raw_source_target_id, "quotes")' in processors


def test_report_surfaces_sensitivities_and_controls():
    source = (ROOT / "app" / "reporting.py").read_text()
    assert "Pre-registered universe sensitivities" in source
    assert "Massive common-stock only" in source
    assert "Pre-registered non-signal controls" in source
    assert "Controls are diagnostics and are never included in strategy P&L" in source


def test_manual_resume_resets_exhausted_partition_attempts():
    source = (ROOT / "app" / "orchestrator.py").read_text()
    start = source[source.index("def start_run"):source.index("def cancel_run")]
    assert "attempts=0" in start
    assert "attempts < max_attempts" not in start
    assert "status in ('failed','cancelled')" in start


def test_smoke_probe_is_labelled_and_idempotent():
    source = (ROOT / "app" / "processors.py").read_text()
    schema = (ROOT / "migrations" / "001_initial.sql").read_text()
    assert "smoke_pipeline_probe_not_a_signal" in source
    assert "smoke_probe" in schema
    assert "when signal_triggers.quality_flags ? 'smoke_pipeline_probe_not_a_signal'" in source


def test_render_requires_explicit_data_entitlements():
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text())
    worker_keys = {item["key"] for item in blueprint["services"][1]["envVars"]}
    assert "ALPACA_SIP_CONFIRMED" in worker_keys
    assert "MASSIVE_ALL_HISTORY_CONFIRMED" in worker_keys


def test_cancel_marks_queued_and_running_partitions_for_resume():
    source = (ROOT / "app" / "orchestrator.py").read_text()
    cancel = source[source.index("def cancel_run"):source.index("def unlock_confirmation")]
    assert "status in ('queued','running')" in cancel


def test_quarterly_reports_are_checkpointed_and_confirmation_stays_final_gate_only():
    protocol = (ROOT / "app" / "protocol.py").read_text()
    orchestrator = (ROOT / "app" / "orchestrator.py").read_text()
    schema = (ROOT / "migrations" / "002_quarterly_tranches.sql").read_text().lower()
    assert '"early_validation_forbidden": True' in protocol
    assert '"tranche_report"' in orchestrator
    assert "research_tranches" in schema
    assert "standalone_report_object_path" in schema
    assert "cumulative_report_object_path" in schema


def test_worker_dashboard_surfaces_heartbeat_and_stale_state():
    main = (ROOT / "app" / "main.py").read_text()
    template = (ROOT / "app" / "templates" / "dashboard.html").read_text()
    assert "heartbeat_age_seconds" in main
    assert "stale_partition_minutes" in main
    assert "Possible stale partition" in template


def test_massive_reference_uses_exact_symbol_batches_not_catalogue_crawl():
    orchestrator = (ROOT / "app" / "orchestrator.py").read_text()
    processors = (ROOT / "app" / "processors.py").read_text()
    provider = (ROOT / "app" / "providers.py").read_text()
    migration = (ROOT / "migrations" / "003_massive_symbol_batches.sql").read_text().lower()
    assert 'f"symbol-batch-{index:05d}"' in orchestrator
    assert '"all-tickers"' not in orchestrator
    assert "ticker_reference(symbol, active=True)" in processors
    assert "ticker_reference(symbol, active=False)" in processors
    assert '"ticker": symbol' in provider
    assert "retired_legacy_all_tickers" in migration


def test_massive_batch_size_is_explicit_in_blueprint():
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text())
    worker_env = {item["key"]: item.get("value") for item in blueprint["services"][1]["envVars"]}
    assert worker_env["SYMBOL_BATCH_SIZE_MASSIVE"] == "100"


def test_massive_symbol_updates_and_cursor_checkpoint_share_one_transaction():
    source = (ROOT / "app" / "processors.py").read_text()
    block = source[source.index("def process_massive_reference"):source.index("def process_calendar")]
    assert "update instruments" in block
    assert "update work_partitions" in block
    assert block.index("update instruments") < block.index("update work_partitions") < block.index("conn.commit()")


def test_massive_invalid_ticker_errors_are_audited_not_retried_forever():
    providers = (ROOT / "app" / "providers.py").read_text()
    processors = (ROOT / "app" / "processors.py").read_text()
    assert "Invalid ticker parameter" in providers
    assert "raise InvalidTickerParameter(symbol)" in providers
    assert 'lookup_status = "invalid_ticker_parameter"' in processors
    assert '"research_impact": "excluded_from_massive_reference_sensitivity_only"' in processors
