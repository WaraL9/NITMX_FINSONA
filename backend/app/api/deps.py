"""Request context: who is acting (E14-01 minimal) and from where.

The UI's "Viewing as" picker sends X-User-Id. Full login arrives with E14-01; until then
the header is trusted, which is acceptable for a local demo only.
"""

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User


def current_user(x_user_id: int | None = Header(None), db: Session = Depends(get_db)) -> User:
    if x_user_id is not None:
        user = db.get(User, x_user_id)
        if user is None:
            raise HTTPException(401, "unknown user")
        return user
    user = db.scalar(select(User).where(User.role == "CA").order_by(User.id).limit(1))
    if user is None:
        raise HTTPException(401, "no users seeded")
    return user


def require_role(*roles: str):
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"requires role {' or '.join(roles)}")
        return user

    return check


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
