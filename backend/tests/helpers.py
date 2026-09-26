"""Signed session headers for the seeded demo users (ids follow app.seed.USERS order)."""

from app.auth import issue_token


def bearer(user_id: int, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(user_id, role)}"}


CA = bearer(1, "CA")
RM = bearer(2, "RM")
SME = bearer(3, "SME")
AUD = bearer(4, "AUDITOR")
