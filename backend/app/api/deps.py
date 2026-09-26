"""Request context: who is acting and what they may touch (E14-01).

* `current_user`: requires a valid `Authorization: Bearer <token>`; no fallback user.
* `scope_guard`: router-level check on every protected route —
    - AUDITOR is read-only (GET only);
    - any case-scoped path parameter (case_id, document_id, txn_id, query_id,
      evidence_id) must belong to a case the user may see: SME only their own
      application, RM only cases assigned to them (or unassigned), CA/AUDITOR all.
"""

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app import auth
from app.db import get_db
from app.models import Case, Document, Evidence, Query, Transaction, User


def current_user(authorization: str | None = Header(None), db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "login required", headers={"WWW-Authenticate": "Bearer"})
    try:
        uid = auth.read_token(authorization.split(" ", 1)[1].strip())
    except auth.InvalidToken as e:
        raise HTTPException(401, f"invalid session: {e}", headers={"WWW-Authenticate": "Bearer"}) from e
    user = db.get(User, uid)
    if user is None or not user.active:
        raise HTTPException(401, "account disabled")
    return user


def require_role(*roles: str):
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"requires role {' or '.join(roles)}")
        return user

    return check


def can_view(case: Case, user: User) -> bool:
    if user.role in ("CA", "AUDITOR"):
        return True
    if user.role == "RM":
        return case.rm_user_id in (None, user.id)
    return case.owner_user_id == user.id


_PARAM_TO_CASE = {
    "document_id": (Document, "case_id"),
    "txn_id": (Transaction, "case_id"),
    "query_id": (Query, "case_id"),
    "evidence_id": (Evidence, "case_id"),
}


def scope_guard(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    if user.role == "AUDITOR" and request.method not in ("GET", "HEAD", "OPTIONS"):
        raise HTTPException(403, "auditors have read-only access")
    params = request.path_params
    case_ids: list[int] = []
    if "case_id" in params:
        case_ids.append(int(params["case_id"]))
    for name, (model, attr) in _PARAM_TO_CASE.items():
        if name in params:
            obj = db.get(model, int(params[name]))
            if obj is None:
                raise HTTPException(404, f"{name.removesuffix('_id')} not found")
            case_ids.append(getattr(obj, attr))
    for cid in case_ids:
        case = db.get(Case, cid)
        # Hide existence from users who may not see the case.
        if case is None or not can_view(case, user):
            raise HTTPException(404, "case not found")
    return user


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
