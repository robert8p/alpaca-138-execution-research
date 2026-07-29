create extension if not exists pgcrypto;

create table if not exists research_runs (
    id uuid primary key default gen_random_uuid(),
    run_kind text not null check (run_kind in ('smoke','full')),
    status text not null default 'created' check (status in (
        'created','running','primary_complete','confirmation_locked','confirmation_running',
        'completed','failed','cancelled'
    )),
    current_phase text not null default 'primary' check (current_phase in ('primary','confirmation')),
    primary_start date not null,
    primary_end date not null,
    confirmation_start date,
    confirmation_end date,
    protocol jsonb not null,
    protocol_hash text not null,
    app_version text not null,
    cancel_requested boolean not null default false,
    confirmation_unlocked_at timestamptz,
    confirmation_protocol_hash text,
    primary_gate_passed boolean,
    final_classification text,
    error text,
    progress jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz,
    updated_at timestamptz not null default now()
);
create unique index if not exists one_full_research_run on research_runs(run_kind) where run_kind='full';

create table if not exists instruments (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references research_runs(id) on delete cascade,
    alpaca_asset_id text,
    symbol text not null,
    name text,
    exchange text,
    alpaca_status text,
    current_active boolean not null default false,
    current_tradable boolean not null default false,
    fractionable boolean not null default false,
    shortable boolean not null default false,
    easy_to_borrow boolean not null default false,
    marginable boolean not null default false,
    otc boolean not null default false,
    legacy_universe_eligible boolean not null default false,
    expanded_universe_eligible boolean not null default false,
    massive_type text,
    massive_active boolean,
    massive_primary_exchange text,
    massive_cik text,
    massive_composite_figi text,
    common_stock_sensitivity boolean not null default false,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(run_id,symbol)
);
create index if not exists instruments_run_legacy_idx on instruments(run_id,legacy_universe_eligible,symbol);
create index if not exists instruments_run_expanded_idx on instruments(run_id,expanded_universe_eligible,symbol);

create table if not exists market_sessions (
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null check (phase in ('primary','confirmation')),
    trade_date date not null,
    session_open timestamptz not null,
    session_close timestamptz not null,
    decision_ts timestamptz not null,
    next_session_open timestamptz,
    status text not null default 'pending',
    metadata jsonb not null default '{}'::jsonb,
    primary key(run_id,phase,trade_date)
);

create table if not exists corporate_actions (
    run_id uuid not null references research_runs(id) on delete cascade,
    symbol text not null,
    action_type text not null,
    execution_date date not null,
    split_from numeric,
    split_to numeric,
    source text not null,
    metadata jsonb not null default '{}'::jsonb,
    primary key(run_id,symbol,action_type,execution_date)
);

create table if not exists daily_bars (
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null check (phase in ('primary','confirmation')),
    symbol text not null,
    trade_date date not null,
    ts timestamptz not null,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision,
    vwap double precision,
    trade_count bigint,
    source_feed text not null default 'sip',
    primary key(run_id,phase,symbol,trade_date)
);
create index if not exists daily_bars_run_date_idx on daily_bars(run_id,phase,trade_date,symbol);

create table if not exists decision_snapshots (
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null check (phase in ('primary','confirmation')),
    trade_date date not null,
    symbol text not null,
    decision_ts timestamptz not null,
    latest_bar_ts timestamptz,
    latest_bar_open double precision,
    latest_bar_high double precision,
    latest_bar_low double precision,
    latest_bar_close double precision,
    latest_bar_volume double precision,
    latest_bar_vwap double precision,
    latest_bar_trade_count bigint,
    previous_close double precision,
    proxy_return_pct double precision,
    proxy_high_return_pct double precision,
    bar_age_seconds integer,
    split_excluded boolean not null default false,
    legacy_universe_eligible boolean not null default false,
    expanded_universe_eligible boolean not null default false,
    common_stock_sensitivity boolean not null default false,
    exact_verification_required boolean not null default false,
    quality_flags jsonb not null default '[]'::jsonb,
    primary key(run_id,phase,trade_date,symbol)
);
create index if not exists decision_snapshots_trigger_idx on decision_snapshots(run_id,phase,trade_date,exact_verification_required);
create index if not exists decision_snapshots_return_idx on decision_snapshots(run_id,phase,trade_date,proxy_return_pct desc);

