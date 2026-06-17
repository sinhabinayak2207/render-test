-- ============================================================================
-- CS Direkt — Settings expansion (FINAL). Idempotent — run this one file in the
-- Supabase SQL editor. Adds every column the new Settings page + RULES + report
-- need. Safe to re-run (add column if not exists).
-- ============================================================================

-- ── company_profiles ─────────────────────────────────────────────────────────
alter table public.company_profiles
  -- financial eligibility (Bid Scope & Eligibility)
  add column if not exists turnover_last_year_cr  numeric,   -- turnover, latest FY
  add column if not exists turnover_3yr_avg_cr     numeric,  -- turnover, 3-yr avg  (capacity GATE)
  add column if not exists net_worth_3yr_avg_cr    numeric,  -- net worth, 3-yr avg
  add column if not exists bank_solvency_cr         numeric, -- bank solvency certificate
  -- scoring + margins
  add column if not exists partial_margin_pct       numeric default 5,   -- global default margin (fallback)
  add column if not exists partial_margins          jsonb default '{}',  -- PER-FIELD margin %: {"turnover_3yr_avg_cr":5,"net_worth_latest_cr":10,...}
  -- others (free NL guidance fed to Claude during analysis)
  add column if not exists analysis_instructions     text,
  -- legal — a LIST of plain-text items (jsonb array of strings; no extra table)
  add column if not exists legal_items               jsonb default '[]';

-- auto_reject_risks: now free-text English (fed to Claude). Convert text[] -> text if needed.
do $$
begin
  if exists (select 1 from information_schema.columns
             where table_name = 'company_profiles' and column_name = 'auto_reject_risks'
               and data_type = 'ARRAY') then
    alter table public.company_profiles
      alter column auto_reject_risks type text using array_to_string(auto_reject_risks, ', ');
  else
    alter table public.company_profiles add column if not exists auto_reject_risks text;
  end if;
end $$;

-- ── company_portfolio (similar past work) ────────────────────────────────────
alter table public.company_portfolio
  add column if not exists description            text,
  add column if not exists completion_certificate text;

-- ── seed CS Direkt defaults on the default (user_id IS NULL) profile ─────────
update public.company_profiles set
  turnover_last_year_cr = coalesce(turnover_last_year_cr, 104.27),
  turnover_3yr_avg_cr   = coalesce(turnover_3yr_avg_cr,   103.79),
  net_worth_3yr_avg_cr  = coalesce(net_worth_3yr_avg_cr,   29.66),
  bank_solvency_cr      = coalesce(bank_solvency_cr,       30.65),
  partial_margin_pct    = coalesce(partial_margin_pct,      5),
  partial_margins       = coalesce(nullif(partial_margins, '{}'::jsonb),
                                   '{"turnover_3yr_avg_cr":5,"net_worth_latest_cr":5}'::jsonb)
where user_id is null;
