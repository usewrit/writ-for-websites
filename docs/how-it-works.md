# How it works

A Writ Bridge call crosses five parts. Two of them are yours (the page and your server). Three
are on the user's computer and belong to the user (the extension, the native host and the Writ
engine). Writ Cloud takes part only for linked workflows and the cloud modes.

```
  user's computer                                                          your infrastructure
 ┌─────────────────────────────────────────────────────────────────┐      ┌──────────────────────┐
 │ your page (@usewrit/web)                                        │      │ your server          │
 │   │ window.writ (postMessage, same window)                      │      │ @usewrit/server or   │
 │   v                                                             │ ───> │ usewrit              │
 │ Writ extension: provider, bridge, service worker, windows       │ page │  verifies receipts,  │
 │   │ native messaging (app.usewrit.bridge)                       │ chan-│  hosts the page      │
 │   v                                                             │ nel  │  channel, mints      │
 │ native host (writ-agentd in browser-host mode)                  │      │  challenges, tokens  │
 │   │ loopback HTTP, the owner's local token                      │      └──────────────────────┘
 │   v
 │ Writ engine (writ-agentd, run by Writ desktop) ──> the sites the workflow calls
 │                                                └─> approved devices on the local network
 └─────────────────────────────────────────────────────────────────┘
```

## The parts

| Part | Where | What it does |
|---|---|---|
| `@usewrit/web` | Your page | Finds the extension, shows the setup banner, checks inputs against your contract, makes calls, carries receipts to your server, and serves your server's commands over the page channel. |
| Provider | The page's main world, injected by the extension | Defines a frozen `window.writ` and relays requests. It is the only thing your page touches. |
| Bridge and service worker | The extension | Decide the page's origin from the browser, enforce limits, open the consent, confirmation and start windows, and talk to the native host. |
| Native host | The user's computer, `app.usewrit.bridge` | Started by the browser. Speaks to the Writ engine over loopback with the owner's local token. Never starts the engine by itself. |
| Writ engine | The user's computer, run by Writ desktop | Holds grants, installs your workflows, runs them isolated, signs receipts. |
| Server bridge | Your server, `@usewrit/server` or `usewrit` | One route for the page channel, user tokens, challenges, receipt checks, device pins, Writ Cloud runs. |
| Writ Cloud | Writ's servers | Serves linked workflows' recipes, and runs functions in `recommended` / `cloud` mode with your API key. Not involved in a `required` call of a bundled workflow. |

## One call, step by step

A page call to `writ.pos.receive({ invoice_no })` in `required` mode, with the user already
connected:

1. `@usewrit/web` checks the inputs against your contract: required ones present, nothing
   undeclared, plain JSON, at most 1 MB.
2. It calls `window.writ.request({ method: "writ_call", params: { key, inputs, challenge } })`.
3. The extension's service worker reads the origin from the browser (`port.sender.origin`), checks
   it is `https` and the top frame, and checks the per-tab limit (4 calls in flight).
4. The function changes data and the user chose "Ask me before each change", so the extension
   opens **Allow this change?**. The user clicks **Allow once**.
5. The service worker sends `call.start` to the native host, which posts it to the engine.
6. The engine checks the grant for that origin and key, that the workflow has not changed since
   consent, that only declared inputs are passed, and the per-site limits (2 running, 30 a
   minute, 500 a day).
7. The engine runs the workflow isolated, on the HTTP or browser lane, reaching only the hosts in
   the workflow and the local-network addresses the user approved.
8. The engine signs a receipt over the outcome, the origin, the key, your challenge, a hash of the
   inputs and a hash of the data, with a key it keeps for this site on this computer.
9. Progress events (step `index` of `total`, no labels, no URLs), then the result and the receipt,
   travel back to the page.
10. Your page sends `{ data, receipt }` to your server, which calls `verify()` before trusting
    anything.

A server call, `writ.user(id).pos.receive(...)`, goes the other way first: your server queues a
command with a challenge minted for it; the user's open page picks it up from your route (a long
poll, `GET /writ-bridge?wait=25`), runs it as above, and posts the result and receipt back. The
server bridge verifies the receipt before your `await` returns.

## Trust boundaries

**The origin comes from the browser.** The extension takes the page's origin only from the
browser's own `port.sender.origin`. A page never names an origin, and nothing in the request can
change it. Only the top frame may call. Only `https` origins may call, plus `http://localhost` and
`http://127.0.0.1` while the extension's Developer mode is on.

**The consent window is the only source of grants.** A grant is created only from the extension's
own `consent.html`, which your page can neither script nor frame. The service worker checks the
sender's extension id, the exact page and the request id before accepting an answer. The window
opens even when no function matches, so a site cannot probe what a user has. Its buttons stay
disabled for 600 ms after it appears or regains focus, so a click aimed at the page behind it
cannot land on Allow.

