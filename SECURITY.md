# Security policy

This repository holds documentation and examples for Writ for websites: the Writ browser extension,
Writ desktop's website features, and the `@usewrit/web`, `@usewrit/server` and `usewrit` SDKs.
What the design protects, and what it does not, is described in
[docs/security.md](./docs/security.md).

## Reporting a vulnerability

Please report security issues privately. Do not open a public issue for a vulnerability.

Use either channel:

1. **Email:** `security@usewrit.app`.
2. **GitHub private advisory:** **Report a vulnerability** under this repository's
   [Security tab](https://github.com/usewrit/writ-for-websites/security/advisories/new).

Include what is affected (the extension, Writ desktop, an SDK and its version, or an example
here), your browser and operating system, steps to reproduce or a proof of concept, and the
impact you believe it has. Never include real credentials, secrets or user data; redact them.

We aim to acknowledge a report within 3 business days and to share a first assessment within 10
business days. We coordinate disclosure with you, and credit you in the advisory unless you ask
us not to.

## In scope

- The extension letting a page act without the user's consent, choose its own origin, reach a
  local-network host the user did not approve, or read credentials, results of other sites, or
  page content.
- Writ starting without the user's consent.
- A site's installed workflow reading the user's vault, saved sign-ins, personas or files.
- A forged, replayed or altered receipt that `verify()` accepts.
- An example in this repository that teaches an unsafe pattern.

## Out of scope

- A user who modifies their own Writ on their own computer and signs what they like. Receipts
  cannot prove anything against that, and the documentation says so.
- Reading a bundled or private (`"recipe": "hidden"`) workflow on the computer it was installed
  on. Hidden means hidden from Writ's interface and API, not encrypted.
- The demo routes in `examples/`, which have no sign-in on purpose and are marked as such.

SDK issues that are not security issues belong in
[usewrit/writ-sdks](https://github.com/usewrit/writ-sdks/issues).
