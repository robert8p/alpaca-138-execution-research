-- v1.1.0: pre-registered quarterly tranches, cumulative interim reports and futility stopping.


-- A staged v1.1.0 protocol is a new pre-registration. Preserve older runs, but
-- permit one full run for each immutable protocol hash.
drop index if exists one_full_research_run;
create unique index if not exists one_full_research_run
    on research_runs(run_kind,protocol_hash) where run_kind='full';

alter table research_runs
    add column if not exists current_tranche_key text,
    add column if not exists completed_primary_tranches integer not null default 0,
    add column if not exists early_futility_stopped boolean not null default false,
    add column if not exists early_futility_reason jsonb;

alter table research_runs drop constraint if exists research_runs_status_check;
alter table research_runs add constraint research_runs_status_check check (status in (
    'created','running','quarter_complete','primary_complete','confirmation_locked','confirmation_running',
    'completed','early_futility_stopped','failed','cancelled'
));

create table if not exists research_tranches (
    id uuid primary key default gen_random_uuid(),
    run_id uuid not null references research_runs(id) on delete cascade,
    phase text not null check (phase in ('primary','confirmation')),
    tranche_key text not null,
    sequence_no integer not null,
    label text not null,
    start_date date not null,
    end_date date not null,
    status text not null default 'locked' check (status in (
        'locked','running','completed','futility_stopped','cancelled','failed'
    )),
    standalone_report_object_path text,
    cumulative_report_object_path text,
    standalone_metrics jsonb not null default '{}'::jsonb,
    cumulative_metrics jsonb not null default '{}'::jsonb,
    futility_assessment jsonb not null default '{}'::jsonb,
    protocol_hash text not null,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique(run_id,phase,tranche_key),
    unique(run_id,phase,sequence_no),
    check (end_date >= start_date)
);
create index if not exists research_tranches_run_status_idx
    on research_tranches(run_id,phase,status,sequence_no);

alter table research_tranches enable row level security;
