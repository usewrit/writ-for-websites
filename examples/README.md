# Examples

| Example | Stack | Shows |
|---|---|---|
| [static-page](./static-page/) | One HTML file, the `@usewrit/web` script tag | The banner, the consent window, a setting, a call on the visitor's computer |
| [node-express](./node-express/) | Express + `@usewrit/server` | The page channel, a server call on the user's computer, challenge and `verify()` |
| [python-fastapi](./python-fastapi/) | FastAPI + `usewrit` | The same, in Python |

Every example needs your own `writ-contract.json`, exported from Writ desktop (**Connect**,
**Connected apps**, **Websites**, **Add to your website**) or with `writ package export`.

[writ-contract.example.json](./writ-contract.example.json) shows the shape: a bundled package for
a fictional POS, with two functions (`pos.receive` writes, `pos.lookup` reads), a credential typed
once (`pos_password`), and two settings (`pos_host`, an address on the user's network, and
`store_no`). It is adapted from the SDK test fixtures. It installs and opens the consent window,
but its runs fail: there is no such POS. Use it to read, then replace it with yours.

All three serve the page on `http://127.0.0.1`. Turn on **Developer mode** in the Writ
extension's options first, and open the page at exactly the address the example prints.
