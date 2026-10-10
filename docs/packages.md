# Shipping workflows with your site

Your site can ask the user's Writ to run three kinds of workflow:

| | **Bundled** | **Linked** | **The user's own** |
|---|---|---|---|
| What you ship | `writ-contract.json` with the full recipe | `writ-contract.json` with the manifest and a link to your Writ Cloud | Only keys and descriptions |
| Where the recipe lives on the user's computer | Installed as a workflow | Fetched when a call runs, kept in memory, never written to disk | Already theirs |
| Updates | Ship a new contract; the user confirms "Update" in one click | Edit it in Writ Cloud; the next run uses it if it stays inside what the user approved | The user's business |
| Withdrawing it | Ship a contract without it; users keep the installed copy | Revoke the publication; the next call fails everywhere | The user disconnects |
| Works offline, or with Writ Cloud down | Yes | No (`RECIPE_UNAVAILABLE`) | Yes |
| Needs a Writ Cloud account | No | Yes | No |
| Who can read the recipe | Anyone who downloads your site's files | Not public. A determined user can still capture it on their own machine | The user |
| Isolation | Walled off from the user's vault, personas and files | The same | Runs as the user's own workflow, with their personas |

All three run on the user's computer and use the same consent window, the same write
confirmations and the same local-network rules. Writ never sees the user's data or credentials in
any of them.

## Bundled: the recipe ships in your contract

This is the default. You export the contract from Writ desktop (**Add to your website**,
**Bundled**) or with `writ package export`, and serve it with your site. Each entry of
`packages` is a `writ.workflow/v1` object:

```json
{
  "format": "writ.workflow/v1",
  "id": "northwind.pos",
  "version": "1.0.0",
  "name": "Northwind POS",
  "description": "Receives supplier deliveries in the POS on your store network.",
  "inputs": { "invoice_no": { "description": "Supplier invoice number" } },
  "credentials": [{ "key": "pos_password", "label": "POS password" }],
  "settings": [{ "key": "pos_host", "label": "Your POS address", "kind": "lan_host", "example": "192.168.1.20:8080" }],
  "steps": [
    {
      "type": "api_call",
      "config": {
        "function_name": "receive",
        "method": "POST",
        "url": "http://{{pos_host}}/api/receivings",
        "headers": { "X-Pos-Password": "{{secret:pos_password}}" },
        "body_json": { "invoice": "{{invoice_no}}" }
      }
    }
  ]
}
```

