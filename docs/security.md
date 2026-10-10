# Security for integrators

This page is for developers who rely on a result from a user's computer: to show it, to store it,
or to let someone in. It covers what a receipt proves, how devices are pinned, and the one case
where you must enrol computers yourself.

To report a vulnerability, see [SECURITY.md](../SECURITY.md).

## Who could lie, and about what

| Party | Can it fake "the call on the user's computer succeeded"? | What stops it |
|---|---|---|
| Another site, or a third-party script on another origin | No | Calls are bound to the page's origin by the browser, and grants are per origin |
| A network attacker | No | TLS on your site; the call itself never leaves the computer until it reaches the sites the workflow calls |
| An old result replayed into a new flow | Not with a challenge | A single-use challenge your server minted, signed into the receipt |
| A script typed into the console, or injected into your page | Not with receipts | The server verifies the receipt's signature, challenge, data hash and inputs hash |
| Someone with their own Writ key, signing receipts for another user | Not with device pinning | The server accepts only devices pinned for that user |
| The user, on their own pinned computer, running a modified Writ | Yes, in principle | Nothing in this design. Receipts prove what that user's Writ says, not what the upstream service answered |

The last row decides how far you can rely on a receipt. When the check protects the user, or your
data hygiene (the account exists, the device is reachable, nobody replays), receipts are enough.
When it protects you against the user themselves, a receipt is not a proof about the upstream
service.

## Receipts

Every call that ran on the user's computer ends with a receipt, on success and on failure. The
Writ engine signs it with Ed25519, using a key it keeps for your site on that computer. The key is
created on first use, sealed in the user's Writ vault, and stable for that install and origin.
Each site gets its own key, so two sites cannot match the same user through their receipts.

