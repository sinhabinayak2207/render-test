-- ============================================================================
-- CS Direkt master data — fills the default company profile + 27 portfolio rows.
-- Run ONCE in the Supabase SQL editor (idempotent). Assumes the settings columns
-- exist (run migration_settings_final.sql first if any are missing).
-- ============================================================================

-- 0) column safety (in case migration not yet run)
alter table public.company_profiles
  add column if not exists analysis_instructions text,
  add column if not exists partial_margins jsonb default '{}',
  add column if not exists legal_items jsonb default '[]',
  add column if not exists turnover_last_year_cr numeric,
  add column if not exists turnover_3yr_avg_cr numeric,
  add column if not exists net_worth_3yr_avg_cr numeric,
  add column if not exists bank_solvency_cr numeric;
do $$
begin
  if exists (select 1 from information_schema.columns
             where table_name='company_profiles' and column_name='auto_reject_risks' and data_type='ARRAY') then
    alter table public.company_profiles alter column auto_reject_risks type text using array_to_string(auto_reject_risks, ', ');
  else
    alter table public.company_profiles add column if not exists auto_reject_risks text;
  end if;
end $$;

-- 1) financials, thresholds, scope, keywords  (default row = user_id IS NULL)
update public.company_profiles set
  company_name          = 'CS Direkt',
  turnover_last_year_cr = 104.27,
  turnover_latest_cr    = 104.27,
  turnover_3yr_avg_cr   = 103.79,
  turnover_5yr_avg_cr   = 81.30,
  net_worth_latest_cr   = 35.80,
  net_worth_avg_cr      = 29.66,
  net_worth_3yr_avg_cr  = 29.66,
  bank_solvency_cr      = 30.65,
  solvency_cert_cr      = 30.65,
  min_tender_value_cr   = 0.35,
  max_tender_value_cr   = null,
  emd_threshold_cr      = 0.25,
  pbg_threshold_pct     = 10,
  eligible_min_score    = 65,
  partial_min_score     = 40,
  partial_margin_pct    = 5,
  partial_margins       = '{"turnover_3yr_avg_cr":5,"net_worth_latest_cr":5}'::jsonb,
  scope_keywords        = '{
    "Museums":        ["museum","gallery","interpretation centre","visitor centre","curation","archaeolog"],
    "Exhibitions":    ["exhibition","expo","pavilion","trade fair","interactive display","booth design"],
    "MICE":           ["summit","conference","investor meet","convention","mice"],
    "Events":         ["event management","festival","mela","road show","retail activation","concert","cultural event","awareness campaign","drone show"],
    "Light & Sound":  ["light and sound","son et lumiere","sound and light","laser show","projection mapping","holographic","facade light","av installation","audio visual","immersive dome","multimedia show","water screen","fountain show"],
    "Science Centres":["science centre","science center","planetarium","science gallery","science museum","ai lab"],
    "Heritage":       ["heritage","conservation","restoration","mandir","pilgrim","temple development"],
    "Tourism":        ["tourism","tourist attraction","theme park","experience centre","leisure infrastructure","spiritual tourism","eco tourism"],
    "Content":        ["content development","motion graphics","ar/vr","storytelling","film production","animation"]
  }'::jsonb,
  include_keywords      = array[
    '3d dome projection','ai exhibitions','ai expo','ai labs','ai summits','anniversary','archaeology museum work',
    'av installation','awareness campaign','celebration','command centre','concerts','conservation and restoration',
    'content development','cultural event','cultural exhibit','cultural experience centre','cultural tourism',
    'digital exhibitions','digital museum','digital spaces','drone shows','eco tourism','event management services',
    'event production','exhibition design','experience centers','experience design and build','experiential marketing',
    'expo design','facade lighting','festivals and mela','films and content creation','gallery design',
    'heritage site development','heritage theme park','holographic projection','immersive dome experience',
    'immersive technology','interactive ar/vr','interactive display','international summit','interpretation centre',
    'investor meet','kumbh mela','laser show','leisure infrastructure','mandir development','mice',
    'mobile science exhibitions','multimedia','multimedia show','museum curation','museum design','museum development',
    'museum execution','museum interior fit out','museum upgradations','pavilion design','pilgrimage infrastructure',
    'planetarium','projection mapping','public information center','religious tourism','restoration','retail activation',
    'road shows','science and aviation museum','science centres','science galleries','science museum','son et lumiere',
    'sound and light show','spiritual tourism','state events','story telling','temple tourism','theme park design',
    'tourism infrastructure','tourist attraction development','tourist attractions','trade fair booth','visitor center',
    'visitor experience','water screen','fountain show'
  ]::text[],
  exclude_keywords      = array[
    'only construction','only civil','civil work only','only supply of material','supply of material only',
    'construction of roads','construction of highway','road construction','highway construction','road & highway',
    'road and highway','false ceiling work','wooden flooring work','wall panelling only','lift installation',
    'passenger lift','civil construction','building construction','construction of building',
    'construction of museum building','civil work for museum'
  ]::text[],
  updated_at = now()