A complete example contract is in [examples/writ-contract.example.json](../examples/writ-contract.example.json).
The full format and its limits are in [contract §8](./contract.md#8-installable-workflows-a-site-supplies-the-workflow-the-user-installs-it-with-one-click).

You can also describe a package in code with `definePackage()` from `@usewrit/web`, and pass it
as `package` on a function request to `connect()`. It runs the same checks the engine runs, and
throws `INPUT_INVALID` with the field at fault.

### What a package may not contain

The engine refuses, at install:

- `upload` and `wait_for_download` steps (no local files);
- AI steps (`ai_fill_form`, `ai_fill`, `ai_continue`, `ai_navigate`), which would spend the user's
  own AI key;
- `codegen` steps;
- `{{file:...}}` placeholders, and any `{{secret:K}}` or `{{vault:K}}` whose `K` is not a declared
  credential;
- payment fields;
- a URL whose scheme or host comes from a call input (use a setting);
- more than 512 KB of JSON or more than 500 steps.

The export warns you about any of these before you ship.

### Functions and keys

A workflow can have several functions (step groups with a `function_name`). Each contract function
maps one of your keys (`pos.receive`) to one package function (`receive`). Dots in keys make
namespaces in the typed client: `writ.pos.receive(...)`. Keys match `[a-z0-9][a-z0-9._-]{0,63}`.

## Linked: the recipe stays in your Writ Cloud

A linked contract ships the manifest (what the workflow does: its functions, hosts, credentials,
settings, whether it uses a browser or page scripts) and a link to a publication in your Writ
Cloud. Each user's Writ fetches the recipe when it runs a function, checks its Ed25519 signature,
checks that it fits the manifest the user approved, runs it from memory, and keeps none of it.

Publish it:

- **Writ Cloud:** on a workflow, **Use on a website**. Pick the functions, list your site's
  origins (`https://app.northwind.example`, plus `http://localhost:5173` for development), choose
  the access (Public or Token), declare the local-network hosts your users' devices will have,
  label the credentials, then Publish.
- **Writ desktop** linked to your Writ Cloud account: **Add to your website**, **Linked**,
  **Publish to Writ Cloud**.

Download the linked contract. Your page code does not change.

**Access.**

- **Public** (default): any page on the publication's allowed origins may fetch the recipe.
- **Token**: every call needs a run token your server mints with the publication's secret key
  (`mintRunToken` in `@usewrit/server`, `mint_run_token` in `usewrit`). Give the page a
  `getRunToken` function. The page keeps the token in memory only, until a minute before it
  expires. See the [quickstart, section 8](./quickstart.md#8-ship-it-linked).

**Recipe cache.** `recipeCache: "session"` (default) fetches the recipe at the page's first call
and reuses it until the page goes away. `"call"` fetches it for every call. `refreshRecipes()`
forces a fetch on the next call.

**Deliveries.** Each recipe fetch counts one delivery against your Writ plan (the Free plan
includes 1,000 a month). Running is never billed: it happens on your users' computers. When you
run out, calls fail with `QUOTA_EXCEEDED`.

**Pinning a version.** A contract can pin `publication.version`. Your users then keep that
version until you ship a contract with another.

## The user's own workflows

Without a package, you ask for keys, and the user binds each one to one of their own Writ
functions in the consent window. You never learn their workflow ids. Their functions may sign in
with the user's own Writ personas.

```ts
import { connectWrit } from "@usewrit/web";

const writ = await connectWrit();
if (!writ.available) return showInstallWrit(writ.installUrl);
const session = await writ.connect({
  app: "Northwind Retail",
  functions: [{ key: "orders.export", description: "Export your open orders", match: { host: "orders.example.com" } }],
});
const { data } = await session.call("orders.export").result;
```

`match` hints which of the user's functions to pre-select. Treat `data` like user input: the user
chose which function answers.

## Credentials: typed once, or given per call

A workflow that signs in names its secrets as `{{secret:KEY}}`. The export turns each into a
declared credential. Your contract never carries a value.

### Typed once (the default)

The consent window shows one field per credential, with its label. The user types it there, in
Writ's own window, and Writ seals it on the installed workflow. Your page never sees it. The
workflow keeps its own signed-in session between runs, so it signs in again only when the site
asks. On an update the fields are optional: a field left empty keeps the saved value. Typing
another login starts a new session.

Use this when the credential belongs to something the user has and your site does not handle: the
password of a POS on their network, a supplier portal account.

### Given per call

A credential declared with `"per_call": true` is not asked in the consent window and never stored.
Your page passes it with every call, as an input named after its key:

```bash
writ package export "Portal login" --function verify_login --key auth.verify_login \
  --call-credential password --out writ-contract.json
```

In Writ desktop's **Add to your website** (Bundled), tick **Your site gives it with each call** on
that credential instead.

```ts
await writ.auth.verify_login({ company, username, password }, { challenge });
```

The engine moves the value to that run's secret channel. It fills `{{secret:password}}` and the
session identity, like a typed login, and it is never written to the run record. Writ still keeps
the signed-in session per login between runs.

Use it when your own sign-in IS this login: each of your users brings theirs, and your form
already has it. The trade-off: the value passes through your page, so your page sees it. Do not
log it, and never send it to your server unless your server needs it anyway.

## Settings: values each user gives once

A setting is a value that differs per user but not per call: the address of their POS, their store
number. The recipe uses it like any placeholder (`http://{{pos_host}}/api/receive`). Each package
declares at most 8.

| Field | Meaning |
|---|---|
| `key` | `[A-Za-z0-9_]{1,64}`, not also an input or a credential |
| `label` | 1 to 80 characters, shown next to the field ("Your POS address") |
| `description` | At most 200 characters: where the user finds the value |
| `kind` | `"text"` (default, at most 200 characters) or `"lan_host"` (one address on the user's network) |
| `example` | At most 120 characters, the field's placeholder |
| `required` | Default `true` |

- **`lan_host`** is `host` or `host:port`: an IPv4 address, `[IPv6]` or a name, with no scheme,
  path, range or loopback. The confirmed address becomes one of the workflow's approved
  local-network hosts. Changing it replaces the old approval.
- **The user gives it**, in the consent window. Your site may suggest a value
  (`suggestSettings()`, or `settings` in `createWritBridge`). The window opens pre-filled and the
  user confirms or corrects it. Nothing is stored before they click **Install and allow**.
- **It is not a call input.** Passing it in `inputs` is `INPUT_INVALID`.
- **It is not a secret.** Use a credential for secrets.
- **Changing it**: suggest a new value (the window asks again, marked "To confirm"), or the user
  edits it in Writ desktop (Connect, Connected apps, Websites, your site, the workflow).

An input that decides which host a request goes to always becomes a setting in the export. This
is what stops a site from aiming a user's Writ at any address, call by call.

## Local-network hosts

A workflow may reach fixed hosts on the user's network, such as `192.168.1.20:8080`. Declare them
on the package as `local_network: { hosts, reason }`: at most 8 single hosts, no ranges, never the
computer itself. The consent window shows them as "This website asks to reach these devices on
your network", with your reason. The user approves them for that workflow only, in the same click.

If the address differs per user, use a `lan_host` setting instead.

A function that reaches the local network, by a fixed host or a `lan_host` setting, always runs in
`required` mode.

## A private recipe

Add `"recipe": "hidden"` to a bundled package to keep its steps out of the user's Writ:

```json
{ "format": "writ.workflow/v1", "id": "northwind.pos", "recipe": "hidden", "...": "..." }
```

From the export: tick **Keep the recipe private** in Writ desktop's **Add to your website**
(Bundled), pass `--private-recipe` to `writ package export`, or set `hide_recipe: true` on an item
of `POST /v1/sites/packages/export`.

The workflow still runs on the user's computer. But their Writ:

- shows it with no steps, in the app and in its local API (`recipe_hidden: true`);
- refuses to edit, export or document it, or copy it to Writ Cloud;
- does not let its MCP tools read it;
- keeps no step detail in its run traces.

Be clear about what this is. **It hides the recipe from the user interface and the API. It does
not encrypt it from the user's machine.** A bundled recipe is in your contract file, which anyone
can download from your site, and it is stored on the user's computer. A determined user can read
it there.

**Linked mode keeps the recipe off the machine**: it is fetched per run, held in memory and never
written to disk, and it is not in your site's public files. A user who controls their computer can
still capture a recipe while it runs. In either mode, never put your own secrets in a workflow. A
step that needs your server's secret is a call to your server, not a step of the recipe.

## Versions and updates

**Every update reopens consent.** The user approves exactly what will run, and approves again
when that changes.

- **Bundled.** Any change to a package you ship, a new `version` or any other edit, makes the
  user's installed copy out of date. On the next connect, the consent window opens as **Update**
  ("Update from 1.0.0 to 1.1.0"), again one click. Saved credentials and settings are kept unless
  the user changes them. A version that adds a required setting asks for it. `version` is at most
  32 characters and is shown to the user; bump it on every release so they can tell versions apart.
- **Linked.** A recipe edit that stays inside the approved manifest (same hosts, credentials,
  functions, write flags, step classes) is not an update: it applies at the next run, with nothing
  to confirm. A change that widens the manifest (a new host, credential, writing function, browser
  steps or page scripts) publishes a new manifest. Calls then fail with `GRANT_STALE`, and the
  banner offers **Update**, which reopens consent.
- **The user's own workflows.** When the user changes a workflow bound to your key, calls fail with
  `GRANT_STALE` until your page connects again.

Your page does not need code for any of this when it uses the banner or `createWritBridge`: they
handle `GRANT_STALE` by showing **Update**. The call still rejects with its error for your code to
handle.

## Removing what you installed

`session.disconnect()` from your page revokes your site's grant. It never removes the workflows
your site installed. Only the user can: **Disconnect** in the extension's popup asks "Also remove
the workflows this site installed?", and Writ desktop offers the same.
