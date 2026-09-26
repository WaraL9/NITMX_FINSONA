"""Login and the current user (E14-01)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth
from app.api.deps import client_ip, current_user, require_role
from app.db import get_db
from app.models import CreditPolicy, User
from app.schemas import PolicyIn, PolicyStateOut, PolicyVersionOut, UserOut
from app.services import audit
from app.services import policy as policy_svc

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


@router.get("/api/policy", response_model=PolicyStateOut)
def get_policy(db: Session = Depends(get_db)):
    names = {u.id: u.name for u in db.scalars(select(User))}
    rows = db.scalars(select(CreditPolicy).order_by(CreditPolicy.id.desc()).limit(20)).all()
    return PolicyStateOut(
        current=policy_svc.as_dict(policy_svc.current(db)),
        history=[PolicyVersionOut(id=r.id, min_dscr=str(r.min_dscr), target_dscr=str(r.target_dscr),
                                  max_dsr=str(r.max_dsr), trade_line_ratio=str(r.trade_line_ratio), reason=r.reason,
                                  updated_by=names.get(r.updated_by), updated_at=r.updated_at) for r in rows],
    )


@router.put("/api/policy", response_model=PolicyStateOut)
def put_policy(body: PolicyIn, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require_role("CA"))):
    values = {k: v for k, v in body.model_dump(exclude={"reason"}).items() if v is not None}
    try:
        policy_svc.update(db, values, user.id, body.reason, client_ip(request))
    except policy_svc.PolicyError as e:
        raise HTTPException(422, str(e)) from e
    return get_policy(db)


@router.get("/api/metrics")
def metrics() -> dict:
    """E15-05: latest evaluation run (python -m app.eval.run), dated and tied to a git commit."""
    import json

    from app.config import settings

    path = settings.data_dir / "eval" / "results.json"
    if not path.exists():
        raise HTTPException(404, "no evaluation run yet — run: python -m app.eval.run")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/api/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db), user: User = Depends(current_user)):
    if user.role not in ("CA", "AUDITOR"):
        return [user]
    return list(db.scalars(select(User).order_by(User.id)))


class DemoResetOut(BaseModel):
    mode: str  # "snapshot" (instant) | "reseed" (snapshot stale or missing)
    ms: int


@router.post("/api/demo/reset", response_model=DemoResetOut)
def demo_reset(db: Session = Depends(get_db), user: User = Depends(require_role("CA"))):
    """E16-01: restore the freshly-seeded demo in one click. Disabled outside demo mode."""
    from app import demo
    from app.config import settings

    if not settings.demo_mode:
        raise HTTPException(403, "demo reset is disabled (FINSONA_DEMO_MODE=false)")
    db.close()  # release this request's connection before the database is replaced
    return demo.reset()
