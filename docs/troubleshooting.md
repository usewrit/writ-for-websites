# Troubleshooting

Every failure has a stable `code`. In the page it is a `WritError` (branch with
`isWritError(error, code)`); on the server a `WritBridgeError` (`isWritBridgeError(error, code)`,
Python `is_writ_bridge_error(error, code)`). Branch on the code, never on the message.

In the page, a bridge call's error also carries `details.venue` (`"user"` or `"cloud"`), and
`details.receipt` when Writ signed the failed run.

## Errors from the user's side

These come from the extension, the native host or the Writ engine on the user's computer. The
server SDKs pass them through when a call ran there.

| Code | Cause | Fix |
|---|---|---|
| `NOT_INSTALLED` | No Writ extension answered within the detection timeout (1.5 s by default). Only in `connectWrit()`'s answer and the bridge's setup. | Show the install link (`installUrl`, or the banner does it). Ask the user to reload after installing: Chrome does not inject the extension into tabs that were already open. |
| `DESKTOP_MISSING` | The extension found no Writ desktop: not installed, or too old to register itself with the browser. | Ask the user to install Writ desktop 1.0.8 or later from https://usewrit.app/desktop. |
| `DESKTOP_OUTDATED` | The extension, Writ desktop and your library speak different protocol versions, or Writ desktop predates website workflows. | Ask the user to update Writ desktop and the extension. |
| `DAEMON_UNAVAILABLE` | Writ is not running, or the user chose **Not now** in the start window. | Ask the user to open Writ, then retry. After **Not now**, the page is not asked again until it reloads. Users can tick **Start Writ when this site needs it** in the consent window. |
| `VAULT_LOCKED` | The user's Writ vault is locked. | Ask the user to unlock Writ, then retry. |
| `CONSENT_DENIED` | The user declined the connection, a settings change, or a write confirmation, or closed a `recommended` banner. | Respect it. Offer to try again later. |
| `NOT_GRANTED` | Your origin has no grant, or no binding for that key. Also: the page channel ran a command for a key this user never granted. For linked workflows: a bad publishable key, an origin the publication does not allow, or a missing or expired run token. | Connect again (the bridge does it by itself). For linked workflows, check the publication's allowed origins and your `getRunToken`. |
| `GRANT_STALE` | The workflow changed since the user approved it: a new bundled package, a linked manifest that widened, or the user's own function changed. | Connect again. The banner shows **Update**, which reopens consent. |
| `WRITE_NEEDS_CONFIRM` | A write reached the engine without the user's confirmation. | Retry. The extension asks the user to confirm. |
| `INPUT_INVALID` | Inputs refused: a required one missing, an undeclared one, a `secret:` or `file:` key, more than 1 MB, a setting passed as an input, or a URL host chosen by an input. Also an invalid contract or package, or a function that reaches the local network under a mode other than `required`. | Fix the inputs, the contract or the mode. The message names the field. |
| `RATE_LIMITED` | Per-site limits on the user's computer: 2 runs at once, 30 a minute, 500 a day. Also 4 calls in flight per tab, or a second connect while one is open. For linked workflows, Writ Cloud's limit of 600 recipe fetches a minute. | Wait and retry. Queue calls on your side. |
| `LAN_NOT_ALLOWED` | The run needed a local-network address the user has not approved for that workflow. | Declare the host in the package (`local_network`) or use a `lan_host` setting, so the user approves it in the consent window. |
| `RUN_FAILED` | The workflow ran and failed. The message carries no selectors, URLs or stack. | Show the message and let the user retry. Check the run in Writ desktop's run history on a test computer. |
| `CANCELLED` | Your page cancelled, the tab closed, the bridge was destroyed, or the user stopped it. | Nothing to fix. |
| `TIMEOUT` | The call exceeded its timeout (default 2 min, at most 15 min). | Retry, perhaps with a larger `timeoutMs`. |
| `RESULT_TOO_LARGE` | The result exceeded 25 MB. | Return less data from the function. |
| `RECIPE_UNAVAILABLE` | Linked workflow: Writ could not fetch the recipe from Writ Cloud (offline, or a base this computer does not allow). | Let the user retry; the banner offers Retry. Ship bundled if the site must work offline. |
| `PUBLICATION_REVOKED` | Linked workflow: you withdrew the publication. | Publish it again, or stop offering the function. |
| `QUOTA_EXCEEDED` | Linked workflow: your Writ plan is out of recipe deliveries this month. On the server, also: your Writ Cloud plan is out of runs. | Raise your plan. |
| `BAD_REQUEST` | A malformed request: a bad key, option, banner option, `challenge` over 2048 characters, an endpoint on another origin, or no route answering at your endpoint. | Fix the code. The message says what. |
| `ORIGIN_NOT_ALLOWED` | The page is not `https`, or the call came from a frame, or it is on `http://localhost` / `http://127.0.0.1` while the extension's Developer mode is off. | Serve over `https` and call from the top frame. For local work, turn on Developer mode in the extension's options. |
| `INTERNAL` | Anything else, including the extension's connection to the page dropping (extension reloaded). An unknown code is kept in `details.providerCode`. | Reload the page and retry. Report it if it repeats. |

