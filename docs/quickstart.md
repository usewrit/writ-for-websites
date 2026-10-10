# Quickstart: run your Writ workflows on your users' computers

Your website calls the workflows you built in Writ. They run on each user's own computer, through
the Writ browser extension and Writ desktop, and the results come back to your page and your
server:

- They use the user's network and IP address, devices on their local network, and credentials
  that never leave their machine.
- Nothing runs on your servers.
- In `required` mode, nothing goes through your Writ account either.

You write the same calls in the page and on the server. One setting, `mode`, decides whether Writ
on the user's computer is required, recommended, or not used.

Contents:

1. [What you need](#1-what-you-need)
2. [Build the workflow and export the contract](#2-build-the-workflow-and-export-the-contract)
3. [Install the SDKs](#3-install-the-sdks)
4. [Choose the mode](#4-choose-the-mode)
5. [The server: mount one route](#5-the-server-mount-one-route)
6. [The page: create the bridge](#6-the-page-create-the-bridge)
7. [Ask each user once for a value](#7-ask-each-user-once-for-a-value)
8. [Ship it linked](#8-ship-it-linked)
9. [Call from your server](#9-call-from-your-server)
10. [Gate a flow on a call the user's computer makes](#10-gate-a-flow-on-a-call-the-users-computer-makes)
11. [Several server instances](#11-several-server-instances)
12. [Test locally](#12-test-locally)
13. [Before you go live](#13-before-you-go-live)

## 1. What you need

- **Writ desktop 1.0.8 or later** on your computer, to build and export workflows:
  <https://usewrit.app/desktop>. Your users need it too.
- **The Writ extension** in Chrome or Edge (version 111 or later), from the
  [Chrome Web Store](https://chromewebstore.google.com/detail/writ/aphpglonnlgemfbgjopfkbdellmfljhg). Edge installs Chrome Web Store extensions after a one-time prompt.
- **A server** in Node 18+ or Python 3.10+, if you want to verify results or call functions from
  the server. A page alone can call functions, but cannot prove anything to anyone.
- **A Writ Cloud account** only for `recommended` and `cloud` modes, or for linked workflows.

## 2. Build the workflow and export the contract

1. Build and test the workflow in Writ (desktop app or Writ Cloud). Give each callable part a
   function name (`verify_login`, `receive`). Prove it on two different inputs before you ship
   it.
2. If it talks to a device on the local network, approve that address on the workflow (**Local
   network access**). If the address differs per user, make it a setting instead (section 7).
3. In Writ desktop, open **Connect**, then **Connected apps**, and in the **Websites** section
   choose **Add to your website**:
   - pick the workflows and functions;
   - give each a key (`auth.verify_login`, `pos.receive`). Dots make namespaces in the typed
     client;
   - tick **Ask each user once (setting)** on an input that differs per user, such as a POS
     address;
   - choose **Bundled** (the workflow ships in your contract) or **Linked** (it stays in your Writ
     Cloud, see section 8);
   - download **`writ-contract.json`** and **`writ-functions.d.ts`**, and read the warnings shown
     next to each package.

Or use the `writ` command line:

```bash
writ package export "POS receive" --function receive --key pos.receive --out writ-contract.json

# an input each user gives once, as a setting
writ package export "POS receive" --function receive --key pos.receive \
  --setting "pos_host:lan_host=Your POS address" --out writ-contract.json

# a credential your site passes with each call instead of each user typing it once
writ package export "Portal login" --function verify_login --key auth.verify_login \
  --call-credential password --out writ-contract.json
```

The contract carries the workflow, its inputs and outputs, and the addresses it reaches. It never
carries your session cookies or any secret: each `{{secret:KEY}}` becomes a declared credential
that each user types once, on their own computer. See [Shipping workflows](./packages.md) for
credentials, settings and private recipes.

Writ Cloud produces the same file: on a workflow, **Use on a website**.

## 3. Install the SDKs

```bash
npm install @usewrit/web            # your web app (page side)
npm install @usewrit/server         # Node backend
pip install "usewrit[fastapi]"      # Python backend (FastAPI, Starlette, any ASGI)
```

Without a bundler, load the script-tag build. It defines `window.WritWeb` and never touches
`window.writ`, which belongs to the extension:

```html
<script src="https://cdn.jsdelivr.net/npm/@usewrit/web@0.2.0/dist/writ-web.iife.js"></script>
```

## 4. Choose the mode

| `mode` | The user has Writ | The user doesn't |
|---|---|---|
| `required` | Runs on their computer | A banner walks them through installing Writ and your workflows; calls wait |
| `recommended` | Runs on their computer | A dismissible banner suggests Writ; calls run on Writ Cloud, in your account |
| `cloud` | Runs on Writ Cloud | Runs on Writ Cloud; no banner |

- `required` needs no Writ Cloud account, no API key and nothing published.
- `recommended` and `cloud` also need `WRIT_API_KEY` in your server's environment, and a contract
  downloaded from Writ Cloud, which maps each function to your cloud workflow.
- A function that reaches the user's local network is always `required`, because Writ Cloud can't
  reach it. That includes a function with a `lan_host` setting.
- A function can set its own `mode` in the contract. On the server, `functionModes` (Node) or
  `function_modes` (Python) overrides it.
- There is never an automatic fallback: a call that fails on the user's computer is not re-run on
  Writ Cloud.

## 5. The server: mount one route

The server bridge serves one route that your pages talk to (the page channel), mints user tokens
and challenges, and verifies receipts.

Node (Express):

```ts
import express from "express";
import { createWritBridge } from "@usewrit/server";
import contract from "./writ-contract.json" with { type: "json" };
import type { WritFunctions } from "./writ-functions";

export const writ = createWritBridge<WritFunctions>({ contract, mode: "required" }); // reads WRIT_BRIDGE_SECRET (+ WRIT_API_KEY)

const app = express();
app.all("/writ-bridge", writ.express()); // before express.json(), or on a path it skips

// when you render a signed-in page, hand the page a token for that user
app.get("/api/session", requireLogin, (req, res) => {
  res.json({ writToken: writ.userToken(req.user.id) });
});
```

Next.js (App Router):

```ts
// app/writ-bridge/route.ts
import { writ } from "@/lib/writ";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const { GET, POST } = writ.next();
```

`writ.handler` is a fetch-API handler, `(request: Request) => Promise<Response>`, for any other
framework that speaks `Request` and `Response`.

Python (FastAPI):

```python
from pathlib import Path

from fastapi import Depends, FastAPI
from usewrit import create_writ_bridge

writ = create_writ_bridge(Path("writ-contract.json"), mode="required")

app = FastAPI()
app.include_router(writ.fastapi_router("/writ-bridge"))


@app.get("/api/session")
async def session(user=Depends(current_user)):
    return {"writToken": writ.user_token(user.id)}
```

Starlette: `Route("/writ-bridge", writ.asgi, methods=["GET", "POST"])`. Anything else:
`await writ.handle(method, headers, query_string, body_bytes)`.

Set `WRIT_BRIDGE_SECRET` to at least 32 random bytes (`openssl rand -base64 48`). It signs user
tokens and challenges, and never leaves your server. The bridge refuses to start without it when
any function can run on a user's computer.

The route must be on the same origin as your page. The page bridge refuses any other endpoint.

## 6. The page: create the bridge

```ts
import { createWritBridge, isWritError } from "@usewrit/web";
import contract from "./writ-contract.json";
import type { WritFunctions } from "./writ-functions";

const writ = createWritBridge<WritFunctions>({
  contract,
  app: "Northwind Retail",   // shown in the banner and the consent window, at most 80 characters
  mode: "required",
  endpoint: "/writ-bridge",  // the default
  userToken,                 // optional: from /api/session; lets your server call this user's computer
});

try {
  const { data, venue, receipt } = await writ.pos.receive({ invoice_no: "F-1029" });
} catch (error) {
  if (isWritError(error, "CONSENT_DENIED")) showNotice("The delivery was not confirmed.");
  else throw error;
}
```

Each call resolves with `{ data, venue, receipt, runId, callId }`. `venue` is `"user"` or
`"cloud"`. `receipt` is the signed receipt when the call ran on the user's computer, and `null` on
Writ Cloud. The page never verifies a receipt: send it to your server.

Call options: `challenge`, `timeoutMs` (1 s to 15 min, default 2 min), `dryRun`, `signal` (an
`AbortSignal`), and for linked workflows `token` and `recipeCache`.

The bridge's own methods: `ready()`, `status()`, `venue(key)`, `suggestSettings(values)`,
`refreshRecipes()` and `destroy()`. A contract key may not start with one of those names.

What the user sees, automatically:

1. **No extension:** a banner at the top of the page with a button to the Chrome Web Store or
   Edge Add-ons, and "I installed it". Firefox, Safari and phones see a short note that Writ needs
   Chrome or Edge on a computer.
2. **No Writ desktop, or an old one:** "Get Writ desktop" or "Update Writ desktop".
3. **Writ not running:** "Open Writ on this computer, then retry". A connect or a call your page
   makes while Writ is stopped opens the extension's start window: **Start Writ for this site?**
   with **Start Writ** and **Not now**. Writ never starts without the user.
4. **First use:** "Install <your workflow> (one click)" opens Writ's consent window. It shows your
   site, what each function does, the addresses it reaches (local-network ones highlighted), a
   field per credential and per setting. The user clicks **Install and allow**.
5. **A function that changes data** asks the user to confirm each time, unless they chose
   otherwise when connecting.

`banner: false` turns the banner off. `banner: { container, position, locale }` places it
(`locale` is `"en"`, `"fr"` or `"es"`). In `required` mode the banner cannot be closed; in
`recommended` mode it can, and calls then run on Writ Cloud.

Lower level, if you want to drive the banner and the typed client yourself:

```ts
import { createWritClient, mountWritBanner } from "@usewrit/web";

mountWritBanner({
  app: "Northwind Retail",
  contract,
  onReady(session) {
    const client = createWritClient<WritFunctions>(session, contract);
    client.pos.receive({ invoice_no: "F-1029" }).result.then(({ data }) => showReceived(data));
  },
});
```

## 7. Ask each user once for a value

Some values differ per user but not per call, such as the address of each customer's POS on
their own network. Declare them as **settings** and use them in the workflow like any input:
`http://{{pos_host}}/api/receive`.

- **Desktop:** in **Add to your website**, tick **Ask each user once (setting)** on that input.
- **CLI:** `--setting "pos_host:lan_host=Your POS address"`.
- **Automatic:** an input that decides which address a request goes to always becomes a setting.

Ask in your own UI if you like, then hand Writ the answer:

```ts
const pos_host = await askUser("What is the address of your POS? (Settings > Network on the POS)");
await writ.suggestSettings({ "pos.receive": { pos_host } }); // or settings: {...} in createWritBridge
```

What happens next:

- **The user confirms.** Writ's own window opens pre-filled. The user checks the address and
  confirms; an address on their local network is highlighted.
- **Every run reuses it.** It is stored with the installed workflow on their computer, and every
  run uses it as `{{pos_host}}`. The address is approved for that workflow only.
- **Your page can't change it per call.** Passing `pos_host` as an input is refused with
  `INPUT_INVALID`. Suggest a new value with `suggestSettings` instead, and the user confirms the
  change in Writ's window. They can also edit it in Writ desktop (Connect, Connected apps,
  Websites).

A contract function lists its package's settings as `settings: { key, label, kind }[]`, so your
own form knows what to ask.

## 8. Ship it linked

Bundled (the default) ships the whole workflow in your contract file. **Linked** ships only what
it does (its manifest) and a link. Each user's Writ fetches the workflow from your Writ Cloud when
it runs, checks it against what the user approved, runs it from memory and keeps none of it.

What you get:

- edits that stay within what users approved (same hosts, credentials and functions) apply at the
  next run, with no new release;
- anything wider asks users for a one-click update;
- withdrawing it stops it everywhere at once.

How to publish:

- **Writ Cloud:** on a workflow, **Use on a website**. Pick the functions and your site's origins
  (`https://app.northwind.example`, plus `http://localhost:5173` for development), then Publish.
- **Writ desktop** (linked to your Writ Cloud account): in **Add to your website**, choose
  **Linked**, then **Publish to Writ Cloud**.

Download the linked contract and use it exactly like a bundled one; your page code doesn't
change.

**Token mode** (only your signed-in users get the workflow): choose Token when publishing. Then
mint a short-lived run token on your server and give the page a way to get it:

```ts
// server (Node)
import { mintRunToken } from "@usewrit/server";

app.get("/api/writ-token", requireLogin, (req, res) => {
  const token = mintRunToken(process.env.WRIT_PUBLICATION_SECRET, {
    publication: "pub_0123456789abcdefABCDEF", // your publication's id
    sub: req.user.id,                          // optional
    ttlSeconds: 600,                           // default 600, at most 3600
  });
  res.set("Cache-Control", "no-store").type("text/plain").send(token);
});

// page
createWritBridge({ contract, app: "Northwind Retail", mode: "required",
  getRunToken: () => fetch("/api/writ-token").then((r) => r.text()) });
```

Python: `mint_run_token(os.environ["WRIT_PUBLICATION_SECRET"], "pub_...", sub=str(user.id))`.

The secret key is the publication's `wsk_...` key, which Writ Cloud shows once. It is not
`WRIT_BRIDGE_SECRET`, and never the publishable `wpk_...` key.

**Recipe cache.**

- `recipeCache: "session"` (default) fetches once per page.
- `"call"` fetches for every call.
- `refreshRecipes()` drops the page's copy.

**What linked mode can't promise:** a user who controls their computer can still capture a recipe
it runs. Never put your own secrets in a workflow, in either mode.

## 9. Call from your server

```ts
const { data, venue } = await writ.user(user.id).pos.receive({ invoice_no }, { waitForUserMs: 10_000 });
```

```python
result = await writ.user(user.id).pos.receive({"invoice_no": invoice_no}, wait_for_user_ms=10_000)
```

- **The user has your site open and Writ ready:** the call runs on their computer
  (`venue: "user"`). It reaches their page through the page channel; the page must have been
  created with the `userToken` your server minted.
- **Otherwise, depending on `mode`:**
  - `required` → `USER_OFFLINE` (or `WRIT_REQUIRED` if they never had Writ ready, or
    `NOT_GRANTED`);
  - `recommended` / `cloud` → Writ Cloud (`venue: "cloud"`).

Every result from a user's computer carries a **signed receipt**, which the server bridge verifies
before returning. A result a script altered in the page is refused (`RESULT_UNVERIFIED`).

`await writ.online(user.id)` tells whether one of the user's pages is connected with Writ ready.
`writ.pos.lookup(inputs)` without a user runs on Writ Cloud in `recommended` / `cloud` mode and
fails with `WRIT_REQUIRED` in `required` mode.

## 10. Gate a flow on a call the user's computer makes

For example, a check the user's computer must make during a sign-in:

```ts
// server: after checking the password in your database
const challenge = writ.challenge({ subject: user.id, key: "auth.verify_login" }); // one-time, 2 minutes

// page
const inputs = { company, username };
const { data, receipt } = await writ.auth.verify_login(inputs, { challenge });
await fetch("/login/complete", { method: "POST", body: JSON.stringify({ data, receipt }) });

// server: check the receipt ran with what your form got (inputs), not another account's sign-in
const v = await writ.verify(receipt, {
  challenge,
  key: "auth.verify_login",
  subject: user.id,
  origin: "https://app.northwind.example",
  data,
  inputs: { company, username },   // the values YOUR form received, kept on the server
});
if (!v.ok || v.outcome !== "success") return deny(); // failed, error, timeout, cancelled, forged, or other inputs
```

Python:

```python
challenge = writ.challenge(user.id, "auth.verify_login", ttl_seconds=120)
v = await writ.verify(
    receipt,
    challenge=challenge,
    key="auth.verify_login",
    subject=user.id,
    origin="https://app.northwind.example",
    data=data,
    inputs={"company": company, "username": username},
)
if not v.ok:
    raise HTTPException(401, v.reason)
```

Pass `inputs` when the result says something about WHO: a receipt hashes what the call ran with,
salted with your challenge, so a page can't run the check with one account and claim another.

A failed run also returns a signed receipt (`outcome: "failed"`), so you can tell "it ran and
failed" from "it never ran". No receipt means deny. `verify()` never throws for a bad receipt; it
answers `{ ok, outcome, reason, device, unknownDevice }`.

**What a receipt proves:** this user's Writ ran your function for your site, with your challenge,
with these inputs, and returned exactly this data. Replays, console edits and results from a
computer other than the one pinned for the user are all rejected.

**Devices.** By default (`pinDevices: "first-use"`) the bridge pins the first Writ install that
answers for each user. Mint challenges only behind your own sign-in. If the receipt IS the
sign-in, or gates it, first use is not a trust root: enrol computers yourself.
[Security](./security.md) explains both cases with code.

## 11. Several server instances

The default store is in memory, for a single process, and forgets device pins on restart. In
production, or with several instances, share one Redis (6.2 or later):

```ts
import Redis from "ioredis";
import { createWritBridge, redisStore } from "@usewrit/server";

const redis = new Redis(process.env.REDIS_URL);
const sub = redis.duplicate();
const store = redisStore(redis, {
  subscribe: async (channel, onMessage) => {
    sub.on("message", (from, message) => { if (from === channel) onMessage(message); });
    await sub.subscribe(channel);
  },
});
export const writ = createWritBridge({ contract, mode: "required", store });
```

```python
import redis.asyncio as redis
from usewrit import RedisStore, create_writ_bridge

store = RedisStore(redis.from_url(os.environ["REDIS_URL"]))
writ = create_writ_bridge(Path("writ-contract.json"), mode="required", store=store)
```

Node and Python use the same key layout (`writ:bridge:`), so both can share one Redis.

## 12. Test locally

1. Run Writ desktop 1.0.8 or later, or start the engine with `writ start`.
2. Install the Writ extension from the Chrome Web Store or Edge Add-ons.
3. Open the extension's **Options** and turn on **Developer mode**. It lets pages on
   `http://localhost` and `http://127.0.0.1` (any port) ask to connect. Every connection still
   goes through the consent window. Production sites must use `https`.
4. Serve your page on `http://127.0.0.1:<port>` and open it at exactly that address.
   `http://localhost:<port>` is a different origin: a receipt made on one fails an `origin` check
   for the other, and a grant for one does not cover the other.
5. Use a `WRIT_BRIDGE_SECRET` for development only, and a separate one in production.

The [examples](../examples/) are set up this way.

To start over as a user would: in the extension's popup, **Disconnect** your site and choose
**Remove them** to delete the workflows it installed. Under `"first-use"` pinning, call
`writ.forgetDevices(userId)` (Python `forget_devices`) so the next computer pins anew.

## 13. Before you go live

- [ ] The page is served over `https` and calls from the top frame.
- [ ] `WRIT_BRIDGE_SECRET` is at least 32 random bytes, set only on the server.
- [ ] Device pins live in a durable store (`redisStore` / `RedisStore`) or your own registry.
- [ ] Challenges are minted only behind your own sign-in. If a receipt gates sign-in, you enrol
      computers yourself ([security](./security.md#enrol-computers-yourself-when-a-receipt-gates-sign-in)).
- [ ] `verify()` gets `origin`, `subject`, `data`, and `inputs` whenever the result says who the
      user is.
- [ ] Page calls routed to Writ Cloud are gated with `authorizeRun` (Python `authorize_run`).
- [ ] Your workflows contain none of your own secrets.
- [ ] Your page handles `CONSENT_DENIED`, `NOT_GRANTED`, `GRANT_STALE`, `RATE_LIMITED` and
      `RUN_FAILED` ([troubleshooting](./troubleshooting.md)).
- [ ] Users without Chrome or Edge on a computer still have a working path.
