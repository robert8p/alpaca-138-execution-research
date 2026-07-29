from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from psycopg.types.json import Jsonb

from app.db import connection, fetch_all, fetch_one
from app.protocol import APP_VERSION, PROTOCOL, protocol_hash
from app.storage import StorageClient


@dataclass(frozen=True)
class MetricSet:
    cohort: str
    scenario: str
    population: str
    targets: int
    filled: int
    completed: int
    unresolved: int
    fill_rate: float | None
    win_rate: float | None
    gross_pnl: float | None
    fees: float | None
    net_pnl: float | None
    mean_return_pct: float | None
    median_return_pct: float | None
    profit_factor: float | None
    maximum_drawdown: float | None
    maximum_consecutive_losses: int
    pnl_excluding_three_largest_winners: float | None
    bootstrap_95pct_lower_mean_return: float | None
    bootstrap_95pct_upper_mean_return: float | None
    single_symbol_profit_share: float | None
    single_date_profit_share: float | None
    independent_dates: int
    symbols: int
    target_hit_rate: float | None
    stop_rate: float | None
    unresolved_rate: float | None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _f(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def _drawdown(daily: pd.Series) -> float | None:
    if daily.empty:
        return None
    equity = daily.cumsum()
    peaks = equity.cummax().clip(lower=0.0)
    return float((peaks - equity).max())


def _loss_streak(values: list[float]) -> int:
    best = current = 0
    for value in values:
        if value < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _bootstrap_bounds(
    frame: pd.DataFrame, seed_material: str, iterations: int = 5000
) -> tuple[float | None, float | None]:
    completed = frame.dropna(subset=["net_return_pct"]).copy()
    if completed.empty:
        return None, None
    dates = sorted(completed["trade_date"].astype(str).unique())
    if len(dates) < 2:
        return None, None
    grouped = {
        d: completed.loc[completed["trade_date"].astype(str) == d, "net_return_pct"].to_numpy(float)
        for d in dates
    }
    seed = int(hashlib.sha256(seed_material.encode()).hexdigest()[:16], 16) % (2**32)
    rng = np.random.default_rng(seed)
    means = np.empty(iterations, dtype=float)
    for i in range(iterations):
        sampled = rng.choice(dates, size=len(dates), replace=True)
        values = np.concatenate([grouped[d] for d in sampled])
        means[i] = float(np.mean(values))
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def _bootstrap_lower(frame: pd.DataFrame, seed_material: str, iterations: int = 5000) -> float | None:
    return _bootstrap_bounds(frame, seed_material, iterations)[0]

def _metric_set(
    frame: pd.DataFrame,
    *,
    cohort: str,
    scenario: str,
    population: str,
    seed_material: str,
) -> MetricSet:
    selected = frame[(frame["cohort"] == cohort) & (frame["scenario"] == scenario)].copy()
    if population == "common_stock":
        selected = selected[selected["common_stock_sensitivity"] == True]  # noqa: E712
    targets = len(selected)
    filled = selected[selected["fill_status"] == "filled"].copy()
    completed = filled.dropna(subset=["net_pnl", "net_return_pct"]).sort_values(["trade_date", "entry_ts", "symbol"])
    winners = completed[completed["net_pnl"] > 0]
    losers = completed[completed["net_pnl"] < 0]
    gains = float(winners["net_pnl"].sum()) if not winners.empty else 0.0
    losses = abs(float(losers["net_pnl"].sum())) if not losers.empty else 0.0
    if losses > 0:
        profit_factor: float | None = gains / losses
    elif gains > 0:
        profit_factor = 1_000_000_000.0
    else:
        profit_factor = None
    # Concentration is measured against total net strategy profit, not gross winning
    # trades. Losses therefore cannot make concentration appear artificially safer.
    total_net_profit = float(completed["net_pnl"].sum()) if not completed.empty else 0.0
    symbol_share = None
    date_share = None
    if total_net_profit > 0:
        symbol_profit = completed.groupby("symbol")["net_pnl"].sum().clip(lower=0)
        date_profit = completed.groupby("trade_date")["net_pnl"].sum().clip(lower=0)
        symbol_share = float(symbol_profit.max() / total_net_profit) if not symbol_profit.empty else None
        date_share = float(date_profit.max() / total_net_profit) if not date_profit.empty else None
    daily = completed.groupby("trade_date")["net_pnl"].sum().sort_index() if not completed.empty else pd.Series(dtype=float)
    sorted_pnl = completed["net_pnl"].astype(float).tolist() if not completed.empty else []
    without_top3 = completed.sort_values("net_pnl", ascending=False).iloc[3:] if len(completed) > 3 else completed.iloc[0:0]
    unresolved = int(filled["unresolved"].fillna(False).astype(bool).sum()) if not filled.empty else 0
    bootstrap_lower, bootstrap_upper = _bootstrap_bounds(completed, seed_material)
    return MetricSet(
        cohort=cohort,
        scenario=scenario,
        population=population,
        targets=targets,
        filled=len(filled),
        completed=len(completed),
        unresolved=unresolved,
        fill_rate=(len(filled) / targets if targets else None),
        win_rate=(len(winners) / len(completed) if len(completed) else None),
        gross_pnl=_f(completed["gross_pnl"].sum()) if not completed.empty else None,
        fees=_f(completed["fees"].sum()) if not completed.empty else None,
        net_pnl=_f(completed["net_pnl"].sum()) if not completed.empty else None,
        mean_return_pct=_f(completed["net_return_pct"].mean()) if not completed.empty else None,
        median_return_pct=_f(completed["net_return_pct"].median()) if not completed.empty else None,
        profit_factor=profit_factor,
        maximum_drawdown=_drawdown(daily),
        maximum_consecutive_losses=_loss_streak(sorted_pnl),
        pnl_excluding_three_largest_winners=_f(without_top3["net_pnl"].sum()) if not without_top3.empty else 0.0,
        bootstrap_95pct_lower_mean_return=bootstrap_lower,
        bootstrap_95pct_upper_mean_return=bootstrap_upper,
        single_symbol_profit_share=symbol_share,
        single_date_profit_share=date_share,
        independent_dates=int(completed["trade_date"].nunique()) if not completed.empty else 0,
        symbols=int(completed["symbol"].nunique()) if not completed.empty else 0,
        target_hit_rate=(float(completed["target_hit"].fillna(False).mean()) if not completed.empty else None),
        stop_rate=(float(completed["stop_triggered"].fillna(False).mean()) if not completed.empty else None),
        unresolved_rate=(unresolved / len(filled) if len(filled) else None),
    )


def _gate(base: MetricSet, conservative: MetricSet) -> dict[str, Any]:
    spec = PROTOCOL["primary_gate"]
    checks = {
        "minimum_filled_trades": base.completed >= spec["minimum_filled_trades"],
        "minimum_independent_dates": base.independent_dates >= spec["minimum_independent_dates"],
        "minimum_symbols": base.symbols >= spec["minimum_symbols"],
        "net_pnl_positive": (base.net_pnl or 0) > 0,
        "profit_factor_minimum": base.profit_factor is not None and base.profit_factor >= spec["profit_factor_minimum"],
        "base_mean_return_positive": (base.mean_return_pct or 0) > 0,
        "base_median_return_positive": (base.median_return_pct or 0) > 0,
        "conservative_net_pnl_nonnegative": conservative.net_pnl is not None and conservative.net_pnl >= 0,
        "pnl_excluding_three_largest_winners_positive": (base.pnl_excluding_three_largest_winners or 0) > 0,
        "date_block_bootstrap_95pct_lower_mean_return_positive": (base.bootstrap_95pct_lower_mean_return or 0) > 0,
        "maximum_drawdown_usd": base.maximum_drawdown is not None and base.maximum_drawdown <= spec["maximum_drawdown_usd"],
        "maximum_consecutive_losses": base.maximum_consecutive_losses <= spec["maximum_consecutive_losses"],
        "maximum_unresolved_exit_rate": base.unresolved_rate is not None and base.unresolved_rate <= spec["maximum_unresolved_exit_rate"],
        "maximum_single_symbol_profit_share": base.single_symbol_profit_share is not None and base.single_symbol_profit_share <= spec["maximum_single_symbol_profit_share"],
        "maximum_single_date_profit_share": base.single_date_profit_share is not None and base.single_date_profit_share <= spec["maximum_single_date_profit_share"],
    }
    return {"passed": all(checks.values()), "checks": checks, "specification": spec}


def _classification(phase: str, gate: dict[str, Any], base: MetricSet, run: dict[str, Any]) -> str:
    if run["protocol_hash"] != protocol_hash():
        return "invalid_process"
    if phase == "confirmation" and run.get("confirmation_protocol_hash") != protocol_hash():
        return "invalid_process"
    if phase == "primary":
        if gate["passed"]:
            return "promising_but_unproven"
        if (base.net_pnl or 0) > 0 and base.completed > 0:
            return "promising_but_unproven"
        return "rejected"
    primary_pass = bool(run.get("primary_gate_passed"))
    if primary_pass and gate["passed"]:
        return "validated_for_paper_testing"
    if (base.net_pnl or 0) > 0 and base.completed > 0:
        return "promising_but_unproven"
    return "rejected"


def _safe_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for col in frame.columns:
        if frame[col].dtype == "object":
            def normalise(value):
                if isinstance(value, (dict, list)):
                    return json.dumps(value, sort_keys=True, default=str)
                if hasattr(value, "isoformat"):
                    return value.isoformat()
                if value is not None and value.__class__.__name__ == "UUID":
                    return str(value)
                return value
            frame[col] = frame[col].map(normalise)
    return frame


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    return buffer.getvalue()


def _markdown(
    *,
    run: dict[str, Any],
    phase: str,
    classification: str,
    gate: dict[str, Any],
    metric_rows: list[dict[str, Any]],
    quality: dict[str, Any],
) -> str:
    lookup = {(row["cohort"], row["scenario"], row["population"]): row for row in metric_rows}
    base = lookup[("signal", "base", "all")]
    optimistic = lookup[("signal", "optimistic", "all")]
    conservative = lookup[("signal", "conservative", "all")]
    failed = [name for name, passed in gate["checks"].items() if not passed]
    lines = [
        f"# 13.776879% execution backtest — {phase}",
        "",
        f"**Classification:** `{classification}`  ",
        f"**Frozen gate:** {'PASS' if gate['passed'] else 'FAIL'}  ",
        f"**Protocol hash:** `{protocol_hash()}`",
        "",
        "## Frozen question",
        "",
        "At 17:00 Europe/London, does buying up to five US equities whose last available SIP trade is strictly more than 13.776879223878035% above the previous regular-session close produce positive, robust, executable intraday returns?",
        "",
        "No threshold, reaction time, stop, target, ranking rule or gate was optimised from this phase's outcomes.",
        "",
        "## Primary signal results",
        "",
        "| Scenario | Targets | Completed trades | Net P&L | Mean return | Median return | Profit factor | Max drawdown |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in (optimistic, base, conservative):
        lines.append(
            f"| {row['scenario']} | {row['targets']} | {row['completed']} | "
            f"{_money(row['net_pnl'])} | {_pct(row['mean_return_pct'])} | {_pct(row['median_return_pct'])} | "
            f"{_number(row['profit_factor'])} | {_money(row['maximum_drawdown'])} |"
        )
    lines += [
        "",
        "## Pre-registered universe sensitivities — base execution",
        "",
        "| Cohort | Targets | Completed | Net P&L | Mean return | Median return | Profit factor |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for cohort, label in (
        ("signal", "Original Alpaca universe"),
        ("common_stock_signal", "Massive common-stock only"),
        ("expanded_signal", "Expanded active/inactive market-data universe"),
    ):
        row = lookup[(cohort, "base", "all")]
        lines.append(
            f"| {label} | {row['targets']} | {row['completed']} | {_money(row['net_pnl'])} | "
            f"{_pct(row['mean_return_pct'])} | {_pct(row['median_return_pct'])} | {_number(row['profit_factor'])} |"
        )
    lines += [
        "",
        "## Pre-registered non-signal controls — base execution",
        "",
        "Controls are diagnostics and are never included in strategy P&L.",
        "",
        "| Cohort | Targets | Completed | Net P&L | Mean return | Median return |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for cohort, label in (("liquidity_matched", "Liquidity matched"), ("random", "Deterministic random")):
        row = lookup[(cohort, "base", "all")]
        lines.append(
            f"| {label} | {row['targets']} | {row['completed']} | {_money(row['net_pnl'])} | "
            f"{_pct(row['mean_return_pct'])} | {_pct(row['median_return_pct'])} |"
        )
    lines += [
        "",
        "## Gate decision",
        "",
        ("Every frozen gate passed." if gate["passed"] else "Failed gates: " + ", ".join(failed)),
        "",
        "## Data quality",
        "",
        f"- Catalogue instruments: {quality['catalogue_instruments']:,}",
        f"- Legacy-universe instruments: {quality['legacy_universe_instruments']:,}",
        f"- Common-stock sensitivity instruments: {quality['common_stock_instruments']:,}",
        f"- Market sessions: {quality['sessions']:,}",
        f"- Decision snapshots: {quality['decision_snapshots']:,}",
        f"- Exact-verification candidates: {quality['exact_verification_candidates']:,}",
        f"- Exactly verified qualifiers: {quality['qualifying_triggers']:,}",
        f"- Missing previous-close snapshots: {quality['missing_previous_close']:,}",
        f"- No completed decision-bar snapshots: {quality['missing_decision_bar']:,}",
        f"- Stale decision-bar snapshots: {quality['stale_decision_bar']:,}",
        f"- Split-date exclusions: {quality['split_exclusions']:,}",
        f"- Execution targets: {quality['execution_targets']:,}",
        f"- Raw SIP objects: {quality['raw_objects']:,} ({quality['raw_size_bytes'] / 1024**3:,.2f} GiB)",
        f"- Permanently failed partitions: {quality['failed_partitions']:,}",
        "",
        "## Interpretation",
        "",
    ]
    if phase == "primary" and gate["passed"]:
        lines.append("The primary period passed. The locked 2026 confirmation period may now be explicitly opened without changing the protocol.")
    elif phase == "primary":
        lines.append("The primary period did not pass every frozen gate. The confirmation period remains locked to prevent repeated testing from becoming threshold optimisation.")
    elif classification == "validated_for_paper_testing":
        lines.append("The frozen rule passed both the primary and confirmation gates. This supports paper testing only; it does not authorise live trading.")
    else:
        lines.append("The confirmation did not justify paper testing under the frozen acceptance standard.")
    lines += [
        "",
        "## Important limitations",
        "",
        "- Historical SIP NBBO size is displayed top-of-book liquidity, not a guarantee of queue position or fill.",
        "- The primary universe reproduces the original current active/tradable Alpaca-universe method and therefore has historical survivorship limitations.",
        "- A Massive common-stock-only sensitivity is reported separately rather than silently changing the original universe.",
        "- Forced overnight positions remain unresolved for the primary intraday gate even when a secondary next-session quote is available.",
        "- This application contains no order-placement capability.",
        "",
        f"Generated by app version {APP_VERSION}.",
    ]
    return "\n".join(lines) + "\n"


def _money(value: Any) -> str:
    return "—" if value is None else f"US${float(value):,.2f}"


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.3f}%"


def _number(value: Any) -> str:
    if value is None:
        return "—"
    if math.isinf(float(value)):
        return "∞"
    return f"{float(value):.3f}"


def build_phase_report(run_id: str, phase: str) -> dict[str, Any]:
    run = fetch_one("select * from research_runs where id=%s", (run_id,))
    if not run:
        raise RuntimeError("Research run missing")
    trade_rows = fetch_all(
        "select * from trade_results where run_id=%s and phase=%s order by trade_date,symbol,cohort,scenario",
        (run_id, phase),
    )
    trades = pd.DataFrame(trade_rows)
    if trades.empty:
        trades = pd.DataFrame(columns=[
            "cohort", "scenario", "common_stock_sensitivity", "fill_status", "net_pnl",
            "net_return_pct", "gross_pnl", "fees", "trade_date", "entry_ts", "symbol",
            "unresolved", "target_hit", "stop_triggered",
        ])
    metrics: list[MetricSet] = []
    for cohort in ("signal", "common_stock_signal", "expanded_signal", "liquidity_matched", "random", "smoke_probe"):
        for scenario in PROTOCOL["execution_scenarios"]:
            for population in ("all", "common_stock"):
                metrics.append(
                    _metric_set(
                        trades,
                        cohort=cohort,
                        scenario=scenario,
                        population=population,
                        seed_material=f"{run_id}:{phase}:{cohort}:{scenario}:{population}:{protocol_hash()}",
                    )
                )
    metric_rows = [m.as_dict() for m in metrics]
    lookup = {(m.cohort, m.scenario, m.population): m for m in metrics}
    base = lookup[("signal", "base", "all")]
    conservative = lookup[("signal", "conservative", "all")]
    gate = _gate(base, conservative)
    classification = _classification(phase, gate, base, run)

    quality_row = fetch_one(
        """
        select
          (select count(*) from instruments where run_id=%s)::int catalogue_instruments,
          (select count(*) from instruments where run_id=%s and legacy_universe_eligible=true)::int legacy_universe_instruments,
          (select count(*) from instruments where run_id=%s and common_stock_sensitivity=true)::int common_stock_instruments,
          (select count(*) from market_sessions where run_id=%s and phase=%s)::int sessions,
          (select count(*) from decision_snapshots where run_id=%s and phase=%s)::int decision_snapshots,
          (select count(*) from decision_snapshots where run_id=%s and phase=%s and exact_verification_required=true)::int exact_verification_candidates,
          (select count(*) from signal_triggers where run_id=%s and phase=%s and qualifies=true)::int qualifying_triggers,
          (select count(*) from decision_snapshots where run_id=%s and phase=%s and previous_close is null)::int missing_previous_close,
          (select count(*) from decision_snapshots where run_id=%s and phase=%s and latest_bar_ts is null)::int missing_decision_bar,
          (select count(*) from decision_snapshots where run_id=%s and phase=%s and coalesce(bar_age_seconds,0)>300)::int stale_decision_bar,
          (select count(*) from decision_snapshots where run_id=%s and phase=%s and split_excluded=true)::int split_exclusions,
          (select count(*) from execution_targets where run_id=%s and phase=%s)::int execution_targets,
          (select count(*) from raw_objects where run_id=%s and phase=%s)::int raw_objects,
          (select coalesce(sum(size_bytes),0) from raw_objects where run_id=%s and phase=%s)::bigint raw_size_bytes,
          (select count(*) from work_partitions where run_id=%s and phase=%s and status='failed')::int failed_partitions
        """,
        (
            run_id, run_id, run_id,
            run_id, phase,
            run_id, phase,
            run_id, phase,
            run_id, phase,
            run_id, phase,
            run_id, phase,
            run_id, phase,
            run_id, phase,
            run_id, phase,
            run_id, phase,
            run_id, phase,
            run_id, phase,
        ),
    ) or {}
    quality = {k: int(v or 0) for k, v in quality_row.items()}

    triggers_rows = fetch_all(
        """
        select st.*,ds.proxy_return_pct,ds.proxy_high_return_pct,ds.latest_bar_volume,
               ds.latest_bar_trade_count,ds.legacy_universe_eligible,ds.expanded_universe_eligible,
               ds.common_stock_sensitivity
          from signal_triggers st join decision_snapshots ds using(run_id,phase,trade_date,symbol)
         where st.run_id=%s and st.phase=%s order by st.trade_date,st.exact_return_pct desc,st.symbol
        """,
        (run_id, phase),
    )
    day_rows = fetch_all(
        """
        select ms.trade_date,ms.decision_ts,
               count(ds.symbol)::int snapshot_count,
               count(ds.symbol) filter(where ds.legacy_universe_eligible)::int legacy_snapshot_count,
               count(st.id) filter(where st.qualifies)::int qualifying_count,
               count(st.id) filter(where st.selected)::int selected_count
          from market_sessions ms
          left join decision_snapshots ds on ds.run_id=ms.run_id and ds.phase=ms.phase and ds.trade_date=ms.trade_date
          left join signal_triggers st on st.run_id=ds.run_id and st.phase=ds.phase and st.trade_date=ds.trade_date and st.symbol=ds.symbol
         where ms.run_id=%s and ms.phase=%s
         group by ms.trade_date,ms.decision_ts order by ms.trade_date
        """,
        (run_id, phase),
    )

    metric_frame = _safe_frame(metric_rows)
    trigger_frame = _safe_frame(triggers_rows)
    trade_frame = _safe_frame(trade_rows)
    day_frame = _safe_frame(day_rows)
    report_md = _markdown(
        run=run, phase=phase, classification=classification, gate=gate,
        metric_rows=metric_rows, quality=quality,
    )

    files: dict[str, bytes] = {
        "BACKTEST_REPORT.md": report_md.encode("utf-8"),
        "preregistered_execution_spec.json": (json.dumps(PROTOCOL, indent=2, sort_keys=True) + "\n").encode(),
        "protocol_hash.txt": (protocol_hash() + "\n").encode(),
        "profitability_gate.json": (json.dumps(gate, indent=2, sort_keys=True, default=str) + "\n").encode(),
        "data_quality.json": (json.dumps(quality, indent=2, sort_keys=True, default=str) + "\n").encode(),
        "strategy_summary.csv": _csv_bytes(metric_frame),
        "strategy_summary.parquet": _parquet_bytes(metric_frame),
        "backtest_triggers.csv": _csv_bytes(trigger_frame),
        "backtest_triggers.parquet": _parquet_bytes(trigger_frame),
        "backtest_trades.csv": _csv_bytes(trade_frame),
        "backtest_trades.parquet": _parquet_bytes(trade_frame),
        "backtest_days.csv": _csv_bytes(day_frame),
        "backtest_days.parquet": _parquet_bytes(day_frame),
    }
    manifest = {
        "run_id": run_id,
        "phase": phase,
        "classification": classification,
        "gate_passed": gate["passed"],
        "protocol_hash": protocol_hash(),
        "app_version": APP_VERSION,
        "files": [
            {"path": name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
            for name, payload in sorted(files.items())
        ],
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, payload in files.items():
            zf.writestr(name, payload)
    object_path = f"runs/{run_id}/{phase}/reports/alpaca_13_8_{phase}_backtest.zip"
    StorageClient().upload_bytes(object_path, archive.getvalue(), "application/zip")

    metrics_json = {
        "classification": classification,
        "gate": gate,
        "summaries": metric_rows,
        "protocol_hash": protocol_hash(),
    }
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into phase_reports(
                run_id,phase,status,classification,gate_passed,metrics,data_quality,
                report_object_path,protocol_hash
            ) values (%s,%s,'completed',%s,%s,%s,%s,%s,%s)
            on conflict(run_id,phase) do update set
                status='completed',classification=excluded.classification,gate_passed=excluded.gate_passed,
                metrics=excluded.metrics,data_quality=excluded.data_quality,
                report_object_path=excluded.report_object_path,protocol_hash=excluded.protocol_hash,updated_at=now()
            """,
            (
                run_id, phase, classification, gate["passed"], Jsonb(metrics_json),
                Jsonb(quality), object_path, protocol_hash(),
            ),
        )
        if run["run_kind"] == "smoke":
            cur.execute(
                "update research_runs set status='completed',final_classification='smoke_test_complete',completed_at=now(),updated_at=now() where id=%s",
                (run_id,),
            )
        elif phase == "primary":
            cur.execute(
                """
                update research_runs
                   set status='primary_complete',primary_gate_passed=%s,final_classification=%s,updated_at=now()
                 where id=%s
                """,
                (gate["passed"], classification, run_id),
            )
        else:
            cur.execute(
                """
                update research_runs
                   set status='completed',final_classification=%s,completed_at=now(),updated_at=now()
                 where id=%s
                """,
                (classification, run_id),
            )
        conn.commit()
    return {"trade_count": len(trade_rows), "object_path": object_path, "gate": gate, "classification": classification}
