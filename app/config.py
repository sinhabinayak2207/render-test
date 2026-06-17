"""Centralized settings loaded from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str

    # TenderKart
    tenderkart_api_key: str = ""
    tenderkart_base_url: str = "https://tenderkart.in/api/v1/client"

    # Anthropic — Bid Scope keyword generation (ONCE) + narrative/report content
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # OpenAI — gpt-4o-mini field-level extraction fallback (only fields regex missed)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_chat_model: str = "gpt-5-mini"   # chat agent (orchestration) model
    enable_vision_fallback: bool = True   # gpt-4o-mini vision OCR when text extraction is empty

    # Pipeline
    sync_updated_after: str = "2026-06-09T00:00:00Z"
    request_delay_seconds: float = 2.5
    max_retries: int = 4
    ocr_lang: str = "en"
    enable_ocr: bool = False   # master switch: OCR scanned pages (PaddleOCR / gpt-4o-mini vision).
    #                            Off by default — rely on selectable text (HTML/digital PDF).
    pdf_text_min_chars_per_page: int = 80   # below this => treat page as scanned
    extract_text_limit: int = 60000         # chars of doc text sent to gpt-4o-mini (was 30k)
    ocr_min_confidence: float = 0.55        # below this => vision fallback
    max_tenders_per_run: int = 1000

    # Storage
    storage_bucket: str = "tender-documents"
    upload_documents: bool = True

    # Re-process tenders already in the DB (refresh fields/OCR) instead of skipping
    reprocess_existing: bool = False

    # CORS
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
