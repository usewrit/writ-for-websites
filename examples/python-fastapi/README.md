# Python (FastAPI) example

A FastAPI server with `usewrit` 0.1.0 and a page that loads `@usewrit/web` 0.2.0 from jsDelivr.
It shows the three things a server does with the Writ Bridge:

| Route | What it shows |
|---|---|
| `GET` / `POST /writ-bridge` | The page channel: `writ.fastapi_router("/writ-bridge")`. |
| `GET /api/session` | `writ.user_token(user_id)`: the token the page passes to `createWritBridge`. |
| `POST /api/receive` | A server call that runs on the user's computer: `await writ.user(user_id).pos.receive(...)`. The bridge verifies the receipt before it returns. |
| `POST /api/lookup/challenge` and `POST /api/lookup/verify` | A page call the server can trust: `writ.challenge(subject, key)` before, `await writ.verify(receipt, challenge=..., key=..., subject=..., origin=..., data=..., inputs=...)` after. |

**Demo only:** there is no sign-in. Every visitor is the same demo user, and `/api/session` hands
its token to anyone. Replace it with your own authentication. Before a receipt gates a sign-in,
read [docs/security.md](../../docs/security.md).

## Run it

You need Python 3.10 or later, Writ desktop 1.0.8 or later, and the Writ extension in Chrome or
Edge.

1. **Add a contract.** Put your own `writ-contract.json` (exported from Writ desktop with **Add to
   your website**, or with `writ package export`) next to `app.py`. The code calls the keys
   `pos.receive` and `pos.lookup` and the setting `pos_host`; rename them in `app.py` and
   `static/index.html` to match your contract.

   To see the shape first, copy the example contract. It describes a fictional POS, so the
   install and consent work but the runs themselves fail:

   ```bash
   cp ../writ-contract.example.json writ-contract.json
   ```

2. **Install and start:**

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   export WRIT_BRIDGE_SECRET="$(openssl rand -base64 48)"
   .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
   ```

   Run a single worker: the default store is in memory. With several workers, pass
   `store=RedisStore(...)` (install `usewrit[redis]`). `WRIT_ORIGIN` sets the origin receipts must
   come from; it defaults to `http://127.0.0.1:8000` (set `PORT` if you change the port).

3. **Turn on Developer mode** in the Writ extension's options, so `http://127.0.0.1` pages may
   connect.

4. **Open <http://127.0.0.1:8000>**, typed exactly so. `http://localhost:8000` is another origin,
   and its receipts fail the `origin` check.

## What happens

1. The Writ banner walks you through what is missing, then "Install Northwind POS (one click)"
   opens Writ's consent window. Type the POS password and address, then **Install and allow**.
2. **Look up** asks the server for a challenge, runs `pos.lookup` on your computer with it, and
   sends the data and the receipt to the server, which answers `ok: true` with the signing
   device's `kid`, or the reason it refused.
3. **Receive** asks the server to run `pos.receive`. The server queues it for your user, this page
   picks it up from `/writ-bridge`, Writ asks you to confirm the change, and the result comes back
   to the server with its receipt.

The first device that answers is pinned to the demo user (`pin_devices="first-use"`, in memory).
Another computer gets `RESULT_UNVERIFIED` until you call `await writ.approve_device(...)`, and a
server restart forgets the pin.
