# Contributing

Fixes to the documentation and the examples are welcome: a wrong sentence, a broken link, an
example that does not run, a step that is missing.

- **Open an issue** for anything larger than a typo, so we can agree on the change first.
- **Open a pull request** for small fixes. Keep one topic per pull request.
- **Match the sources.** Every API name, option, error code and file name in these docs exists in
  the SDKs. If you find one that does not, that is a bug: please report it.
- **Keep the style.** Short, plain sentences. No emojis. Fictional names only (Northwind Retail,
  `app.northwind.example`).
- **Never include a secret**, a real customer name, or a private path in a doc or an example.

The wire contract in [docs/contract.md](./docs/contract.md) is the public copy of the contract the
extension, Writ desktop and the SDKs implement. Changes to it follow changes to the software; open
an issue if it disagrees with what the software does.

The SDK source lives in [usewrit/writ-sdks](https://github.com/usewrit/writ-sdks): `web/`
(`@usewrit/web`), `server-node/` (`@usewrit/server`) and `usewrit-python/` (`usewrit`). Report SDK
bugs and send SDK changes there.

Security issues: see [SECURITY.md](./SECURITY.md), never a public issue.

By contributing, you agree that your contribution is licensed under the [MIT License](./LICENSE).
