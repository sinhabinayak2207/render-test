-- Settings expansion — financials, legal, others (auto-reject risks + no-go locations),
-- and portfolio detail. Idempotent (add column if not exists). Run once in Supabase.

-- ── company_profiles: new columns ─────────────────────────────────────────────
alter table public.company_profiles
  add column if not exists turnover_last_year_cr numeric,   -- turnover, latest FY
  add column if not exists turnover_3yr_avg_cr   numeric,   -- turnover, 3-yr avg (capacity GATE)
  add column if not exists net_worth_3yr_avg_cr  numeric,   -- net worth, 3-yr avg
  add column if not exists bank_solvency_cr       numeric,  -- bank solvency certificate
  add column if not exists gst_number             text,
  add column if not exists pan_number             text,
  add column if not exists certifications         text[] default '{}',   -- ISO 9001 / EPF / ESIC …
  add column if not exists contractor_class       text,
  add column if not exists can_form_jv            boolean default true,
  add column if not exists auto_reject_risks      text[] default '{}',   -- risk phrase present -> REJECTED
  add column if not exists no_go_locations         text[] default '{}',  -- execution here -> EXCLUDED
  add column if not exists partial_margin_pct      numeric default 5,    -- global default margin (fallback)
  add column if not exists partial_margins         jsonb default '{}',   -- per-field margin %: {"turnover_3yr_avg_cr":5,"net_worth_latest_cr":10,...}
  add column if not exists legal_title              text,
  add column if not exists legal_description        text;

-- ── company_portfolio: new columns ───────────────────────────────────────────
alter table public.company_portfolio
  add column if not exists description           text,
  add column if not exists completion_certificate text;

-- ── seed CS Direkt defaults on the default (user_id IS NULL) profile row ──────
update public.company_profiles set
  turnover_last_year_cr = coalesce(turnover_last_year_cr, 104.27),
  turnover_3yr_avg_cr   = coalesce(turnover_3yr_avg_cr,   103.79),
  net_worth_3yr_avg_cr  = coalesce(net_worth_3yr_avg_cr,   29.66),
  bank_solvency_cr      = coalesce(bank_solvency_cr,       30.65),
  certifications        = coalesce(nullif(certifications, '{}'), array['GST','PAN','ISO 9001','EPF','ESIC']),
  can_form_jv           = coalesce(can_form_jv, true)
where user_id is null;
