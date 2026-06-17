"""Supabase client factories.

- service_client(): server-side, uses the secret key, BYPASSES RLS. Used for all
  pipeline writes (tenders, documents, cycle_events, runs).
- new_auth_client(): a FRESH anon client per auth call. Auth ops mutate the
  client's stored session, so a stateless server must not share one instance.
"""
from functools import lru_cache

from supabase import Client, create_client

from .config import settings

try:  # bound network timeouts so a slow Storage upload can't hang the whole run
    from supabase import ClientOptions

    _SVC_OPTS = ClientOptions(postgrest_client_timeout=60, storage_client_timeout=60)
except Exception:  # noqa: BLE001 — older/newer client without this export
    _SVC_OPTS = None


@lru_cache(maxsize=1)
def service_client() -> Client:
    if _SVC_OPTS is not None:
        return create_client(settings.supabase_url, settings.supabase_service_key, options=_SVC_OPTS)
    return create_client(settings.supabase_url, settings.supabase_service_key)


def new_auth_client() -> Client:
    # Intentionally NOT cached — see module docstring.
    return create_client(settings.supabase_url, settings.supabase_anon_key)
