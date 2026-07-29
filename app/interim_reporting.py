from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import date
from typing import Any

import pandas as pd

from app.db import connection, fetch_all, fetch_one
from app.protocol import APP_VERSION, PROTOCOL, protocol_hash
from app.reporting import MetricSet, _csv_bytes, _metric_set, _money, _number, _parquet_bytes, _pct, _safe_frame
from app.storage import StorageClient
from app.tranches import finalise_tranche


COHORTS = (
    "signal", "common_stock_signal", "expanded_signal", "liquidity_matched", "random", "smoke_probe"
)


def _trade_frame(run_id: str, phase: str, start: date, end: date) -> pd.DataFrame:
    rows = fetch_all(
        """
        select * from trade_results
         where run_id=%s and phase=%s and trade_date between %s and %s
         order by trade_date,symbol,cohort,scenario
        """,
        (run_id, phase, start, end),
    )
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=[
            "cohort", "scenario", "common_stock_sensitivity", "fill_status", "net_pnl",
            "net_return_pct", "gross_pnl", "fees", "trade_date", "entry_ts", "symbol",
            "unresolved", "target_hit", "stop_triggered",
        ])
    return frame


def _metrics(frame: pd.DataFrame, seed: str) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str], MetricSet]]:
    sets: list[MetricSet] = []
    for cohort in COHORTS:
        for scenario in PROTOCOL["execution_scenarios"]:
            for population in ("all", "common_stock"):
                sets.append(
                    _metric_set(
                        frame, cohort=cohort, scenario=scenario, population=population,
                        seed_material=f"{seed}:{cohort}:{scenario}:{population}:{protocol_hash()}",
                    )
                )
    return [item.as_dict() for item in sets], {
        (item.cohort, item.scenario, item.population): item for item in sets
    }


def assess_futility(
    lookup: dict[tuple[str, str, str], MetricSet], *, phase: str, run_kind: str, sequence_no: int
) -> dict[str, Any]:
    spec = PROTOCOL["early_futility_gate"]
    base = lookup[("signal", "base", "all")]
    conservative = lookup[("signal", "conservative", "all")]
    eligible = bool(
        spec["enabled"] and phase == "primary" and run_kind == "full"
        and sequence_no >= spec["earliest_primary_tranche"]
    )
    checks = {
        "minimum_completed_trades": base.completed >= spec["minimum_completed_trades"],
        "minimum_independent_dates": base.independent_dates >= spec["minimum_independent_dates"],
        "minimum_symbols": base.symbols >= spec["minimum_symbols"],
        "base_net_pnl_negative": base.net_pnl is not None and base.net_pnl < 0,
        "base_mean_return_negative": base.mean_return_pct is not None and base.mean_return_pct < 0,
        "conservative_net_pnl_negative": conservative.net_pnl is not None and conservative.net_pnl < 0,
        "date_block_bootstrap_95pct_upper_mean_return_nonpositive": (
            base.bootstrap_95pct_upper_mean_return is not None
            and base.bootstrap_95pct_upper_mean_return <= 0
        ),
    }
    stop = eligible and all(checks.values())
    return {
        "eligible": eligible,
        "stop": stop,
        "checks": checks,
        "specification": spec,
        "classification": "rejected_early_for_futility" if stop else "continue_testing",
        "note": (
            "This is a pre-registered early rejection rule. A positive interim result can never validate the strategy."
        ),
    }


def _quality(run_id: str, phase: str, start: date, end: date) -> dict[str, int]:
    row = fetch_one(
        """
        select
          (select count(*) from market_sessions where run_id=%s and phase=%s and trade_date between %s and %s)::int sessions,
          (select count(*) from decision_snapshots where run_id=%s and phase=%s and trade_date between %s and %s)::int decision_snapshots,
          (select count(*) from signal_triggers where run_id=%s and phase=%s and trade_date between %s and %s and qualifies=true)::int qualifying_triggers,
          (select count(*) from execution_targets where run_id=%s and phase=%s and trade_date between %s and %s)::int execution_targets,
          (select count(*) from trade_results where run_id=%s and phase=%s and trade_date between %s and %s)::int trade_results,
          (select count(*) from work_partitions where run_id=%s and phase=%s and status='failed')::int failed_partitions
        """,
        (
            run_id,phase,start,end,run_id,phase,start,end,run_id,phase,start,end,
            run_id,phase,start,end,run_id,phase,start,end,run_id,phase,
        ),
    ) or {}
    return {key: int(value or 0) for key, value in row.items()}


