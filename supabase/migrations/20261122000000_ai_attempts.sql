-- Phase 5G: AI retry + fallback. Every attempt is stored; readers still show only the latest valid row.
alter table ai_outputs
  add column attempt     smallint not null default 1,      -- 1 primary, 2 retry with the reason appended, 3 fallback model
  add column is_fallback boolean  not null default false;

alter table ai_task_runs
  add column retried   integer not null default 0,         -- subjects that needed more than one call
  add column fallbacks integer not null default 0;         -- subjects that reached the fallback model
