"""Login and the current user (E14-01)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth
from app.api.deps import client_ip, current_user
from app.db import get_db
from app.models import User
from app.schemas import UserOut
from app.services import audit

public = APIRouter(tags=["session"])
router = APIRouter(tags=["session"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class LoginOut(BaseModel):
    token: str
    user: UserOut


@public.post("/api/auth/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    name = body.username.strip().lower()
    wait = auth.locked(name)
    if wait:
        raise HTTPException(429, f"too many failed attempts — try again in {int(wait) + 1}s")
    user = db.scalar(select(User).where(User.username == name))
    if user is None or not user.active or not auth.verify_password(body.password, user.password_hash):
        auth.record_failure(name)
        # Same message whether the user exists or not.
        raise HTTPException(401, "wrong username or password")
    auth.record_success(name)
    audit.log(db, "login", user_id=user.id, ip=client_ip(request), target_type="user", target_id=user.id)
    db.commit()
    return LoginOut(token=auth.issue_token(user.id, user.role), user=user)


@router.get("/api/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.get("/api/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role not in ("CA", "AUDITOR"):
        return [user]
    return list(db.scalars(select(User).order_by(User.id)))