def _interim_markdown(
    *, label: str, scope: str, phase: str, start: date, end: date,
    lookup: dict[tuple[str, str, str], MetricSet], futility: dict[str, Any], quality: dict[str, int],
) -> str:
    base = lookup[("signal", "base", "all")]
    optimistic = lookup[("signal", "optimistic", "all")]
    conservative = lookup[("signal", "conservative", "all")]
    lines = [
        f"# 13.776879% {scope} interim report — {label}", "",
        f"**Period:** {start.isoformat()} to {end.isoformat()}  ",
        f"**Phase:** `{phase}`  ",
        f"**Protocol hash:** `{protocol_hash()}`  ",
        f"**Interim classification:** `{futility['classification']}`", "",
        "This report cannot validate the strategy. Only the complete 2024–2025 primary gate can unlock confirmation.", "",
        "## Signal execution results", "",
        "| Scenario | Targets | Completed | Net P&L | Mean return | Median return | Profit factor | 95% bootstrap interval |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in (optimistic, base, conservative):
        interval = f"{_pct(row.bootstrap_95pct_lower_mean_return)} to {_pct(row.bootstrap_95pct_upper_mean_return)}"
        lines.append(
            f"| {row.scenario} | {row.targets} | {row.completed} | {_money(row.net_pnl)} | "
            f"{_pct(row.mean_return_pct)} | {_pct(row.median_return_pct)} | {_number(row.profit_factor)} | {interval} |"
        )
    lines += ["", "## Pre-registered futility assessment", ""]
    for name, passed in futility["checks"].items():
        lines.append(f"- {'PASS' if passed else 'not met'} — {name.replace('_', ' ')}")
    lines += [
        "",
        ("**Automatic early-futility stop triggered.** The primary study is rejected and confirmation remains sealed."
         if futility["stop"] else
         "No futility stop was triggered. Testing continues to the next locked tranche."),
        "", "## Coverage", "",
        f"- Market sessions: {quality['sessions']:,}",
        f"- Decision snapshots: {quality['decision_snapshots']:,}",
        f"- Exact qualifiers: {quality['qualifying_triggers']:,}",
        f"- Execution targets: {quality['execution_targets']:,}",
        f"- Simulated scenario results: {quality['trade_results']:,}",
        f"- Permanently failed partitions in phase: {quality['failed_partitions']:,}",
        "", "## Integrity rule", "",
        "A favourable quarter is labelled promising only. Thresholds, execution assumptions, gates and later periods remain unchanged.",
        "", f"Generated by app version {APP_VERSION}.",
    ]
    return "\n".join(lines) + "\n"


def _archive(
    *, run_id: str, phase: str, tranche_key: str, label: str, scope: str,
    start: date, end: date, frame: pd.DataFrame, metric_rows: list[dict[str, Any]],
    lookup: dict[tuple[str, str, str], MetricSet], futility: dict[str, Any], quality: dict[str, int],
) -> tuple[bytes, dict[str, Any]]:
    markdown = _interim_markdown(
        label=label,scope=scope,phase=phase,start=start,end=end,lookup=lookup,futility=futility,quality=quality,
    )
    metric_frame = _safe_frame(metric_rows)
    trade_frame = _safe_frame(frame.to_dict("records"))
    files: dict[str, bytes] = {
        "INTERIM_REPORT.md": markdown.encode("utf-8"),
        "interim_metrics.json": (json.dumps(metric_rows,indent=2,sort_keys=True,default=str)+"\n").encode(),
        "futility_assessment.json": (json.dumps(futility,indent=2,sort_keys=True,default=str)+"\n").encode(),
        "data_quality.json": (json.dumps(quality,indent=2,sort_keys=True,default=str)+"\n").encode(),
        "interim_summary.csv": _csv_bytes(metric_frame),
        "interim_summary.parquet": _parquet_bytes(metric_frame),
        "interim_trades.csv": _csv_bytes(trade_frame),
        "interim_trades.parquet": _parquet_bytes(trade_frame),
        "preregistered_execution_spec.json": (json.dumps(PROTOCOL,indent=2,sort_keys=True)+"\n").encode(),
        "protocol_hash.txt": (protocol_hash()+"\n").encode(),
    }
    manifest = {
        "run_id":run_id,"phase":phase,"tranche_key":tranche_key,"label":label,"scope":scope,
        "start":start.isoformat(),"end":end.isoformat(),"protocol_hash":protocol_hash(),"app_version":APP_VERSION,
        "files":[
            {"path":name,"size_bytes":len(payload),"sha256":hashlib.sha256(payload).hexdigest()}
            for name,payload in sorted(files.items())
        ],
    }
    files["manifest.json"]=(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,payload in files.items():
            archive.writestr(name,payload)
    return buffer.getvalue(), {"metrics":metric_rows,"quality":quality,"futility":futility}


def build_tranche_reports(run_id: str, phase: str, params: dict[str, Any]) -> dict[str, Any]:
    run = fetch_one("select * from research_runs where id=%s", (run_id,))
    if not run:
        raise RuntimeError("Research run missing")
    if run["protocol_hash"] != protocol_hash():
        raise RuntimeError("Protocol hash mismatch while creating interim report")
    tranche_key = str(params["tranche_key"])
    tranche = fetch_one(
        "select protocol_hash from research_tranches where run_id=%s and phase=%s and tranche_key=%s",
        (run_id,phase,tranche_key),
    )
    if not tranche or tranche["protocol_hash"] != protocol_hash():
        raise RuntimeError("Tranche protocol hash mismatch")
    sequence_no = int(params["sequence_no"])
    label = str(params["label"])
    start = date.fromisoformat(params["start"])
    end = date.fromisoformat(params["end"])
    cumulative_start = run["primary_start"] if phase == "primary" else run["confirmation_start"]

    standalone_frame = _trade_frame(run_id,phase,start,end)
    standalone_rows,standalone_lookup = _metrics(standalone_frame,f"{run_id}:{phase}:{tranche_key}:standalone")
    cumulative_frame = _trade_frame(run_id,phase,cumulative_start,end)
    cumulative_rows,cumulative_lookup = _metrics(cumulative_frame,f"{run_id}:{phase}:{tranche_key}:cumulative")
    futility = assess_futility(
        cumulative_lookup,phase=phase,run_kind=run["run_kind"],sequence_no=sequence_no,
    )
    standalone_quality = _quality(run_id,phase,start,end)
    cumulative_quality = _quality(run_id,phase,cumulative_start,end)

    standalone_futility = {
        "eligible": False,"stop": False,"checks": {},
        "specification": PROTOCOL["early_futility_gate"],
        "classification": "standalone_descriptive_only",
        "note": "Futility is evaluated only on cumulative results, never on a standalone quarter.",
    }
    standalone_zip,standalone_payload = _archive(
        run_id=run_id,phase=phase,tranche_key=tranche_key,label=label,scope="standalone",
        start=start,end=end,frame=standalone_frame,metric_rows=standalone_rows,lookup=standalone_lookup,
        futility=standalone_futility,quality=standalone_quality,
    )
    cumulative_zip,cumulative_payload = _archive(
        run_id=run_id,phase=phase,tranche_key=tranche_key,label=label,scope="cumulative",
        start=cumulative_start,end=end,frame=cumulative_frame,metric_rows=cumulative_rows,lookup=cumulative_lookup,
        futility=futility,quality=cumulative_quality,
    )
    root=f"runs/{run_id}/{phase}/interim/{tranche_key}"
    standalone_path=f"{root}/alpaca_13_8_{tranche_key}_standalone.zip"
    cumulative_path=f"{root}/alpaca_13_8_{tranche_key}_cumulative.zip"
    storage=StorageClient()
    storage.upload_bytes(standalone_path,standalone_zip,"application/zip")
    storage.upload_bytes(cumulative_path,cumulative_zip,"application/zip")

    finalise_tranche(
        run_id,phase,tranche_key,sequence_no,
        standalone_path=standalone_path,cumulative_path=cumulative_path,
        standalone_metrics=standalone_payload,cumulative_metrics=cumulative_payload,futility=futility,
    )
    return {
        "trade_count":len(cumulative_frame),"standalone_path":standalone_path,
        "cumulative_path":cumulative_path,"futility":futility,
    }
