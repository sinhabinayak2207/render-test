from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import current_user, login, signup

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str


@router.post("/login")
def login_route(body: Credentials):
    return login(body.email, body.password)


@router.post("/signup")
def signup_route(body: Credentials):
    return signup(body.email, body.password)


@router.get("/me")
def me_route(user=Depends(current_user)):
    return {"id": user.id, "email": user.email}
