-- Tender Agent — Phase 1 uses the project's EXISTING tables:
--   tenders, tender_artifacts, tender_runs, cycle_events
-- No migration is required — the pipeline writes into those tables as-is
-- (service key bypasses RLS). This file only ensures cycle_events exists on a
-- brand-new project; on your project it is a harmless no-op.

create extension if not exists pgcrypto;

create table if not exists public.cycle_events (
  id          uuid primary key default gen_random_uuid(),
  run_id      uuid,
  created_at  timestamptz not null default now(),
  level       text not null default 'info',
  message     text not null,
  meta        jsonb
);
alter table public.cycle_events enable row level security;
drop policy if exists "cycle_events read" on public.cycle_events;
create policy "cycle_events read" on public.cycle_events
  for select to anon, authenticated using (true);
do $$ begin
  alter publication supabase_realtime add table public.cycle_events;
exception when duplicate_object then null; end $$;
