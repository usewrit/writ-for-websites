# Writ website integration: wire contract (v1, protocol 1)

The binding contract between the parts that let a website run Writ workflows on a visitor's
computer: the page library, the Writ browser extension, the native host and the Writ engine
(`writ-agentd`), plus the Writ Bridge on the developer's server. Section numbers are stable; other
documents link to them.

For a guided introduction, start with the [quickstart](./quickstart.md) and
[how it works](./how-it-works.md).

```
@usewrit/web ──(window.writ)── provider ──postMessage── bridge ──runtime port── service worker ──native messaging── writ-agentd (browser-host mode) ──loopback── engine /v1/sites/*
  the page library              Writ extension (Manifest V3, one package for Chrome and Edge)                        Writ desktop, on the same computer
```

Every hop speaks the same envelope. A request is `{ id, method, params }`. A reply is
`{ id, result }` or `{ id, error: { code, message } }`. An event is `{ event, payload }`.
`id` is a string, unique per sender.

Names:
- **Native host name:** `app.usewrit.bridge`.
- **Protocol number:** `1`. Every hop refuses a different major protocol with `DESKTOP_OUTDATED`
  (page/extension side) or `PROTOCOL_MISMATCH` (host side).

## Error codes (all hops)

| code | meaning |
|---|---|
| `NOT_INSTALLED` | library only: no `window.writ` provider after the detection timeout |
| `DESKTOP_MISSING` | the native host is not registered (Writ desktop not installed, or too old to register it) |
| `DESKTOP_OUTDATED` | protocol mismatch between extension and host |
| `DAEMON_UNAVAILABLE` | the host could not reach or start the Writ engine |
| `VAULT_LOCKED` | the owner's vault is locked; unlock Writ |
| `CONSENT_DENIED` | the user declined the connection or a write confirmation |
| `NOT_GRANTED` | this origin has no grant, or no binding for that key |
| `GRANT_STALE` | the bound workflow changed since consent (steps, destinations); `writ_connect` again |
| `WRITE_NEEDS_CONFIRM` | engine only: a write call without `user_confirmed` under the "ask" policy |
| `INPUT_INVALID` | inputs failed validation (undeclared key, secret/file key, too large, local-network destination chosen by input) |
| `RATE_LIMITED` | per-origin concurrency / per-minute / per-day limit |
| `LAN_NOT_ALLOWED` | the run was refused a local-network address the owner has not approved |
| `RUN_FAILED` | the run ended in failure (`message` is sanitized: no selectors, URLs, stack) |
| `CANCELLED` | cancelled by the page, the tab closing, or the owner |
| `TIMEOUT` | the call exceeded `timeout_ms` |
| `RESULT_TOO_LARGE` | the result exceeded the cap (default 25 MB) |
| `PROTOCOL_MISMATCH` | host only: `hello` named a protocol this host does not speak (the extension maps it to `DESKTOP_OUTDATED`) |
| `RECIPE_UNAVAILABLE` | linked workflow (§11): Writ couldn't get its recipe from Writ Cloud (offline, or a base this computer doesn't allow) |
| `PUBLICATION_REVOKED` | linked workflow: the website withdrew it |
| `QUOTA_EXCEEDED` | linked workflow: the website's Writ plan is out of deliveries this month |
| `BAD_REQUEST` | malformed request |
| `ORIGIN_NOT_ALLOWED` | not https (localhost allowed only in the extension's developer mode), or not the top frame |
| `INTERNAL` | anything else |

## 1. Page ⇄ provider (`window.writ`, injected by the extension, MAIN world, `document_start`)

```ts
interface WritProvider {
  readonly isWrit: true
  readonly version: string        // extension version
  readonly protocol: 1
  request(args: { method: string; params?: unknown }): Promise<unknown>
  on(event: 'call', cb: (payload: CallEvent) => void): void
  off(event: 'call', cb: (payload: CallEvent) => void): void
}
```

`window.writ` is defined with `Object.defineProperty(window, 'writ', { value: frozen, writable:
false, configurable: false })`.

Discovery is race-free, EIP-6963 style:
- The provider dispatches `window.dispatchEvent(new CustomEvent('writ:announceProvider', { detail: Object.freeze({ provider, info: { name: 'Writ', version, protocol: 1 } }) }))` once at injection.
- It dispatches again every time it sees a `writ:requestProvider` event.

### Methods

| method | params | result |
|---|---|---|
| `writ_status` | none | `{ extension_version, protocol: 1, host: 'ok'\|'missing'\|'outdated', daemon: 'running'\|'started'\|'unavailable', desktop_version: string\|null, lan_capable: boolean }` |
| `writ_connect` | `{ app: string, functions: FunctionRequest[] }` | `{ origin, functions: GrantedFunction[] }` (opens the consent window when any key is unbound; `CONSENT_DENIED` on decline) |
| `writ_functions` | none | `{ origin, functions: GrantedFunction[] }` (empty when not connected) |
| `writ_call` | `{ key, inputs?: object, timeout_ms?: number, dry_run?: boolean, challenge?: string, token?: string, recipe_cache?: 'session'\|'call' }` | `{ call_id }`, then `call` events for `call_id` (`token` / `recipe_cache`: linked workflows, §11) |
| `writ_refresh_recipes` | none | `{ ok: true }` once this page's cached linked recipes are dropped (§11) |
| `writ_cancel` | `{ call_id }` | `{ ok: true }` |
| `writ_disconnect` | none | `{ ok: true }` (revokes this origin's grant) |

```ts
type FunctionRequest = {
  key: string                      // site-chosen, [a-z0-9][a-z0-9._-]{0,63}
  description: string              // shown in consent, ≤ 200 chars
  writes?: boolean                 // the site expects it to change data
  match?: { name?: string; host?: string }  // hints to pre-select one of the user's functions
}
type GrantedFunction = {
  key: string
  description: string
  inputs: { name: string; required: boolean; description?: string }[]
  outputs: string[]
  writes: boolean
  local_network: boolean           // the bound workflow reaches the owner's local network
}
type CallEvent =
  | { call_id: string; type: 'started'; run_id: number }
  | { call_id: string; type: 'progress'; index: number; total: number }   // NO step labels, NO URLs
  | { call_id: string; type: 'needs_user'; reason: 'twofa' | 'captcha' | 'vault_locked' | 'confirm' }
  | { call_id: string; type: 'finished'; run_id: number; data: unknown; duration_ms: number; engine: 'http' | 'browser' | 'hybrid' | null }
  | { call_id: string; type: 'error'; code: string; message: string }
```

Limits enforced by the extension before anything leaves the browser:
- `inputs` JSON at most 1 MB;
- `timeout_ms` clamped to [1 000, 900 000], default 120 000;
- at most 4 calls in flight per tab.

## 2. Provider ⇄ bridge (`window.postMessage`, same window)

Page → bridge: `{ __writ: 1, dir: 'req', id, method, params }`.

Bridge → page:
- `{ __writ: 1, dir: 'res', id, result }`, or `{ __writ: 1, dir: 'res', id, error }`;
- `{ __writ: 1, dir: 'evt', event: 'call', payload }`.

Filtering:
- The bridge ignores any message where `event.source !== window` or the shape is not exact.
- The provider ignores `res` / `evt` messages it did not ask for: unknown `id`, or an unknown
  `call_id`.

## 3. Bridge ⇄ service worker (`chrome.runtime.connect({ name: 'writ-page' })`, one port per page)

The same `{ id, method, params }` / `{ id, result|error }` / `{ event, payload }` frames.

**Trust: the service worker decides the origin ONLY from `port.sender.origin`. The page never
supplies an origin.**

Refusals, all with `ORIGIN_NOT_ALLOWED`:
- `port.sender.frameId !== 0` (not the top frame);
- an origin that is not `https:`;
- `http://localhost` / `http://127.0.0.1`, unless developer mode is on in the extension options.

When a page port disconnects (navigation, tab close), the service worker cancels that page's
in-flight calls.

## 4. Service worker ⇄ native host (`chrome.runtime.connectNative('app.usewrit.bridge')`)

**Transport.** Chrome native messaging: a u32 native-endian length prefix + UTF-8 JSON.
- Host → extension frames are at most 1 MB: results travel as `call.result_chunk` parts of at most
  768 KiB of JSON text.
- The service worker opens one shared port lazily and closes it after 60 s with no call in flight.

**Origins.**
- The host refuses to start unless argv[1] is one of its allowed extension origins.
- The service worker sends the page origin it derived in §3 as `params.origin`. The host trusts
  the extension, which owns the origin decision; the engine re-validates the origin's shape.

| method | params | result |
|---|---|---|
| `hello` | `{ extension_version, protocol: 1, browser: 'chrome'\|'edge'\|'other' }` | `{ protocol: 1, host_version, daemon: { state: 'running'\|'started'\|'unavailable', version: string\|null }, lan_capable }` |
| `grants.get` | `{ origin }` | `{ grant: Grant \| null }` |
| `grants.candidates` | `{ origin, requested: FunctionRequest[] }` | `{ functions: Candidate[] }` |
| `grants.create` | `{ origin, app_name, bindings: { key, description, workflow_id, function_name: string\|null, writes_declared: boolean }[], write_policy: 'ask'\|'allow', ttl_days: number }` | `{ grant: Grant }` |
| `grants.revoke` | `{ origin }` | `{ ok: true }` |
| `grants.list` | none | `{ grants: Grant[] }` (extension popup) |
| `call.start` | `{ call_id, origin, key, inputs, user_confirmed: boolean, timeout_ms, dry_run }` | `{ call_id, run_id }`, then events |
| `call.cancel` | `{ call_id }` | `{ ok: true }` |
| `daemon.start` | none | `{ state: 'running'\|'started' }` |

**Writ starts only with the person's consent.** The host never starts the engine on its own: with
none running, every method answers `DAEMON_UNAVAILABLE` and `hello` reports `unavailable`. Only
`daemon.start` starts one (detached, so it outlives the browser), and the service worker sends it
in exactly two cases:
- the person presses Start Writ in the extension's own popup, welcome page or start window;
- a site's `writ_connect`, `writ_functions` or `writ_call` found Writ not running, and the person
  ticked "Start Writ when this site needs it" in that site's consent window.

Otherwise such a request opens the start window (`start.html`): the site, and Start Writ / Not now.
One window per site at a time, and after Not now the page is not asked again until it reloads; its
requests fail `DAEMON_UNAVAILABLE`. `writ_status` never starts Writ and never opens the window. The
"start when needed" choice is the extension's (`chrome.storage.local`, `autostart.<origin>`), since
Writ's grants can't be read while it is stopped. It lasts as long as the site's grant, is set or
cleared each time the person answers the consent window, and goes when the site is disconnected or
Writ reports no live grant for it.

Host → service worker events (`{ event, payload }`, `payload.call_id` always set):
- `call.started` `{ run_id }`
- `call.progress` `{ index, total }`
- `call.needs_user` `{ reason }`
- `call.result_chunk` `{ seq, last, part }`: `part` is a slice of the result JSON text, and
  `seq` starts at 0.
- `call.finished` `{ run_id, duration_ms, engine }`: always after the last chunk.
- `call.error` `{ code, message }`

```ts
type Grant = {
  id: number
  origin: string
  app_name: string
  write_policy: 'ask' | 'allow'
  created_at: number; last_used_at: number | null; expires_at: number   // unix seconds
  bindings: {
    key: string; description: string
    workflow_id: number; workflow_name: string; function_name: string | null
    writes: boolean; local_network: boolean
    inputs: { name: string; required: boolean; description?: string }[]
    outputs: string[]
    stale: boolean                      // the workflow changed since consent
  }[]
}
type Candidate = {
  workflow_id: number; workflow_name: string; function_name: string | null
  description: string | null
  inputs: { name: string; required: boolean; description?: string }[]
  outputs: string[]
  writes: boolean
  destinations: string[]                // hosts the function reaches; local-network ones listed in lan_destinations too
  lan_destinations: string[]
  persona_name: string | null
  suggested_for: string[]               // requested keys this candidate matches by hint
}
```

**Consent UI** (extension-owned popup window `consent.html`):
- The service worker opens it with `chrome.windows.create({ type: 'popup', url })`, keyed by a
  request id held in `chrome.storage.session`.
- The page reads its request and the candidates from the service worker over
  `chrome.runtime.sendMessage`.
- `consent.approve` / `consent.deny` are accepted ONLY when `sender.id === chrome.runtime.id` and
  `sender.url` starts with the extension's own `consent.html`.

**Write confirmation** (`confirm.html`, same rules):
- It shows before every `writes: true` call when the grant's `write_policy` is `ask`.
- On approve the service worker sends `call.start` with `user_confirmed: true`. On deny the page
  gets `CONSENT_DENIED`.

## 5. Native host ⇄ engine (loopback HTTP, `Authorization: Bearer <local wlt_ token>`, no `Origin` header)

All `/v1/sites/*` routes:
- need the owner's manage scope;
- refuse LAN and tunnel reach;
- are the owner's: the local `wlt_` token, or a `manage` key.

| route | body | answer |
|---|---|---|
| `POST /v1/sites/hello` | `{ extension_version, browser }` | `{ daemon_version, lan_capable }` (records the last extension handshake) |
| `GET /v1/sites/status` | none | `{ extension: { last_seen_at, version, browser } \| null, hosts: { chrome, edge, chromium, brave }: boolean }` |
| `POST /v1/sites/host/install` | none | `{ hosts: { ... } }` (re)writes the native-host manifests |
| `GET /v1/sites/grants[?origin=]` | none | `{ grants: Grant[] }` |
| `POST /v1/sites/candidates` | `{ origin, requested }` | `{ functions: Candidate[] }` |
| `POST /v1/sites/grants` | `{ origin, app_name, bindings, write_policy, ttl_days }` | `{ grant }` (the site then shows under Connect → Connected apps → Websites) |
| `DELETE /v1/sites/grants/:id` | none | `{ ok }` (the app) |
| `POST /v1/sites/revoke` | `{ origin }` | `{ ok, removed }` (the extension popup, `writ_disconnect`) |
| `POST /v1/sites/calls` | `{ origin, key, inputs, user_confirmed, timeout_ms, dry_run }` | `202 { run_id, workflow_id }` |

The host then:
1. follows `GET /v1/runs/:run_id/events` (SSE: `started` / `step` / `progress` / `finished` / `error`);
2. on `finished`, reads `GET /v1/workflows/:workflow_id/_runs/:run_id` for `data`;
3. chunks `data` to the service worker.

**Engine enforcement for `/v1/sites/calls`:**
- a live grant for the origin, with a binding for the key;
- the binding's hash still matches the workflow, else `GRANT_STALE`;
- declared inputs only: no `secret:` / `file:` keys, no `persona_id` / `function_name` /
  `auth_policy` overrides;
- `store: "return"`;
- writes need `user_confirmed` when the policy is `ask`, else `WRITE_NEEDS_CONFIRM`;
- the workflow's REST toggle is NOT consulted: the owner's consent for this origin is the exposure
  decision for that site;
- per-origin limits: 2 concurrent, 30/min, 500/day;
- runs are attributed to the site (its origin and grant id), which is not the owner, so a site
  input can never choose a local-network destination.

## 6. Desktop app surfaces (Writ desktop)

- Connect → Connected apps → **Websites**: `GET /v1/sites/grants` and `DELETE /v1/sites/grants/:id`.
- Settings → **Browser extension**: `GET /v1/sites/status` and `POST /v1/sites/host/install`, plus
  install links.
- Workflow → **Local network access**: `GET/PUT /v1/workflows/:id/network`,
  `POST/DELETE /v1/workflows/:id/network/hosts`.
- App-wide **local-network approval prompt**: `GET /v1/network/lan-requests`,
  `POST /v1/network/lan-requests/:id { approve }` and `POST /v1/network/lan-requests/:id/surfaced`.
- Run history caller label: `caller.identity.kind === 'site'`, shown as "Website · <origin>".

## 6b. Errors the engine returns

Every `/v1/sites/*` refusal is `{ error, code }` with a contract `code`. The native host relays
`code` as is, and only codes of the form `[A-Z_]+` cross to the page; anything else becomes
`INTERNAL`.

A failed run never carries the run's own error text to the page, because it can name selectors,
URLs or local-network addresses. The host maps the run's status to fixed messages:
`RUN_FAILED`, `LAN_NOT_ALLOWED`, `CANCELLED` or `TIMEOUT`.

## 7. Store listing IDs

`allowed_origins` in the host manifest lists the Chrome Web Store ID, the Edge Add-ons ID and the
development ID. Release builds of the engine carry the store IDs. The development ID is pinned by
the `key` in the extension's development manifest.

For development with an unpacked extension, run `WRIT_EXTENSION_IDS=<id> writ-agentd
install-browser-host`. It adds the id to the manifests and remembers it in `browser_host.json` in
Writ's home. That file matters because the host is started by the browser without the
installer's environment, so it checks its caller against the file. Writ's home is the desktop's
active profile (`~/.writ/profiles/<id>`, named in `~/.writ/active_profile`) for both the host and
the installer, unless `WRIT_HOME` says otherwise.

The engine re-registers the host for every installed browser at each start. Set
`WRIT_BROWSER_HOST_AUTOINSTALL=0` to turn that off.

## 8. Installable workflows (a site supplies the workflow; the user installs it with one click)

A site may ship the workflow itself instead of asking the user to bind one of theirs. It adds a
`package` (and, when the package has several functions, `function`) to a `FunctionRequest`:

```ts
type FunctionRequest = {
  key: string; description: string; writes?: boolean; match?: { name?: string; host?: string }
  package?: WritPackage          // the workflow to install for this key
  function?: string              // which function of the package this key calls (required when it has several)
}
type WritPackage = {
  format: 'writ.workflow/v1'
  id: string                     // the site's id for it, [a-z0-9][a-z0-9._-]{0,63}; (origin, id) names one installed workflow
  version?: string               // shown to the user, at most 32 chars
  name: string                   // 1..120 chars
  description?: string           // at most 1000 chars
  entry_url?: string             // http(s)
  steps: object[]                // Writ workflow steps (the same shape a saved workflow stores), 1..500
  functions?: object[]           // optional function declarations, as a saved workflow stores them
  api_functions?: object         // optional API-function map
  auth_config?: object           // optional sign-in recipe (AuthRecipe v1)
  inputs?: { [name: string]: { description?: string; required?: boolean } }
  credentials?: { key: string; label: string; secret?: boolean; required?: boolean }[]   // at most 10
  settings?: WritSetting[]       // at most 8: values each user gives once (below)
  local_network?: { hosts: string[]; reason?: string }   // at most 8 single hosts, no ranges, no loopback
}
type WritSetting = {
  key: string                    // [A-Za-z0-9_]{1,64}; unique; not also an input or a credential key
  label: string                  // 1..80 chars, e.g. "Your POS address"
  description?: string           // at most 200 chars: where the user finds it
  kind?: 'text' | 'lan_host'     // default 'text'
  example?: string               // at most 120 chars; the field's placeholder
  required?: boolean             // default true
}
```

### Credentials the site gives per call, and a private recipe

- A credential declared with `"per_call": true` is not asked in the consent window and never stored.
  The site passes it with every call, as an input named after its key (`password` for
  `{{secret:password}}`). The engine moves it to that run's call-secret channel (`secret:KEY`). There
  it fills `{{secret:KEY}}` and the session identity, like a typed login, and it is never written to
  the run record. Use it when the site's own sign-in IS this login: each of its users brings
  theirs. Export: `call_credentials: [KEY]` on an item, or `writ package export --call-credential KEY`.
- `"recipe": "hidden"` on a package keeps its steps private on users' computers. It runs there, but
  the owner's API answers its workflow with empty steps and `recipe_hidden: true`, and refuses to
  edit, export, document or copy it to Writ Cloud. The MCP tools don't read it, and its run traces
  keep no step detail, as for a linked one. Export: `hide_recipe: true` on an item.

### Settings: values each user gives once (a POS address, a store number)

A setting is a value that differs per user but not per call. The recipe uses it like any
placeholder (`http://{{pos_host}}/api/receive`, `{{store_no}}`), and each user gives it once.

- **Who gives it.** The user, in Writ's own consent window. The site may suggest a value, typically
  after asking in its own form (`functions[].settings`, below), and the window shows it pre-filled
  for the user to confirm or correct. Nothing is stored before the user clicks "Install and allow".
- **Where it lives.** It is stored on the installed workflow as one of its stored input values
  (`form_data`), so every run resolves `{{key}}` with it, whoever starts the run. It is not a
  secret; use a credential for secrets.
- **`lan_host`.** One address on the user's local network:
  - `host` or `host:port`, where the host is an IPv4 address, `[IPv6]` or a name;
  - no scheme, path, range or loopback (the same rules as `local_network.hosts`).

  The confirmed value is approved as one of that workflow's local-network hosts
  (`approved_via: "site"`). It replaces the previous value's approval when the user changes it. The
  consent window highlights it as an address on their network.
- **`text`.** At most 200 characters, no control characters.
- **A website can't set it per call.** A call may pass only the function's declared inputs, so a
  setting key in `inputs` is `INPUT_INVALID`.
- **Where a request may go.** A URL whose scheme or host comes from a caller value must take it
  from a declared setting. A function input there is refused when the package is parsed, because
  the site could aim the user's Writ anywhere, call by call. A response value (`{{extracted:…}}`,
  a "next page" link) may still name the host. The local network stays out of reach for any value
  but an address the user confirmed, since a run's local-network allowlist is the workflow's
  approved hosts.
- **Changing it.** Any of these updates the stored value (and its local-network approval):
  - the site suggests a different value on a later `writ_connect`: the package's status becomes
    `"update"` with `settings_changed`, and the window asks again;
  - the user edits it in Writ desktop (Websites → the site → the workflow);
  - a package version adds a required setting, which also makes its status `"update"`.

### Limits the engine enforces when it parses a package

**Size.** The package's JSON is at most 512 KB.

**Steps that are refused.** A package may not contain:
- `upload` or `wait_for_download` steps (no local files);
- AI steps (`ai_fill_form`, `ai_fill`, `ai_continue`, `ai_navigate`), which would spend the owner's AI
  key;
- `codegen` steps.

**Text that is refused.** A package may not contain:
- `{{file:…}}`;
- any `{{secret:K}}` / `{{vault:K}}` whose `K` is not one of its declared `credentials`;
- any payment field (`payment_mode`, `__pay_`).

### Isolation, whoever runs it: the site, the owner, a schedule or the cloud

An installed site workflow:
- never reads the owner's vault, local files or personas;
- sees only the credentials the owner typed for it at install time (sealed on the workflow) and its
  own declared inputs;
- reaches local-network hosts only if the package declares them and the owner confirms them in the
  same click. They are recorded with `approved_via: "site"`;
- keeps its OWN signed-in session between runs, through the ordinary workflow-session plumbing:
  - the install turns session persistence on;
  - the credentials typed at install are the session's credential identity (as vault secrets are
    for the owner's workflows);
  - each run, on either lane, restores the session banked for that identity and banks what it ends
    holding (a jar with no login in it is not banked), so it signs in only when the site asks again;
  - re-installing with another login clears the previous account's sessions;
  - in the browser, a restored session that still signs the run in skips the recorded sign-in. At
    the first sign-in step that needs the form, the engine waits up to 4 s for its field, or any
    visible password box. With neither, the site treats the session as signed in, and that
    sign-in chain is skipped (traced as skipped). Otherwise the sign-in runs as recorded. (The
    HTTP lane already skips `login_post` on a warm session.)
- never starts from the owner's browser: with "use local Chrome" or an uploaded profile, its
  browser contexts skip that baseline.

### Wire

- **`writ_connect`**: packages ride along in `functions[]`.
  - The consent window shows, per package key: name, version, description, functions (inputs,
    outputs, writes), every host it calls, the local-network hosts it asks for with the site's
    reason, and one field per declared credential.
  - The Allow button reads "Install and allow". Credential values are typed in the extension's own
    window and go to the engine; the page never sees them.
- **Preview** (`grants.candidates` → `packages[].preview`):

  ```ts
  {
    id, name, version, description, entry_url, step_count, hash, notes: string[],
    functions: { name, description, inputs: { name, required, description }[], outputs: string[], writes, destinations: string[],
                 address_settings: string[] }[],   // settings whose value is where its requests go
    destinations: string[],
    local_network: { hosts: string[], reason: string | null },   // also flat as lan_hosts / lan_reason
    credentials: { key, label, secret, required }[],
  }
  ```

  The preview also carries
  `settings: { key, label, description, kind, example, required, value, stored }[]`:
  - `stored` is the value this site's installed copy holds, or `null`;
  - `value` is what the field opens with: the site's suggestion when it is valid, else `stored`,
    else `null`.

  A field whose `value` differs from a non-null `stored` is a change the user confirms (the window
  shows the stored value it replaces).

  The consent window marks only that package as not installable when it can't read a preview.
- **Rules:**
  - When several keys use the same package, the window shows one card. Two different packages
    under one id are refused.
  - On an update, credential fields are optional: a key that is not sent keeps its stored value.
  - Settings are sent on every install and update: the window sends every field's value, pre-filled
    or typed. A required setting without a value is refused before the host is called.
  - `writ_disconnect` from a page never removes installed workflows. Only the owner's own Disconnect
    (popup or app) can, with `remove_installed`.
  - The extension caps one connect's packages at 3 MB counted per key, and refuses any host request
    over about 4 MB with `INPUT_INVALID`. The host drops frames over 4 MB.
  - An `unknown method` answer to `packages.check` (an older desktop) means `DESKTOP_OUTDATED`.
- **Host methods:**

| method | params | result |
|---|---|---|
| `packages.check` | `{ origin, packages: { key, package, settings? }[] }` | `{ packages: { key, status: 'new'\|'update'\|'current'\|'invalid', error?, workflow_id?, settings_changed?: string[] }[] }` |
| `grants.candidates` | `requested[]` may carry `package` / `function` / `settings` (suggested values) | `functions[]` as before, plus `packages: { key, preview?, error?, installed: { workflow_id, version, current } \| null }[]` |
| `grants.create` | a binding may be `{ key, description, package, function?, credentials?: { [key]: string }, settings?: { [key]: string } }` instead of `{ workflow_id, function_name }` | installs or updates, then binds |
| `grants.revoke` | `{ origin, remove_installed?: boolean }` | `{ ok }` |

- **Engine routes:**
  - `POST /v1/sites/packages/check`: same as the `packages.check` method above.
  - `GET /v1/sites/packages[?workflow_id=]`: `{ packages: { workflow_id, origin, package_id, version, installed_at, updated_at, settings: { key, label, kind, required, value }[], fixed_hosts, source: 'bundled'|'linked', publication: { id, base, version }|null, publisher, access, linked_status: 'offline'|'withdrawn'|null, linked_status_at }[] }`.
  - `PUT /v1/sites/packages/:workflow_id/settings` `{ settings: { [key]: string } }` (owner-only,
    manage scope): change stored settings, with the same validation and local-network approval as
    an install. It answers like `GET` for that one workflow.
  - `DELETE /v1/sites/grants/:id?remove_installed=true` and `POST /v1/sites/revoke { remove_installed }`
    also delete the workflows that origin installed.
- **`Grant.bindings[]`** gains `package: { id, version } | null`.
- **Suggested settings (page → provider).** `FunctionRequest` gains
  `settings?: { [settingKey: string]: string }`. These are values the site suggests for the
  package's settings; when several keys share a package, the first suggestion for a setting wins.
  At most 8 entries per request, each at most 200 characters; anything else is `INPUT_INVALID`.
- **When consent opens:** `writ_connect` skips the consent window only when every requested key is
  bound, not stale, and every package `packages.check` reports `current`. A new version reopens it
  as "Update", again one click.

## 9. Developer tools: from your workflows to a website integration

**Goal.** A developer turns workflows they built in Writ into something their website ships. End
users install it with one click and it runs on their own computer, so there is no server cost and
no Writ infrastructure in the loop.

### Export (owner-only, manage scope, local reach): `POST /v1/sites/packages/export`

Body:

```ts
{ items: { workflow_id: number; function_name?: string | null; key?: string;
           settings?: { key: string; label?: string; kind?: 'text' | 'lan_host'; description?: string; example?: string }[] }[] }   // 1..20 items
```

An item may also carry `call_credentials: string[]` (credentials the site gives per call, §8) and
`hide_recipe: true` (a private recipe, §8).

Settings in an export:
- An input the recipe uses in a URL's scheme or host becomes a setting automatically: `lan_host`
  when the developer's own value for it is a local-network address or the workflow has approved
  local-network hosts, otherwise `text`. The export carries a warning.
- `items[].settings` turns further inputs into settings, or names them (label, kind, description,
  example).
- The developer's own value is never exported: it is their address, not the user's.

Answer:

```ts
{
  packages: {
    workflow_id: number; function_name: string | null
    key: string                      // the given key, else derived: <package id>.<function or "run">
    package: WritPackage             // ready to ship: steps/functions/auth_config/inputs as stored,
                                     // credential VALUES never included; every {{secret:K}} becomes a
                                     // declared credential K; approved single LAN hosts become local_network
    contract: {
      inputs: { name: string; required: boolean; description?: string }[]
      outputs: string[]
      writes: boolean
      local_network: string[]
      credentials: { key: string; label: string; secret: boolean }[]
      settings: { key: string; label: string; kind: 'text' | 'lan_host' }[]
    }
    warnings: string[]               // e.g. a persona sign-in the end user will have to type instead,
                                     // a LAN range or loopback entry left out, a step type packages refuse
    valid: boolean                   // the package passes the engine's package checks as is
    error?: string                   // why not, when valid is false
  }[]
}
```

Several items of the same workflow share one `package` (the same `id`). Each item is its own key
(`function`).

### CLI

`writ package export <workflow> [--function <name>] [--key <key>] [--setting KEY[:lan_host|:text][=LABEL]] [--call-credential KEY] [--out <file>]`
prints or writes the same JSON.

### SDK banner (`@usewrit/web`)

```ts
mountWritBanner({
  app: string,
  functions: FunctionRequest[],      // with packages
  onReady(session) {},
  position?: 'top' | 'bottom',
  locale?: 'en' | 'fr' | 'es',
  container?: HTMLElement,
}) → { destroy(), session: Promise<WritSession> }
```

The banner renders in a shadow root at the top of the page and walks the visitor through what is
missing, in order:
1. the extension (store links);
2. Writ desktop (`DESKTOP_MISSING` / `DESKTOP_OUTDATED` → https://usewrit.app/desktop);
3. the engine (`daemon: 'unavailable'` → "Open Writ" + retry);
4. "Install <workflow> (one click)" / "Connect", which calls `connect()` and opens the consent
   window;
5. once connected, it hides and calls `onReady`.

It is dismissible per page session and never shows when the session is already connected.

### Desktop "Use on a website" tool

Lives at Connect → Connected apps → Websites → "Add to your website". The developer:
1. picks workflows and functions (one or many);
2. edits the keys;
3. gets the package JSON (download one file per package, or copy);
4. gets typed contracts (`writ-functions.d.ts`);
5. gets a ready-to-paste snippet: `connectWrit` + `mountWritBanner` + typed calls;
6. sees the export warnings next to each package.

## 10. The contract file (what a developer downloads) and the typed client

**Developer journey:**
1. Build workflows in Writ (desktop app or Writ Cloud).
2. Download ONE contract file.
3. Ship it with the site.
4. Load it with `@usewrit/web`.

The banner gets the visitor set up: the extension, Writ desktop, then a one-click install of the
site's workflows. The typed client then calls every function on the visitor's own computer, with
no request to Writ.

```ts
type WritContract = {
  format: 'writ.contract/v1'
  generated_at: string                 // ISO 8601
  generator: string                    // "writ-desktop/<version>" | "writ-cloud"
  publisher?: { name?: string }        // shown in consent as what the site says it is (not verified)
  functions: {
    key: string                        // [a-z0-9][a-z0-9._-]{0,63}, unique; dots make namespaces in the client
    description: string
    package: string                    // the id of one of `packages`
    function: string | null            // the package function this key calls
    inputs: { name: string; required: boolean; description?: string }[]
    outputs: string[]
    writes: boolean
    local_network: string[]
    settings?: { key: string; label: string; kind: 'text' | 'lan_host' }[]   // the package's settings, for the site's own form
  }[]
  packages: WritPackage[]              // §8, each id once
}
```

A function entry may also carry `mode` (`'required' | 'recommended' | 'cloud'`, §12) and
`cloud: { workflow_id, function } | null` (§11).

### Producers

- **Engine:** `POST /v1/sites/packages/export` also answers `contract: WritContract` (the
  `valid` items only), built from the same items.
- **CLI:** `writ package export … --out writ-contract.json` writes it.
- **Writ Cloud:** `POST /api/automation/workflows/contract` produces the same shape for cloud
  workflows. It applies the same refusals and the same session scrubbing; the visitor's engine
  re-checks everything at install anyway.

### SDK

- **`contractFunctions(contract) → FunctionRequest[]`.** Each request carries its package and
  function.
- **`mountWritBanner({ app, contract, onReady })`.** `contract` is an alternative to `functions`.
- **`createWritClient<F>(session, contract)`.** Builds a proxy with one method per key, and dotted
  keys nest:

  ```ts
  const pos = createWritClient<WritFunctions>(session, contract)
  await pos.pos.receive({ invoice_no }).result
  ```

  Each method:
  - checks the contract's inputs (required present, nothing undeclared) before calling;
  - returns a `WritCall`.

  `F` is the `WritFunctions` interface the desktop tool or the cloud generates (`writ-functions.d.ts`).

## 11. Linked workflows (the recipe stays in the developer's Writ Cloud)

A guided introduction is in [Shipping workflows](./packages.md#linked-the-recipe-stays-in-your-writ-cloud).

### Canonical JSON

Every hash and signature below is computed over **RFC 8785 (JCS)** canonical JSON, encoded as UTF-8:
- keys sorted by UTF-16 code units, recursively;
- compact separators;
- non-ASCII emitted as is;
- numbers as ECMAScript's `Number::toString` prints them (RFC 8785 §3.2.2.3), which is what
  `JSON.stringify` writes: `12.5`, `100` for `100.0`, `1e+21`, `1.5e-7`. An integer beyond 2^53 is
  the double a JSON parser reads for it.

It is the same canonicalizer the engine uses for its auto-update manifests. In Python,
`json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` is equivalent only for
documents with ASCII keys and integer numbers; the `usewrit` package implements the full rule.

Golden vectors pin the canonical bytes, `manifest_hash`, the Ed25519 test key and the envelope
signature. Every implementation must reproduce them.

### Manifest

Writ Cloud computes the manifest from a published version. It is what the visitor approves.

```ts
type WritManifest = {
  format: 'writ.manifest/v1'
  publication: string                       // pub_…
  name: string; description: string | null
  publisher: { name: string | null }
  functions: { name: string | null; inputs: { name: string; required: boolean; description?: string }[]; outputs: string[]; writes: boolean }[]
  destinations: string[]                    // sorted unique host[:port] of every literal URL in the recipe
  lan_hosts: string[]; lan_reason: string | null
  credentials: { key: string; label: string; secret: boolean; required: boolean }[]
  settings: WritSetting[]                   // §8 "Settings", values each visitor gives once; [] when none
  browser: boolean                          // the recipe has a step outside the HTTP set (api_call, login_post, navigate, return, wait)
  scripts: boolean                          // the recipe has an `evaluate` step
}
// manifest_hash = sha256 hex of canonical JSON of the manifest
```

How Writ Cloud computes it from a published recipe (the engine's fit check reads the same rules):
- `functions`: one per published function, in the order the developer picked them. `name` is the
  function name, or `null` for a function-less workflow. The other fields are those functions'
  call inputs (settings excluded), outputs and write verdict, read the same way as for a bundled
  package.
- `destinations`: the sorted, unique `host[:port]` of every literal http(s) URL under any `url` /
  `*_url` key of `entry_url`, the steps, `functions`, `api_functions` and `auth_config`.
- `lan_hosts`: the visitors' local-network hosts the developer declares at publish: single hosts,
  no ranges, no loopback.
- `credentials`: one per `{{secret:K}}` the recipe names, labelled by the developer.
- `settings`: an input in a URL's scheme or host becomes a setting automatically, as in the §9
  export; the developer labels it.
- The publish refusals are those of the engine's package checks (§8): refused step types,
  `{{file:}}`, payment fields, undeclared secrets, and caller inputs in an address. Recorded
  session values are scrubbed, as in the §9 export.

**Identifiers.**
- Publication `pub_` + 22 characters `[A-Za-z0-9]`.
- Publishable key `wpk_` + 32 characters, public by design.
- Secret key `wsk_` + 40 characters; Writ Cloud shows it once and stores it sealed.
- Versions are 1, 2, 3, … per publication, immutable.

**Signing.**
- Writ Cloud signs with Ed25519. The key is named by `kid` (`writ-pub-<yyyy>-<nn>`).
- The engine pins `kid → public key` in its binary. A test key, `writ-pub-test-2026`, is trusted
  only in test builds.
- Development and self-hosting can add keys with `WRIT_PUBLICATION_KEYS=kid:base64,…`, set by the
  machine's own user.
- `sig` is base64url without padding. `public_key` in `/v1/pub/keys` is standard base64 of the raw
  32 bytes.
- Golden vectors pin every one of these.

### Contract entry (in `WritContract.packages`)

```ts
type WritLinkedPackage = {
  format: 'writ.linked/v1'
  id: string                                // package id, as for bundled packages
  name: string
  publication: { id: string; base?: string; version?: number }  // base defaults to https://api.usewrit.app; version pins (optional)
  key: string                               // publishable key wpk_… (public by design)
  access: 'public' | 'token'                // token: every call needs a run token (getRunToken)
  publisher?: { name?: string }
  manifest: WritManifest
  manifest_hash: string
}
```

The linked contract Writ Cloud hands out is a `writ.contract/v1` file:
- its `packages` are `WritLinkedPackage`s;
- each of its `functions[]` carries `cloud: { workflow_id, function }` when the publication comes
  from a Writ Cloud workflow, so a `recommended` / `cloud` Writ Bridge (§12) can run it on Writ
  Cloud too;
- a publication uploaded from Writ desktop has no cloud workflow, so its functions carry none
  (`required` only).

### Writ Cloud public routes

The engine calls these; the browser never does.

| route | body | answers |
|---|---|---|
| `GET {base}/v1/pub/{id}/manifest[?version=N]` | none | `200 { publication, version, manifest, manifest_hash, status: 'live' }`, `404`, `410 { status: 'revoked' }` |
| `POST {base}/v1/pub/{id}/recipe` | `{ key, origin, token?, version?, daemon_version }` | `200 RecipeEnvelope`, `401` bad key, `403` origin not allowed or bad token, `404`, `410` revoked, `402` developer quota exceeded, `429` rate limited |
| `GET {base}/v1/pub/keys` | none | `{ keys: { kid, alg: 'Ed25519', public_key: base64 }[] }` (transparency; the engine PINS its keys at build) |

**`/v1/pub/{id}/recipe` checks, in order:**
1. The publication exists (`404`) and is live (`410`).
2. `key` is its publishable key (`401`).
3. `origin` is one of its allowed origins (`403`). Allowed origins are exact `scheme://host[:port]`;
   `http://localhost[:port]` is accepted only when the developer listed it.
4. In `token` mode, `token` verifies (`403`).
5. The per-key and per-IP rate limit, 600 a minute (`429`).
6. The developer's monthly delivery quota (`402`).
7. The answer is the envelope of the requested version, or the latest when none is given. A
   version that doesn't exist is `404`.

Each `200` counts one delivery for the publication's account. The answer carries
`Cache-Control: no-store`.

**Quota.** Deliveries a month per account: Free 1,000, then rising by plan. Execution is never
billed, since it runs on visitors' computers.

**Managing publications** (authenticated, the developer's own account):
- `POST /api/publications`, with `{ workflow_id, functions: (string|null)[], allowed_origins,
  access, publisher_name?, lan_hosts?, lan_reason?, credential_labels?, setting_labels? }`, creates a
  publication and publishes version 1.
- `POST /api/publications/from-package` `{ package, … }` does the same from a §8 package (Writ
  desktop's "Publish to Writ Cloud").
- `GET /api/publications` lists them with delivery counts; `GET /api/publications/{id}` shows one
  with its versions.
- `POST /api/publications/{id}/versions` re-snapshots the workflow, or takes `{ package }` for one
  uploaded from the desktop.
- `PATCH /api/publications/{id}` changes the origins, access, publisher name, labels and LAN
  hosts. A change that alters the manifest publishes a new version.
- `POST /api/publications/{id}/revoke` and `POST /api/publications/{id}/rotate-secret`.
- `GET /api/publications/{id}/contract?kind=linked|bundled` returns the contract file.

```ts
type RecipeEnvelope = {
  format: 'writ.recipe/v1'
  publication: string; version: number; manifest_hash: string
  recipe: { steps: object[]; functions: object[] | null; api_functions: object | null; auth_config: object | null; entry_url: string | null }
  issued_at: number                         // unix seconds
  kid: string
  sig: string                               // base64url Ed25519 over canonical JSON of the envelope WITHOUT `sig`
}
```

### Token mode

A run token is a JWT, HS256, signed with the publication's secret key `wsk_…`:
- header `{ "alg": "HS256", "typ": "JWT" }`;
- claims `{ pub, iat, exp ≤ iat + 3600, sub? }`.

The developer's backend mints it. The page passes it as `token` on each call. Writ Cloud verifies
it. It is never stored by the extension or the engine.

### Engine rules for a linked package

**Bases.** The engine only talks to allowed bases: `https://api.usewrit.app`, plus
`WRIT_PUBLICATION_BASES` (comma-separated, for development and self-hosting).

**Install.**
1. Fetch the manifest; it must equal the contract's (`manifest_hash`).
2. Show it in consent.
3. Store a linked stub: a workflow with no steps, marked linked, holding the publication id, the
   approved `manifest_hash` and the pinned version, with the typed credentials sealed and the LAN
   hosts approved (`via site`).

**Run** (any caller):
1. Get the envelope: from the page session's memory cache, or freshly fetched for
   `recipe_cache: 'call'`, the first call, or after `refreshRecipes`.
2. Verify:
   - the Ed25519 signature against the pinned keys;
   - `manifest_hash ==` the approved hash, else the call fails with `GRANT_STALE`, and the banner
     offers "Update";
   - the recipe FITS the manifest: the same refusals as bundled packages; secrets only from the
     manifest credentials; literal destinations ⊆ `destinations ∪ lan_hosts`; HTTP steps only
     when `browser` is false; no `evaluate` step when `scripts` is false; every manifest function
     present, none of them writing when the manifest says it doesn't. A call passes only the
     approved manifest's inputs; the binding is made from it.
3. Run it in memory on the stub, isolated as for bundled packages.
4. Store it nowhere: not the row, the trace or the logs.

**Cache.** Memory only, keyed by (publication, page session). A page session ends when the page's
port disconnects, and its entries go with it.
- `recipe_cache: 'call'` never caches.
- A run the site didn't start (the owner in the app, a schedule) fetches without a token and caches
  nothing.
- The cache holds at most 256 envelopes; the least recently used goes first.
- `writ_refresh_recipes` drops the page session's entries, through the same `session.end`.

**Errors:**

| code | when |
|---|---|
| `RECIPE_UNAVAILABLE` | network failure, or a base that isn't allowed |
| `PUBLICATION_REVOKED` | 410 |
| `NOT_GRANTED` | 401 (bad publishable key) or 403 (origin not allowed, bad or expired run token), with Writ Cloud's message |
| `GRANT_STALE` | the published manifest no longer matches the approved one |
| `QUOTA_EXCEEDED` | 402 (the developer's plan is out of deliveries) |
| `RATE_LIMITED` | 429 |

**Desktop surfaces.** A linked stub shows "Kept up to date by <publisher> from Writ Cloud". The
owner's last run that hit `RECIPE_UNAVAILABLE` or `PUBLICATION_REVOKED` shows as "Offline" or
"Withdrawn by the site" on its row in Websites.

**Publishing from the desktop.** `POST /v1/sites/packages/publish` (owner-only, needs a linked Writ
Cloud account) with `{ items, allowed_origins, access, publisher_name? }` exports like §9. It then
calls `POST /api/publications/from-package` with the device's account and answers
`{ publication, linked_contract }`.

### Wire additions

- **`writ_call`** params gain:
  - `token?: string`;
  - `recipe_cache?: 'session' | 'call'` (default `session`).
- **New page method `writ_refresh_recipes`**: drops this page session's cached recipes.
- **Host methods:**
  - `call.start` gains `token`, `recipe_cache`, `page_session` (a random id the service worker
    assigns per page port);
  - new `session.end { page_session }` is sent when the page port disconnects.
- **Engine:**
  - `POST /v1/sites/calls` gains the same three fields;
  - new `POST /v1/sites/sessions/end { page_session }`.

## 12. Writ Bridge (one object in the page and on the server)

Modes: `required` | `recommended` | `cloud`, chosen by the developer and never automatic. A guided
introduction is in the [quickstart](./quickstart.md) and [security](./security.md).

### 12.1 Signed receipts (engine → page → server)

A call may carry `challenge` (an opaque string ≤ 2048 chars that the server minted). Its finished
or error outcome always carries a `receipt` once a run took place. The engine signs the receipt
with a per-site Ed25519 key, sealed in the vault, created on first use and stable for that
(install, origin):

```ts
type WritReceipt = {
  v: 1
  origin: string
  key: string; package: string | null; function: string | null
  challenge: string | null
  outcome: 'success' | 'failed' | 'error' | 'timeout' | 'cancelled'
  error_code: string | null
  data_hash: string | null       // sha256 hex of the RFC 8785 canonical JSON of the data the page receives (null unless success)
  inputs_hash: string            // sha256 hex of (challenge or "") + "\n" + canonical JSON of the inputs the call ran with
  run_id: number; started_at: number; finished_at: number   // unix seconds
  writ: { version: string }
  device: { kid: string; alg: 'Ed25519'; public_key: string; hardware: boolean }   // public_key base64url (32 bytes); kid = first 16 hex of sha256(public_key bytes)
  sig: string                    // base64url Ed25519 over the canonical JSON of the receipt WITHOUT `sig`
}
```

**The data the page receives** is the run's `extracted_data` when the run document has one, else its
`data`. That is the same rule the native host applies.

**Wire:**
- `writ_call` params gain `challenge?`.
- The page's `finished` event gains `receipt`; an `error` event carries `receipt` when a run took
  place.
- Host: `call.start` gains `challenge`; `call.finished` and `call.error` payloads gain `receipt`.
- Engine: `POST /v1/sites/calls` gains `challenge`; new `GET /v1/sites/calls/:run_id/receipt`
  (owner-only, like every `/v1/sites` route) signs and returns the receipt of a finished site call.

**Golden vectors** hold a fixed test key, a receipt, its canonical bytes and its signature. Every
verifier (Node, Python) must accept it, and must reject any one-field change.

### 12.2 Server-minted values (server SDKs only; the engine treats them as opaque)

| value | format | content |
|---|---|---|
| user token | `base64url(json) "." base64url(HMAC-SHA256(secret, base64url(json)))` | json `{ v: 1, typ: 'user', sub, exp }` |
| challenge | same format | json `{ v: 1, typ: 'challenge', sub, key, nonce (16 random bytes, base64url), exp }`; single use: the server remembers spent nonces until `exp` |

`secret` is `WRIT_BRIDGE_SECRET`, at least 32 bytes, and never sent to the page. Node and Python
produce identical bytes for the same input; shared golden vectors pin them.

### 12.3 Page channel (developer-hosted route, same origin, `Authorization: Writ <userToken>`)

| request | body | answer |
|---|---|---|
| `POST {endpoint}` | `{ hello: { ready: boolean, granted: string[], writ_version: string \| null } }` | `204` (readiness; re-sent on change and every 60 s while polling) |
| `GET {endpoint}?wait=25` | none | `200 { commands: { id, key, inputs, options: { timeout_ms?, dry_run? }, challenge, expires_at }[] }` (long-poll) |
| `POST {endpoint}` | `{ result: { id, ok: true, data, receipt } }` or `{ result: { id, ok: false, error: { code, message }, receipt? } }` | `204` |
| `POST {endpoint}` | `{ run: { key, inputs, options } }` | `200 { data, venue: 'cloud' }` or an error (`recommended` / `cloud` only: a page call routed to Writ Cloud) |

**Server checks:**
- A command's `challenge` is minted for its `id`.
- A result is accepted only with a receipt that:
  - verifies;
  - names the expected `key` and `challenge`;
  - is signed by a device pinned for that user (below);
  - has a `data_hash` equal to the posted data.
- Anything else is `RESULT_UNVERIFIED`.

**Device pins.** A receipt carries the public key that signed it, so a signature alone proves only
that SOME key signed it: anyone can make a key and sign a receipt claiming success. The server
bridge therefore pins signers per user (or challenge subject), option `pinDevices`:
- `"first-use"` (default): the first device whose receipt verifies for a user is pinned to them,
  atomically in the store (`checkDevice`; in Redis, one script over the set
  `{prefix}devices:{subject}`). Pins never expire. A receipt from any other device is refused with
  `unknownDevice: true` until the developer approves that device (`approveDevice`), having
  confirmed out of band that it is the user's. `forgetDevices` clears a user's pins.
- a function `(userId, device) => boolean`: the developer's own registry decides;
- `"off"`: any signer is accepted. Replays and cross-site reuse are still refused, but forgery is
  not; use it only where the result gates nothing.

First use is trust on first use. A forger who answers before the user's real Writ ever has wins
that pin, so gate first enrolment as you would a new login device (an email confirmation, say).
[Security](./security.md#enrol-computers-yourself-when-a-receipt-gates-sign-in) shows the pattern.

**Page bridge rules:**
- It runs commands only for granted keys (otherwise it posts `NOT_GRANTED`).
- It runs commands only while the page is open.
- It refuses an endpoint that isn't same-origin.
- The banner is shown automatically by mode.

### 12.4 Server bridge API (Node `@usewrit/server`, Python `usewrit`; same names, snake_case in Python)

| Call | Purpose |
|---|---|
| `createWritBridge({ contract, mode, secret = env.WRIT_BRIDGE_SECRET, apiKey = env.WRIT_API_KEY, store = memory, pollSeconds = 25, cloudBase = 'https://api.usewrit.app' })` | Builds the bridge |
| `bridge.handler` | A fetch-API handler; adapters: `bridge.express()`, `bridge.next()`, Python `bridge.asgi` / `bridge.fastapi_router(path)` |
| `bridge.userToken(userId, { ttlSeconds = 3600 })` | The token the page uses |
| `bridge.user(id).<nested.key>(inputs, { timeoutMs, waitForUserMs, dryRun })` | Resolves `{ data, venue: 'user' \| 'cloud', receipt? }` |
| `bridge.<nested.key>(inputs)` | No user: Writ Cloud for `recommended` / `cloud`; `WRIT_REQUIRED` for `required` |
| `bridge.challenge({ subject, key, ttlSeconds = 120 })` / `bridge.verify(receipt, { challenge, key, origin?, data?, subject?, inputs? })` | `{ ok, outcome, reason?, device, unknownDevice? }`; `inputs`: the call must have run with exactly these (`inputs_hash`). A command the server sent is always checked against the inputs it sent |
| `bridge.online(userId)` | Whether one of the user's pages is connected and ready |
| `bridge.approveDevice(userId, device \| publicKey)` / `bridge.forgetDevices(userId)` | Pin a further device for a user; clear a user's pins (`pinDevices`, default `"first-use"`) |

**Errors:** `WRIT_REQUIRED`, `USER_OFFLINE`, `RESULT_UNVERIFIED`, `TIMEOUT`, `NOT_GRANTED`,
`CLOUD_NOT_CONFIGURED`, plus any error code from the visitor's side.
