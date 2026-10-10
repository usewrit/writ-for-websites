"""Writ Bridge example: a FastAPI server that

- hosts the page channel (/writ-bridge), so this server can run functions on the user's computer;
- runs pos.receive on the user's computer, through their open page (POST /api/receive);
- verifies the receipt of a call the page made itself (POST /api/lookup/*).

DEMO ONLY: there is no sign-in. Every visitor is the same demo user, and /api/session hands its
token to anyone who asks. Replace DEMO_USER and /api/session with your own authentication before
you use any of this. See docs/security.md before a receipt gates a sign-in.

Run: uvicorn app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from usewrit import WritBridgeError, create_writ_bridge

HERE = Path(__file__).resolve().parent
CONTRACT = HERE / "writ-contract.json"
PORT = int(os.environ.get("PORT", "8000"))
# The exact origin the page is served from: receipts made on any other origin are refused.
ORIGIN = os.environ.get("WRIT_ORIGIN", f"http://127.0.0.1:{PORT}")
DEMO_USER = "demo-user"
CHALLENGE_TTL_SECONDS = 120

# Reads WRIT_BRIDGE_SECRET (at least 32 bytes) from the environment. "required": functions run
# only on the user's computer, and nothing goes to Writ Cloud.
writ = create_writ_bridge(CONTRACT, mode="required")

app = FastAPI()

# The page channel, at /writ-bridge on this origin.
app.include_router(writ.fastapi_router("/writ-bridge"))


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(HERE / "static" / "index.html")


@app.get("/writ-contract.json", include_in_schema=False)
async def contract_file() -> FileResponse:
    return FileResponse(CONTRACT, media_type="application/json")


@app.get("/api/session")
async def session() -> JSONResponse:
    """The token the page passes to its bridge. DEMO: no sign-in; mint it only for the signed-in user."""
    return JSONResponse({"writToken": writ.user_token(DEMO_USER)}, headers={"Cache-Control": "no-store"})


class ReceiveBody(BaseModel):
    invoice_no: str


@app.post("/api/receive")
async def receive(body: ReceiveBody) -> JSONResponse:
    """A server call that runs on the user's computer, through their open page. The bridge
    verifies the receipt before the await returns."""
    try:
        result = await writ.user(DEMO_USER).pos.receive({"invoice_no": body.invoice_no}, wait_for_user_ms=10_000)
    except WritBridgeError as error:
        # USER_OFFLINE, WRIT_REQUIRED, NOT_GRANTED, RESULT_UNVERIFIED, CONSENT_DENIED, RUN_FAILED, ...
        return JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=409)
    return JSONResponse({"venue": result.venue, "data": result.data})


# challenge -> (expires at, the inputs this server expects). DEMO: in memory, one process; use
# your session store.
pending: dict[str, tuple[float, dict[str, Any]]] = {}


class ChallengeBody(BaseModel):
    sku: str = ""


@app.post("/api/lookup/challenge")
async def lookup_challenge(body: ChallengeBody) -> dict[str, str]:
    now = time.monotonic()
    for stale in [key for key, (expires, _) in pending.items() if expires < now]:
        del pending[stale]
    challenge = writ.challenge(DEMO_USER, "pos.lookup", ttl_seconds=CHALLENGE_TTL_SECONDS)
    pending[challenge] = (now + CHALLENGE_TTL_SECONDS, {"sku": body.sku})
    return {"challenge": challenge}


class VerifyBody(BaseModel):
    challenge: str
    data: Any = None
    receipt: Any = None


@app.post("/api/lookup/verify")
async def lookup_verify(body: VerifyBody) -> JSONResponse:
    entry = pending.pop(body.challenge, None)
    if entry is None:
        return JSONResponse({"ok": False, "reason": "unknown or expired challenge"}, status_code=400)
    check = await writ.verify(
        body.receipt,
        challenge=body.challenge,
        key="pos.lookup",
        subject=DEMO_USER,
        origin=ORIGIN,
        data=body.data,
        inputs=entry[1],  # the call must have run with exactly what this server expected
    )
    if not check.ok:
        return JSONResponse(
            {"ok": False, "reason": check.reason, "unknownDevice": check.unknown_device},
            status_code=403,
        )
    return JSONResponse({"ok": True, "device": (check.device or {}).get("kid"), "data": body.data})
