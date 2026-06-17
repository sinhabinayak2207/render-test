"""Supabase-backed auth: login/signup + a Bearer-token dependency.

The frontend stores the returned `access_token` in an httpOnly cookie and sends
it back as `Authorization: Bearer <token>` on every proxied call. We validate it
against Supabase on each request (stateless).
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .supabase_client import new_auth_client

_bearer = HTTPBearer(auto_error=True)


def login(email: str, password: str) -> dict:
    client = new_auth_client()
    try:
        res = client.auth.sign_in_with_password({"email": email, "password": password})
    except Exception:
        raise HTTPException(status_code=401, detail={"error": "invalid_credentials"})
    session = getattr(res, "session", None)
    if not session or not session.access_token:
        raise HTTPException(status_code=401, detail={"error": "invalid_credentials"})
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_in": session.expires_in,
        "token_type": "bearer",
        "user": {"id": res.user.id, "email": res.user.email} if res.user else None,
    }


def signup(email: str, password: str) -> dict:
    client = new_auth_client()
    try:
        res = client.auth.sign_up({"email": email, "password": password})
    except Exception as exc:  # surfaced as detail to the signup form
        raise HTTPException(status_code=400, detail={"error": "signup_failed", "detail": str(exc)})
    session = getattr(res, "session", None)
    if session and session.access_token:
        return {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token,
            "expires_in": session.expires_in,
            "token_type": "bearer",
            "user": {"id": res.user.id, "email": res.user.email} if res.user else None,
        }
    # No session => email confirmation is enabled on the project.
    return {"detail": "Account created. Email confirmation is required before sign in."}


def current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)):
    """FastAPI dependency: validates the bearer JWT and returns the Supabase user."""
    token = creds.credentials
    try:
        res = new_auth_client().auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    user = getattr(res, "user", None)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    return user