create table if not exists signal_triggers (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null check (phase in ('primary','confirmation')),
    trade_date date not null,
    symbol text not null,
    decision_ts timestamptz not null,
    previous_close double precision not null,
    exact_signal_trade_ts timestamptz,
    exact_signal_price double precision,
    exact_return_pct double precision,
    signal_trade_age_seconds integer,
    qualifies boolean not null default false,
    selected boolean not null default false,
    selected_rank integer,
    quality_flags jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique(run_id,phase,trade_date,symbol)
);
create index if not exists signal_triggers_daily_idx on signal_triggers(run_id,phase,trade_date,qualifies,exact_return_pct desc);

create table if not exists execution_targets (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null check (phase in ('primary','confirmation')),
    trade_date date not null,
    symbol text not null,
    cohort text not null check (cohort in ('signal','common_stock_signal','expanded_signal','liquidity_matched','random','smoke_probe')),
    source_trigger_id uuid references signal_triggers(id) on delete cascade,
    decision_ts timestamptz not null,
    session_close timestamptz not null,
    next_session_open timestamptz,
    previous_close double precision not null,
    decision_price double precision,
    prior_minute_dollar_volume double precision,
    common_stock_sensitivity boolean not null default false,
    match_score double precision,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique(run_id,phase,trade_date,symbol,cohort,source_trigger_id)
);
create index if not exists execution_targets_run_idx on execution_targets(run_id,phase,trade_date,cohort);

create table if not exists work_partitions (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null check (phase in ('primary','confirmation')),
    stage text not null,
    partition_key text not null,
    priority integer not null default 100,
    status text not null default 'queued' check (status in ('queued','running','completed','failed','cancelled')),
    params jsonb not null default '{}'::jsonb,
    cursor jsonb not null default '{}'::jsonb,
    attempts integer not null default 0,
    max_attempts integer not null default 8,
    worker_id text,
    heartbeat_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    next_attempt_at timestamptz,
    last_error text,
    row_count bigint not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(run_id,phase,stage,partition_key)
);
create index if not exists work_partitions_claim_idx on work_partitions(status,next_attempt_at,priority,created_at);
create index if not exists work_partitions_run_stage_idx on work_partitions(run_id,phase,stage,status);

create table if not exists raw_objects (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null,
    execution_target_id uuid not null references execution_targets(id) on delete cascade,
    data_type text not null check (data_type in ('trades','quotes')),
    page_index integer not null,
    start_ts timestamptz not null,
    end_ts timestamptz not null,
    object_path text not null unique,
    row_count bigint not null,
    size_bytes bigint not null,
    sha256 text not null,
    source_feed text not null default 'sip',
    created_at timestamptz not null default now(),
    unique(execution_target_id,data_type,page_index)
);

create table if not exists trade_results (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null,
    execution_target_id uuid not null references execution_targets(id) on delete cascade,
    scenario text not null check (scenario in ('optimistic','base','conservative')),
    cohort text not null,
    trade_date date not null,
    symbol text not null,
    fill_status text not null,
    requested_notional double precision not null,
    shares double precision,
    entry_ts timestamptz,
    entry_ask double precision,
    entry_price double precision,
    entry_spread_bps double precision,
    entry_slippage_bps double precision,
    exit_reason text,
    exit_ts timestamptz,
    exit_bid double precision,
    exit_price double precision,
    exit_spread_bps double precision,
    exit_slippage_bps double precision,
    gross_pnl double precision,
    fees double precision,
    net_pnl double precision,
    net_return_pct double precision,
    maximum_adverse_excursion_pct double precision,
    maximum_favourable_excursion_pct double precision,
    target_hit boolean,
    stop_triggered boolean,
    forced_overnight boolean not null default false,
    unresolved boolean not null default false,
    common_stock_sensitivity boolean not null default false,
    quality_flags jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique(execution_target_id,scenario)
);
create index if not exists trade_results_summary_idx on trade_results(run_id,phase,cohort,scenario);

create table if not exists phase_reports (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null check (phase in ('primary','confirmation')),
    status text not null,
    classification text,
    gate_passed boolean,
    metrics jsonb not null default '{}'::jsonb,
    data_quality jsonb not null default '{}'::jsonb,
    report_object_path text,
    protocol_hash text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(run_id,phase)
);

alter table research_runs enable row level security;
alter table instruments enable row level security;
alter table market_sessions enable row level security;
alter table corporate_actions enable row level security;
alter table daily_bars enable row level security;
alter table decision_snapshots enable row level security;
alter table signal_triggers enable row level security;
alter table execution_targets enable row level security;
alter table work_partitions enable row level security;
alter table raw_objects enable row level security;
alter table trade_results enable row level security;
alter table phase_reports enable row level security;