A receipt carries ([contract §12.1](./contract.md#121-signed-receipts-engine--page--server)):

- `origin`: your site, as the browser reported it to the extension;
- `key`, `package`, `function`: what ran;
- `challenge`: the challenge your server minted, echoed as received;
- `outcome`: `success`, `failed`, `error`, `timeout` or `cancelled`, with `error_code`;
- `data_hash`: SHA-256 of the RFC 8785 canonical JSON of the data the page received;
- `inputs_hash`: SHA-256 of the challenge, a newline, and the canonical JSON of the inputs the call
  ran with;
- `run_id`, `started_at`, `finished_at`, `writ.version`;
- `device`: the signing key (`kid`, `alg: "Ed25519"`, `public_key`, `hardware`);
- `sig`: the signature over all of the above.

`verify()` in `@usewrit/server` and `usewrit` checks, in order: the signature and key id, the
function key, that the receipt carries your exact challenge, that your server minted that
challenge for this key (and subject) and it has not expired, the origin (when you pass it), the
device pin, that the challenge was never used before, that the call succeeded, the inputs hash
(when you pass `inputs`), and the data hash (when you pass `data`). It never throws for a bad
receipt. It answers `{ ok, outcome, reason, device, unknownDevice }`.

What to pass:

- **`origin`** always, in production: your page's exact origin, such as
  `https://app.northwind.example`. A receipt made on any other site, including your own staging
  site or `localhost`, then fails.
- **`subject`** when you minted the challenge for a user or an attempt.
- **`data`**, the data your page reported. Without it, you know the call ran, but not that the page
  sent you what it returned.
- **`inputs`** whenever the result says something about who the user is. Keep the values your own
  form received on the server, and pass those, not what the page reports later. A page then cannot
  run a check with one account and claim another. The hash covers exactly the inputs the page
  passed, including a credential given per call (`"per_call": true`), and never the settings the
  user stored.

Calls your server makes through `writ.user(id)` are always checked this way, with the inputs your
server sent; a result that fails is `RESULT_UNVERIFIED`.

**A failure is signed too.** `outcome: "failed"` tells you the function ran and failed. No receipt
means it never ran, or someone is hiding the receipt. Deny in both cases.

**Hashed data.** Numbers are hashed the way JavaScript prints them. An integer beyond 2^53 is
hashed as the double JSON carries, so return such values, and exact money amounts, as strings.

## Device pinning

A receipt carries the public key that signed it. A signature alone therefore proves only that some
key signed. Anyone can make an Ed25519 key and sign a receipt that claims success. Pinning ties
receipts to the user's own Writ.

The server bridge pins signers per challenge subject, with the `pinDevices` option (Python
`pin_devices`):

| Policy | Accepted signers |
|---|---|
| `"first-use"` (default) | The first device whose receipt verifies for a subject is pinned to it, atomically in the store. Afterwards only pinned devices verify. Another device gets `unknownDevice: true`. |
| a function `(subject, device) => boolean` | Your own registry decides. It may be async. |
| `"off"` | Any signer. Replays and cross-site reuse are still refused, forgery is not. Use it only where the result gates nothing. |

Pins live in the bridge's store and never expire. The default memory store forgets them on
restart, after which the next device to answer pins itself. In production use `redisStore()` /
`RedisStore`, or your own registry.

The store does the atomic work through `checkDevice(subject, publicKey, firstUse)`, which answers
`"known"`, `"pinned"` or `"unknown"`, plus `pinDevice(subject, publicKey)` and
`forgetDevices(subject)`. Implement those three if you write your own store.

### When your own sign-in comes first: first use with approval

If the user signs in with your own password check first, and only then does anything with Writ,
the default is sound: the first device to answer is pinned by someone who already proved who they
are. Mint challenges and user tokens only behind that sign-in.

When the same user turns up on another computer, its receipts come back with
`unknownDevice: true` (or `RESULT_UNVERIFIED` with `details.unknownDevice` for a call through
`writ.user(id)`). Confirm out of band that the computer is theirs, then approve it:

```ts
const check = await writ.verify(receipt, { challenge, key: "pos.lookup", subject: user.id, origin, data });
if (!check.ok && check.unknownDevice) {
  await sendDeviceConfirmationEmail(user, check.device); // your flow
  return res.status(403).json({ error: "confirm this computer from the email we sent" });
}

// later, when the user clicked the link in that email
await writ.approveDevice(user.id, device);   // the receipt's device, or its public_key

// a lost or replaced computer: forget every pin; the next device pins anew
await writ.forgetDevices(user.id);
```

Python: `await writ.approve_device(user.id, device)` and `await writ.forget_devices(user.id)`.

Never approve a device on the page's word alone: the page is what an attacker controls.

## Enrol computers yourself when a receipt gates sign-in

If a Writ receipt decides whether someone gets into your app, as the sign-in itself or as a step
of it, **do not trust a device key on first use**. Under `"first-use"`, the first receipt that
verifies pins its signer. A forger who answers first, for any user who has not used Writ yet, pins
their own key and passes every later check for that user.

Enrol each computer through a step you control instead:

1. **Your server checks a password itself** (or another factor it trusts). Never let the user's
   Writ be the password check: it would sign in with the credential it keeps and report success
   whatever was typed in your form.
2. **Your server mints a one-time enrolment challenge** bound to the signed-in account: a subject
   reserved for enrolment (`enroll:<user id>`), your function key, and a short lifetime.
3. **The page runs one function on this computer** with that challenge, and posts the data and the
   receipt back.
4. **Your server verifies the receipt** with the enrolment subject, your origin, the data, and the
   inputs it expects for this account. Then it checks the data says what it must (the account
   exists, the device answered).
5. **Your server records the device's public key** for the account in its own table.
6. From then on, your pin policy accepts only recorded devices for that account's subject
   (`user:<user id>`). An `enroll:` subject accepts any device, because only your password check
   can mint one.

Use distinct subject prefixes so a challenge minted for one purpose never answers the other. Give
the page its user token (for the page channel) only after enrolment.

Node (`@usewrit/server`):

```ts
import express from "express";
import { createWritBridge } from "@usewrit/server";

// Your own table of trusted computers: (user id, Writ public key). Example interface.
import { trustedDevices } from "./trusted-devices.js";

const ORIGIN = "https://app.northwind.example";
const ENROL_KEY = "account.whoami"; // a function of your contract that proves the account

export const writ = createWritBridge({
  contract,
  mode: "required",
  // Who may sign for a subject:
  //   enroll:<id>  any computer; only a password-checked sign-in can mint such a challenge
  //   user:<id>    only a computer enrolled for that account
  pinDevices: async (subject, device) => {
    if (subject.startsWith("enroll:")) return true;
    if (subject.startsWith("user:")) return trustedDevices.has(subject.slice("user:".length), device.public_key);
    return false;
  },
});

const app = express();
app.all("/writ-bridge", writ.express());
app.use("/api", express.json());

// 1-2. Your sign-in checks the password, then hands the page an enrolment challenge.
app.post("/api/login", async (req, res) => {
  const user = await checkPassword(req.body.email, req.body.password); // your own check
  if (!user) return res.status(401).end();
  req.session.userId = user.id;
  req.session.enrolChallenge = writ.challenge({ subject: `enroll:${user.id}`, key: ENROL_KEY, ttlSeconds: 900 });
  res.json({ enrolChallenge: req.session.enrolChallenge });
});

// 3. The page runs, on this computer:
//      const { data, receipt } = await bridge.account.whoami({ username }, { challenge: enrolChallenge });
//      await postJson("/api/writ/enroll", { data, receipt });

// 4-5. Verify, check the data, record the device, then open the page channel.
app.post("/api/writ/enroll", async (req, res) => {
  const user = await currentUser(req);
  const challenge = req.session.enrolChallenge;
  delete req.session.enrolChallenge;
  if (!user || !challenge) return res.status(401).end();

  const check = await writ.verify(req.body.receipt, {
    challenge,
    key: ENROL_KEY,
    subject: `enroll:${user.id}`,
    origin: ORIGIN,
    data: req.body.data,
    inputs: { username: user.username }, // what THIS account's call must have run with
  });
  if (!check.ok || !check.device) return res.status(403).json({ error: check.reason });
  if (req.body.data?.username !== user.username) return res.status(403).end(); // your own check of the data

  await trustedDevices.add(user.id, check.device.public_key);
  res.json({ writToken: writ.userToken(`user:${user.id}`) });
});

// 6. Later calls for this account use the user: subject, and only enrolled computers answer.
//      await writ.user(`user:${user.id}`).pos.receive({ invoice_no });
```

Python (`usewrit`):

```python
from pathlib import Path

from usewrit import create_writ_bridge

ORIGIN = "https://app.northwind.example"
ENROL_KEY = "account.whoami"


async def device_allowed(subject: str, device) -> bool:
    kind, _, user_id = subject.partition(":")
    if kind == "enroll":
        return True  # only a password-checked sign-in mints an enroll: challenge
    if kind == "user":
        return await trusted_devices.has(user_id, device.get("public_key"))
    return False


writ = create_writ_bridge(Path("writ-contract.json"), mode="required", pin_devices=device_allowed)


# after your own password check succeeded for `user`
def enrolment_challenge(user) -> str:
    return writ.challenge(f"enroll:{user.id}", ENROL_KEY, ttl_seconds=900)


async def enrol(user, challenge: str, data, receipt) -> str | None:
    check = await writ.verify(
        receipt,
        challenge=challenge,
        key=ENROL_KEY,
        subject=f"enroll:{user.id}",
        origin=ORIGIN,
        data=data,
        inputs={"username": user.username},
    )
    if not check.ok or not check.device:
        return None
    if not isinstance(data, dict) or data.get("username") != user.username:
        return None
    await trusted_devices.add(user.id, check.device["public_key"])
    return writ.user_token(f"user:{user.id}")
```

Notes on this pattern:

- With a function policy, the bridge does not read its store's pins, so `approveDevice` and
  `forgetDevices` have no effect on who verifies. Add and remove rows in your own table instead,
  and cap how many computers one account may enrol.
- The enrolment challenge is single use. A user on a second browser or computer enrols it the same
  way, by signing in there.
- The page runs the enrolment call with a bridge created without a `userToken`. Once enrolment
  returns the token, call `destroy()` on that bridge and create it again with
  `createWritBridge({ contract, app, mode, userToken })` to open the page channel.
- Serve the page at exactly the origin you verify. `http://127.0.0.1:8000` and
  `http://localhost:8000` are different origins.
- Under `required` mode, nothing goes to Writ Cloud. Under `recommended`, decide for yourself what
  happens when no enrolled computer is online; the bridge never falls back on its own.

## What a receipt cannot prove

It proves that the Writ install pinned for this user ran your function for your site, with your
challenge, with these inputs, and returned exactly this data. It cannot prove that the user did not
modify their own Writ on their own computer. If you must hold up against the user themselves, the
proof has to come from the upstream service, not from the user's machine.

## What the extension and Writ never do

- The extension reads no page content, DOM or cookies. Its content scripts define `window.writ`
  and relay messages your page sends on purpose.
- The extension holds no credentials, makes no network requests, and sends nothing to Writ's
  servers or to you. Function inputs and results travel only between your page and Writ desktop on
  the same computer, after the user's consent.
- Your page never sees the credentials a user typed in the consent window, their Writ vault,
  their saved sign-ins or their sessions.
- A workflow your site installed never reads the user's vault, personas or files.
- Error messages that reach your page carry no selectors, URLs or local-network addresses, and
  progress events carry no step labels.
- Writ never starts without the user: the start window, or the "Start Writ when this site needs
  it" box the user ticked for your site.

## Your server's side

- **`WRIT_BRIDGE_SECRET`** signs user tokens and challenges (HMAC-SHA256). At least 32 random
  bytes, never sent to the page. Rotating it logs every page out of the bridge.
- **User tokens** identify the user to the page channel. Mint them only for the signed-in user and
  keep them short (`ttlSeconds`, default 3600).
- **Same origin.** The page bridge refuses an endpoint on another origin, and the channel answers no
  CORS.
- **Page calls routed to Writ Cloud** (`recommended` / `cloud`) spend your plan for any signed-in
  user. Gate them with `authorizeRun(userId, key, inputs)` (Python `authorize_run`).
- **Treat `data` like user input**, even when the receipt verifies. It is what the user's computer
  returned.
- **Linked workflows in token mode** use the publication's `wsk_...` secret key to mint run tokens.
  Keep it on your server, behind your own sign-in.

## Reporting a vulnerability

Email **security@usewrit.app**, or open a private advisory from this repository's Security tab.
Never in a public issue. Details: [SECURITY.md](../SECURITY.md).
