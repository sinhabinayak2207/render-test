-- Tender Agent — per-customer config (editable RULES + Bid Scope Profile).
-- Run in the Supabase SQL editor. One row per user (multi-tenant); the row with
-- user_id = NULL is the default profile the pipeline uses.

create extension if not exists pgcrypto;

create table if not exists public.company_profiles (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid unique,                 -- auth.users.id; NULL = default profile
  company_name        text default 'CS Direkt',

  -- Financial capacity (₹ crore) — editable "placeholders" for the RULES engine
  turnover_3yr_avg_cr numeric default 103.79,
  turnover_5yr_avg_cr numeric default 81.30,
  turnover_latest_cr  numeric default 104.27,
  net_worth_latest_cr numeric default 35.80,
  net_worth_avg_cr    numeric default 29.66,
  solvency_cert_cr    numeric default 30.65,

  -- Tender value bounds + thresholds (₹ crore / %)
  min_tender_value_cr numeric default 0.35,        -- ₹35 lakh floor (hard reject below)
  max_tender_value_cr numeric,                     -- NULL = no upper cap
  emd_threshold_cr    numeric default 0.25,
  pbg_threshold_pct   numeric default 10,

  -- Score cutoffs
  eligible_min_score  int default 65,
  partial_min_score   int default 40,

  -- Bid Scope Profile (how the company participates)
  scope_description   text,                        -- free text the user writes about their business
  service_lines       text[] default array['Museums','Exhibitions','MICE','Events','Light & Sound','Science Centres','Heritage','Tourism','Content'],
  scope_keywords      jsonb,                       -- {category: [phrases]} — Claude-refined; seeded below
  include_keywords    text[] default '{}',         -- extra in-scope keywords (Claude)
  exclude_keywords    text[] default '{}',         -- out-of-scope keywords (Claude)
  keywords_generated_at timestamptz,               -- when Claude last generated keywords

  created_at          timestamptz default now(),
  updated_at          timestamptz default now()
);

alter table public.company_profiles enable row level security;
drop policy if exists "company_profiles read"  on public.company_profiles;
drop policy if exists "company_profiles write" on public.company_profiles;
create policy "company_profiles read"  on public.company_profiles for select to anon, authenticated using (true);
create policy "company_profiles write" on public.company_profiles for all to authenticated using (true) with check (true);

-- Seed the default profile (user_id NULL) with CS Direkt scope keywords + exclusions.
insert into public.company_profiles (user_id, company_name, scope_description, scope_keywords, exclude_keywords)
select null,
  'CS Direkt',
  'Techno-creative agency: museums & interpretation centres, exhibitions & pavilions, MICE, events, son-et-lumiere / light & sound, projection mapping, science centres, heritage, tourism experiences, immersive AV & content.',
  '{
    "Museums": ["museum","gallery","interpretation centre","interpretation center","exhibit","diorama"],
    "Exhibitions": ["exhibition","expo","pavilion","trade fair","display"],
    "MICE": ["conference","convention","summit","seminar","mice"],
    "Events": ["event","ceremony","festival","celebration","inauguration"],
    "Light & Sound": ["light and sound","son et lumiere","sound and light","projection mapping","laser show"],
    "Science Centres": ["science centre","science center","planetarium","science city","innovation hub"],
    "Heritage": ["heritage","monument","conservation","restoration"],
    "Tourism": ["tourism","tourist","destination development","experience centre","visitor centre","visitor center"],
    "Content": ["audio visual","immersive","augmented reality","virtual reality","hologram","multimedia","documentary film"]
  }'::jsonb,
  array['road construction','civil construction','building construction','false ceiling','supply of material','material supply','passenger lift','boundary wall','manpower supply','housekeeping','security guard','pest control','furniture supply','ambulance','printer','laptop','cctv','firefighting']
where not exists (select 1 from public.company_profiles where user_id is null);