`PROTOCOL_MISMATCH` exists between the extension and the native host only; your page sees it as
`DESKTOP_OUTDATED`.

## Errors from the server bridge

| Code | Cause | Fix |
|---|---|---|
| `WRIT_REQUIRED` | A `required` function, and this user never reported Writ ready; or a call without a user (`writ.pos.lookup(...)`) in `required` mode; or your server refused to run a `required` function on Writ Cloud for a page. | Run it for a user (`writ.user(id)`), with their page open and Writ set up. |
| `USER_OFFLINE` | A `required` function, and none of this user's pages is connected with Writ ready. A command no page picked up within 15 s is taken back (the tab closed). | Ask the user to open your site. Pass `waitForUserMs` (Python `wait_for_user_ms`) to wait for them. Make sure the page created its bridge with the `userToken`. |
| `RESULT_UNVERIFIED` | A result came back without a receipt that verifies for that call: forged, replayed, altered, or signed by a device not pinned for the user (`details.unknownDevice`). | Treat the result as forged. For a new computer, confirm it out of band and `approveDevice` it. See [security](./security.md#device-pinning). |
| `CLOUD_NOT_CONFIGURED` | A `recommended` or `cloud` function has no Writ Cloud mapping, or there is no `WRIT_API_KEY`, or the mapped workflow or function does not exist. Raised when the bridge is created. | Download the contract from Writ Cloud (it carries `cloud` mappings) and set `WRIT_API_KEY`. Or use `required`. |
| `CLOUD_UNAVAILABLE` | Writ Cloud could not be reached, or answered 5xx. | Retry later. |
| `CONFIG_INVALID` | Invalid bridge options: a missing or short `WRIT_BRIDGE_SECRET`, a local-network function in a cloud mode, a contract key that starts with a member of the bridge (`user`, `verify`, ...), or a run-token secret that is not a `wsk_` key. | Fix the configuration. The message names the problem and never repeats a secret. |
| `TIMEOUT` | The call did not finish within `timeoutMs`. | Retry, perhaps with a larger `timeoutMs`. |

## `verify()` says no

`verify()` never throws for a bad receipt. Read `reason` (paraphrased below):

| `reason` is about | Likely cause |
|---|---|
| the receipt comes from another origin | The page was opened on another address than the one you pass as `origin`: `http://localhost` instead of `http://127.0.0.1`, `www.` or not, a staging host. |
| the challenge was already used | The page posted the same receipt twice, or you verified it twice. A challenge is spent by the first receipt that answers it. |
| the receipt answers another challenge / the challenge was minted for another function or subject | The page used a challenge from another attempt, or you passed a different `subject` or `key` than you minted with. |
| signed by a device this user has not registered (`unknownDevice: true`) | Another computer or browser profile, or a forgery. Approve it only after an out-of-band check. |
| the call ended "failed" (or error, timeout, cancelled) | The run happened and did not succeed. Deny. |
| the call ran with other inputs than these | The page ran the function with other values than the ones your server expects. Deny. |
| the data does not match the receipt | The page posted data other than what the function returned. Deny. |

## Common setup problems

| What you see | Why, and what to do |
|---|---|
| Nothing happens on `http://localhost` or `http://127.0.0.1` | The extension's Developer mode is off. Turn it on in the extension's options. |
| The banner keeps saying the extension is missing after install | The tab was open before the install. Reload the page. |
| The consent window never opens | Every requested key is already bound and current, so the connect resolved without one. Disconnect your site from the popup to see it again. |
| The page channel never runs server calls | The page bridge has no `userToken`, the endpoint is on another origin, the route is mounted after `express.json()`, or the token expired (status `unauthorized`: create the bridge again with a fresh token). Check `writ.status().channel` in the page. |
| Every server call is `USER_OFFLINE` with several server instances | The default store is in memory per process. Use `redisStore()` / `RedisStore`. |
| A new computer is refused after a restart that worked before | With the memory store, pins are lost on restart and the next device pins itself; on a durable store, a second computer needs `approveDevice`. |
| `createWritBridge` throws `INPUT_INVALID` about the local network | The function reaches the user's network (a fixed host or a `lan_host` setting), so it can only be `required`. |
