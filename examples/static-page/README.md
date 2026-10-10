# Static page example

One HTML file, no build step and no server code. It loads `@usewrit/web` 0.2.0 from jsDelivr,
creates a Writ Bridge in `required` mode, lets the visitor send their POS address to Writ as a
setting, and calls `pos.lookup` on the visitor's computer.

Without a server, nothing checks the receipt. Use this example to see the banner, the consent
window and a call. Use [node-express](../node-express/) or [python-fastapi](../python-fastapi/)
for anything your server must trust.

## Run it

1. **Add a contract.** Export your own `writ-contract.json` from Writ desktop (**Connect**,
   **Connected apps**, **Websites**, **Add to your website**) or with `writ package export`, and
   put it next to `index.html`. The page calls the key `pos.lookup` and suggests the setting
   `pos_host`; edit those names in `index.html` to match your contract.

   To see the shape first, copy the example contract. It describes a fictional POS, so the
   install and consent work but the run itself fails:

   ```bash
   cp ../writ-contract.example.json writ-contract.json
   ```

2. **Serve the folder on 127.0.0.1:**

   ```bash
   python3 -m http.server 8080 --bind 127.0.0.1
   ```

3. **Turn on Developer mode** in the Writ extension's options, so `http://127.0.0.1` pages may
   connect. Writ desktop 1.0.8 or later must be installed.

4. **Open <http://127.0.0.1:8080>**, typed exactly so.

## What you will see

1. The Writ banner at the top of the page, if the extension or Writ desktop is missing, or if Writ
   is not running.
2. "Install Northwind POS (one click)", which opens Writ's consent window. It shows the site, the
   two functions, the POS password field and the POS address setting. Click **Install and allow**.
3. The output shows `ready: true` and the bridge status.
4. **Send to Writ** reopens the consent window as an update with your address pre-filled. Confirm
   it there.
5. **Look up** runs `pos.lookup` on your computer and shows where it ran (`venue: "user"`) and the
   id of the key that signed the receipt.

To start over, open the extension's popup, **Disconnect** the site and choose **Remove them**.
