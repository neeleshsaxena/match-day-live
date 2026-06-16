from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

PW_FILE = Path(__file__).resolve().parent.parent / ".admin_password"
ADMIN_USER = "admin"


def _resolve_password() -> str:
    env_pw = os.environ.get("ADMIN_PASSWORD")
    if env_pw:
        return env_pw
    if PW_FILE.exists():
        return PW_FILE.read_text().strip()
    pw = secrets.token_urlsafe(8)
    PW_FILE.write_text(pw)
    try:
        PW_FILE.chmod(0o600)
    except OSError:
        pass
    print(
        f"\n  >> Generated admin credentials: {ADMIN_USER} / {pw}\n"
        f"  >> Saved to {PW_FILE}. Override via ADMIN_PASSWORD env var.\n",
        file=sys.stderr,
        flush=True,
    )
    return pw


ADMIN_PASSWORD = _resolve_password()
_security = HTTPBasic()


def admin_required(creds: HTTPBasicCredentials = Depends(_security)) -> str:
    user_ok = secrets.compare_digest(creds.username.encode(), ADMIN_USER.encode())
    pass_ok = secrets.compare_digest(creds.password.encode(), ADMIN_PASSWORD.encode())
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": 'Basic realm="match-day-live admin"'},
        )
    return creds.username