where user_id is null;

-- 2) portfolio — 27 reference projects (replace the default set)
delete from public.company_portfolio where user_id is null;
insert into public.company_portfolio (user_id, project_name, client, project_type, approx_value_cr, categories) values
 (null,'Jyotisar Museum, Kurukshetra','Haryana Tourism','Museum',100.0, array['Museums','Heritage']),
 (null,'Chamkaur Sahib Museum','Punjab Heritage Board','Museum',28.0, array['Museums','Heritage']),
 (null,'Valmik Museum, Amritsar','Punjab Heritage Board','Museum',26.0, array['Museums','Heritage']),
 (null,'Rashtrapati Bhawan Sound & Light','ITDC','Sound & Light Show',21.0, array['Light & Sound']),
 (null,'Indian Museum Kolkata Renovation','Indian Museum Kolkata','Museum',20.0, array['Museums','Heritage']),
 (null,'MPSTDC Mahakal, Ujjain (S&L + Water)','MP State Tourism','Sound & Light + Water',20.0, array['Light & Sound','Content']),
 (null,'550th Guru Nanak Birth Celebration','Punjab Heritage Board','Multi-discipline Event',19.0, array['Events','Content']),
 (null,'GAIL Experience Centre','GAIL India','Experience Centre / Projection Mapping',18.0, array['Tourism','Content']),
 (null,'Lachit Museum','Assam Govt','Museum',15.0, array['Museums','Heritage']),
 (null,'Kedarnath Parichay Museum','NCSM / DST','Museum / Interpretation Centre',15.0, array['Museums','Tourism']),
 (null,'World Food India','FICCI','Exhibition + Event',12.0, array['Exhibitions','MICE']),
 (null,'MPCST Planetarium, Ujjain','Ujjain Smart City','Planetarium / AV',8.0, array['Science Centres','Content']),
 (null,'PM Museum Sound & Light','Nehru Memorial Museum','Sound & Light Show',8.0, array['Museums','Light & Sound']),
 (null,'Suraj Kund Mela','Haryana Tourism','Event Festival',8.0, array['Events']),
 (null,'Dhordo Sound & Light Show','Gujarat Tourism','Sound & Light Show',7.0, array['Light & Sound']),
 (null,'Burhanpur Sound & Light Show','MP State Tourism','Sound & Light Show',5.0, array['Light & Sound']),
 (null,'Viraat Swaroop (Statue Mapping + S&L)','Haryana Tourism','Statue Mapping + S&L',5.0, array['Light & Sound']),
 (null,'Red Fort Projection Mapping','IGNCA','Projection Mapping',5.0, array['Content','Light & Sound']),
 (null,'NFDC Film Bazaar','NFDC Goa','Exhibition',5.0, array['Exhibitions']),
 (null,'Sanchi Light & Sound','MP State Tourism','Sound & Light Show',4.5, array['Light & Sound']),
 (null,'Leh Sound & Light Show','ITDC','Sound & Light Show',4.0, array['Light & Sound']),
 (null,'Ajmer Smart City Cultural AV','Ajmer Smart City','Sound & Light Show',4.0, array['Light & Sound']),
 (null,'Navratri Festival','Gujarat Tourism','Event Festival',3.5, array['Events']),
 (null,'Pachmarhi Sound & Light Show','MP State Tourism','Sound & Light Show',3.0, array['Light & Sound']),
 (null,'Rose Garden Light & Sound','MCC Chandigarh','Sound & Light Show',2.0, array['Light & Sound']),
 (null,'APIIC Pavilion (CII Summit)','CII','Exhibition Pavilion',0.80, array['Exhibitions','MICE']),
 (null,'GTB Kirtan Samagam','Punjab Heritage Board','Large Event / AV',0.30, array['Events']);
