# Supabase tables used by the Tender Agent pipeline

Source of truth = the project's **existing** tables (the pipeline writes into them with
the service key). "Filled by" shows where each value comes from.

Legend: **TK** = direct from TenderKart API · **Groq** = LLM analysis of the document text ·
**Py** = computed by the Python pipeline · **auto** = DB default · **(legacy)** = column from
the old backend, not written by this pipeline.

---

## `tenders`  (36 columns)

| Column | Type | Filled by | Notes |
|---|---|---|---|
| id | uuid (PK) | auto | |
| run_id | uuid | Py | current `tender_runs.id` |
| portal_id | uuid (FK→portals) | — | left null (TenderKart isn't a portal row) |
| portal_name | text **(required)** | TK | `portal_name` |
| title | text **(required)** | TK | `title` |
| reference_number | text | TK | `tender_reference_number` |
| issuing_authority | text | TK | `organisation` |
| authority_contact | text | Groq | from document text |
| estimated_value | numeric | TK | `tender_value` |
| emd_amount | numeric | TK | `emd_fee` |
| emd_currency | text | Py | `"INR"` |
| pbg_percent | numeric | Groq | performance-bank-guarantee % |
| pre_bid_date | date | Groq | from docs |
| opening_date | date | Groq | bid/technical opening |
| closing_date | date | TK | `closing_at` (date part) |
| tender_type | text | TK | `tender_type` |
| scope_summary | text | Groq | 2–4 sentence scope |
| eligibility_conditions | jsonb | Groq | list of requirements |
| source_url | text **(required)** | Py | `tenderkart://{portal}/{tender_id}` |
| content_hash | text **(required)** | Py | sha256(tender + docs) — dedupe/cache |
| raw_text | text | Py | combined extracted text of all docs |
| verdict | text | Groq | ELIGIBLE / PARTIAL / INELIGIBLE / EXCLUDED / PENDING |
| competitiveness_score | numeric | Groq | 0–100 |
| score_breakdown | jsonb | Groq | {scope_fit, financial, eligibility, timeline} |
| matched_hashtags | text[] | Groq | |
| matched_categories | text[] | Groq/TK | falls back to TK category/product_category |
| gaps_to_address | jsonb | Groq | |
| suggested_actions | jsonb | Groq | |
| risk_level | text | Groq | LOW / MEDIUM / HIGH (CHECK-constrained) |
| downloaded_docs | jsonb | Py | [{doc_id, name, document_type, format, ocr_used, pages, storage_url}] |
| matched_keyword | text | Py | matched filter name |
| matched_bucket | text | Py | matched filter name |
| source_zip_url | text | — | (legacy) unused |
| created_at | timestamptz | auto | |
| **extracted_data** | jsonb | Groq+Py | **all PDF fields w/ page source** — see below |
| tenderkart_id | text | TK | TenderKart tender UUID — **dedupe key** |

### `extracted_data` JSON shape
```json
{
  "all_fields": [
    {"label": "EMD Amount", "value": "2,50,000", "document": "NIT.pdf", "page": 2}
  ],
  "key_dates": [
    {"label": "Bid Submission End", "value": "2026-07-06", "document": "details.html", "page": 1}
  ],
  "tenderkart": { /* full raw TenderKart tender object */ }
}
```
Every extracted field carries its **source document + page number**.

---

## `tender_artifacts`  (one row per document)

| Column | Type | Filled by | Notes |
|---|---|---|---|
| id | uuid (PK) | auto | |
| tender_id | uuid (FK→tenders.id) | Py | |
| file_name | text **(required)** | TK | document name |
| file_type | text | Py | digital_pdf / scanned_pdf / html / xls / xlsx / doc / docx / json / image / vision |
| storage_url | text | Py | public URL of the uploaded file in Storage bucket `tender-documents` |
| extracted_text | text | Py | the document's extracted markdown/text |
| created_at | timestamptz | auto | |

---

## `tender_runs`

| Column | Type | Filled by | Notes |
|---|---|---|---|
| id | uuid (PK) | auto | |
| started_at | timestamptz | auto | |
| completed_at | timestamptz | Py | |
| status | text | Py | running / completed / failed / partial |
| sites_total | int | Py | number of filters scanned |
| sites_succeeded | int | Py | |
| sites_failed | int | Py | |
| tenders_found | int | Py | |
| tenders_qualified | int | Py | verdict ELIGIBLE/PARTIAL |
| triggered_by | text | Py | manual / scheduled / chat / test |

---

## `cycle_events`  (live chat narration — Realtime)

| Column | Type | Filled by | Notes |
|---|---|---|---|
| id | uuid (PK) | auto | |
| run_id | uuid | Py | |
| level | text | Py | info / success / warn / error |
| message | text **(required)** | Py | narration line shown in the chat |
| meta | jsonb | Py | optional (report links etc.) |
| created_at | timestamptz | auto | |

---

## Storage
- Bucket **`tender-documents`** (public) — original document files; URL stored in
  `tender_artifacts.storage_url` and `tenders.downloaded_docs[].storage_url`.

## Other existing (legacy) tables — not written by this pipeline
`admin_users`, `connectors`, `csd_portfolio`, `hashtag_buckets`, `interventions`,
`portal_credentials`, `portals`, `qualification_runs`, `tender_run_sites`, `tenderkart_sync_state`.