**Writes are confirmed.** A function that changes data shows a confirmation window before each
run while the grant's write policy is "ask", the default. A denial ends the call with
`CONSENT_DENIED`.

**The local network is reached only on approval.** A workflow reaches a device on the user's
network only when the package declares it and the user confirms it in the consent window, or when
the user typed that address as a `lan_host` setting. A call input can never choose a destination:
a URL whose host comes from a call input is refused when the package is parsed, and runs a site
starts are attributed to the site, not the owner.

**Writ starts only with consent.** The native host never starts the engine by itself. When a site
needs Writ while it is stopped, the extension opens **Start Writ for this site?** with **Start
Writ** and **Not now**, one window per site at a time. After **Not now**, the page is not asked
again until it reloads. The engine starts without that window only when the user ticked **Start
Writ when this site needs it** for that site in its consent window, or pressed **Start Writ** in
the extension's popup or welcome page. `writ_status` never starts Writ.

**Installed workflows are walled off.** A workflow a site ships, whoever runs it (the site, the
owner, a schedule):

- never reads the owner's vault, saved sign-ins, personas or local files;
- sees only its declared inputs and the credentials the user typed for it;
- keeps its own signed-in session between runs, separate from the owner's;
- never starts from the owner's own browser profile;
- cannot contain AI steps, file steps, generated code or payment fields.

**Grants end.** A grant lasts 30 days, 90 days or 1 year, as the user chose. The user can
disconnect a site from the extension's popup or from Writ desktop at any time. Your page can
revoke its own grant with `session.disconnect()`; that never removes the workflows it installed.

## What travels where

| What | From | To | Notes |
|---|---|---|---|
| Function keys, descriptions, packages | Your page | The extension, then the engine | Shown in the consent window. |
| Call inputs | Your page, or your server through the page | The engine | Declared inputs only, at most 1 MB. Never logged by the extension. |
| Credentials typed at install | The user, in the consent window | The engine | Sealed on the installed workflow. Never sent to your page. |
| Per-call credentials | Your page, as an input | The engine | Used for that run only, never stored, never written to the run record. |
| Settings (a POS address) | Suggested by your page, confirmed by the user | The engine | Stored with the installed workflow. Not secret. |
| Run requests | The engine | The sites and approved devices the workflow calls | From the user's computer and IP address. |
| Progress | The engine | Your page | Step counts only: no labels, no URLs. |
| Results | The engine | Your page | Only the function's declared outputs. Capped at 25 MB. |
| Error messages | The engine | Your page | Fixed, sanitized codes and messages: no selectors, URLs or local addresses. |
| Receipts | The engine | Your page, then your server | Signed; carry hashes of inputs and data, not the values. |
| Page channel traffic | Your page | Your server | Same origin, `Authorization: Writ <userToken>`. |
| Linked recipes | Writ Cloud | The engine | Signed, held in memory only, fetched per page session or per call. |
| Cloud runs | Your server | Writ Cloud | `recommended` / `cloud` only, with your `WRIT_API_KEY`. |

## What never leaves the user's computer

- The credentials the user typed into the consent window, and the sessions the workflow earns
  with them.
- The user's own Writ vault, saved sign-ins, personas and files. A site's workflow cannot read
  them at all.
- The content of the pages and APIs the workflow visits, except the declared outputs it returns
  to your page.
- The device key that signs receipts. Only its public key travels, inside each receipt.
- Anything about the user's other connected sites. Each site gets its own receipt key, so two
  sites cannot match the same user through receipts.

The extension itself reads no page content, holds no credentials, makes no network requests and
sends nothing to Writ's servers or to you. It passes messages between your page and Writ desktop
on the same computer.

## Limits

| Limit | Value | Enforced by |
|---|---|---|
| Inputs per call | 1 MB of JSON | Library, extension, engine |
| Call timeout | 1 s to 15 min, default 2 min | Extension |
| Calls in flight per tab | 4 | Extension (the page bridge queues the rest) |
| Runs per site | 2 at once, 30 a minute, 500 a day | Engine |
| Result size | 25 MB | Engine |
| Challenge length | 2048 characters | Library, extension, engine |
| Package size | 512 KB of JSON, 1 to 500 steps | Library, engine |
| Packages per connect | 3 MB in total | Extension |
| Credentials, settings, local-network hosts per package | 10, 8, 8 | Library, engine |
| Function key | `[a-z0-9][a-z0-9._-]{0,63}` | Library, extension |
| App name, function description | 80, 200 characters | Library, extension |

The full wire format is in the [contract](./contract.md).
