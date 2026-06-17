-- Tender Agent — add the report-complete columns to the existing `tenders` table.
-- Safe & idempotent (ADD COLUMN IF NOT EXISTS). Run in the Supabase SQL editor.
-- Existing columns are kept; verdict/score/risk already exist from the legacy schema.

alter table public.tenders
  -- TK / EXTRACT factual fields
  add column if not exists issuing_authority_location text,
  add column if not exists min_turnover_cr            numeric,
  add column if not exists min_networth_cr            numeric,
  add column if not exists tender_mode                text,
  add column if not exists location_of_execution      text,
  add column if not exists project_duration           text,
  add column if not exists key_deliverables           jsonb,
  add column if not exists unusual_clauses            jsonb,
  add column if not exists penalty_clauses            jsonb,
  add column if not exists sow_page_refs              text,
  -- RULES layer (filled later by the deterministic qualifier)
  add column if not exists urgency                    text,
  add column if not exists reasons_qualified          jsonb,
  add column if not exists reasons_rejected           jsonb,
  add column if not exists eligibility_check          jsonb,
  add column if not exists excluded_reason            text,
  -- NARRATE layer (filled later by Claude)
  add column if not exists narrative_fit              text,
  add column if not exists key_business_insight       text,
  add column if not exists pre_bid_queries            jsonb,
  add column if not exists strategic_fit_basis        text,
  add column if not exists compliance_basis           text,
  add column if not exists risk_layperson_explanation text,
  add column if not exists disqualification_triggers  jsonb,
  add column if not exists business_logic_explanation text;
