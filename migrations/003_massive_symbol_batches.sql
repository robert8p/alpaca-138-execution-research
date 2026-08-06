-- v1.1.2 operational repair: retire the catalogue-wide Massive partition.
-- The worker now creates resumable exact-symbol batches from instruments in each run.

update work_partitions
   set status='completed',
       worker_id=null,
       heartbeat_at=null,
       completed_at=coalesce(completed_at,now()),
       row_count=0,
       cursor='{"finished":true,"retired_legacy_all_tickers":true,"replacement":"v1.1.2_symbol_batches"}'::jsonb,
       last_error=coalesce(last_error,'') || E'\nRetired by v1.1.2 exact-symbol Massive lookup repair',
       updated_at=now()
 where stage='massive_reference'
   and partition_key='all-tickers';
