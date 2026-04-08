import os
import sqlite3
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

app = FastAPI(title="License Server")

DB_PATH = "licenses.db"
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS licenses (
                license_key TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                activated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS issued_licenses (
                license_key TEXT PRIMARY KEY,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                expires_at TEXT
            )
            """
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO issued_licenses (license_key, is_active, created_at)
            VALUES (?, 1, ?)
            """,
            ("TEST-001", datetime.now(timezone.utc).isoformat()),
        )

        conn.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


class ActivateRequest(BaseModel):
    license_key: str
    device_id: str


class CheckRequest(BaseModel):
    license_key: str
    device_id: str


class IssueRequest(BaseModel):
    license_key: str
    expires_at: str | None = None


class DisableRequest(BaseModel):
    license_key: str


@app.get("/")
def root():
    return {"ok": True, "message": "license server is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/admin/issue")
def admin_issue(payload: IssueRequest, x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN is not configured")

    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid admin token")

    if payload.expires_at:
        try:
            expires_dt = datetime.fromisoformat(payload.expires_at)
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="expires_at must be valid ISO datetime")

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO issued_licenses
            (license_key, is_active, created_at, expires_at)
            VALUES (?, 1, ?, ?)
            """,
            (
                payload.license_key,
                datetime.now(timezone.utc).isoformat(),
                payload.expires_at,
            ),
        )
        conn.commit()

    return {"ok": True, "status": "issued", "license_key": payload.license_key}


@app.post("/admin/disable")
def admin_disable(payload: DisableRequest, x_admin_token: str | None = Header(default=None)):
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN is not configured")

    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="invalid admin token")

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE issued_licenses SET is_active = 0 WHERE license_key = ?",
            (payload.license_key,),
        )
        conn.commit()

    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="license key not found")

    return {"ok": True, "status": "disabled", "license_key": payload.license_key}


@app.post("/activate")
def activate(payload: ActivateRequest):
    with sqlite3.connect(DB_PATH) as conn:
        issued = conn.execute(
            """
            SELECT is_active, expires_at
            FROM issued_licenses
            WHERE license_key = ?
            """,
            (payload.license_key,),
        ).fetchone()

        if issued is None:
            raise HTTPException(status_code=403, detail="license key was not issued")

        is_active, expires_at = issued

        if is_active != 1:
            raise HTTPException(status_code=403, detail="license key is disabled")

        if expires_at:
            expires_dt = datetime.fromisoformat(expires_at)
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            if expires_dt < datetime.now(timezone.utc):
                raise HTTPException(status_code=403, detail="license key is expired")

        row = conn.execute(
            "SELECT device_id FROM licenses WHERE license_key = ?",
            (payload.license_key,),
        ).fetchone()

        if row is None:
            conn.execute(
                """
                INSERT INTO licenses (license_key, device_id, activated_at)
                VALUES (?, ?, ?)
                """,
                (
                    payload.license_key,
                    payload.device_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            return {"ok": True, "status": "activated"}

        if row[0] == payload.device_id:
            return {"ok": True, "status": "already_activated"}

        raise HTTPException(status_code=403, detail="license already activated on another device")


@app.post("/check")
def check(payload: CheckRequest):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT l.device_id, i.is_active, i.expires_at
            FROM licenses l
            LEFT JOIN issued_licenses i ON i.license_key = l.license_key
            WHERE l.license_key = ?
            """,
            (payload.license_key,),
        ).fetchone()

    if row is None:
        return {"ok": False, "status": "not_found"}

    device_id, is_active, expires_at = row

    if device_id != payload.device_id:
        return {"ok": False, "status": "device_mismatch"}

    if is_active != 1:
        return {"ok": False, "status": "disabled"}

    if expires_at:
        expires_dt = datetime.fromisoformat(expires_at)
        if expires_dt.tzinfo is None:
            expires_dt = expires_dt.replace(tzinfo=timezone.utc)
        if expires_dt < datetime.now(timezone.utc):
            return {"ok": False, "status": "expired"}

    return {"ok": True, "status": "active"}
