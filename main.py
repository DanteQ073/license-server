from datetime import datetime, timezone
import sqlite3

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="License Server")

DB_PATH = "licenses.db"


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


@app.get("/")
def root():
    return {"ok": True, "message": "license server is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/activate")
def activate(payload: ActivateRequest):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT device_id FROM licenses WHERE license_key = ?",
            (payload.license_key,),
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO licenses (license_key, device_id, activated_at) VALUES (?, ?, ?)",
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
            "SELECT device_id FROM licenses WHERE license_key = ?",
            (payload.license_key,),
        ).fetchone()

    if row is None:
        return {"ok": False, "status": "not_found"}

    if row[0] != payload.device_id:
        return {"ok": False, "status": "device_mismatch"}

    return {"ok": True, "status": "active"}
