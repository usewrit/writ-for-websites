// Writ Bridge example: an Express server that
//   - hosts the page channel (/writ-bridge), so this server can run functions on the user's computer;
//   - runs pos.receive on the user's computer, through their open page (POST /api/receive);
//   - verifies the receipt of a call the page made itself (POST /api/lookup/*).
//
// DEMO ONLY: there is no sign-in. Every visitor is the same demo user, and /api/session hands its
// token to anyone who asks. Replace DEMO_USER and /api/session with your own authentication
// before you use any of this. See docs/security.md before a receipt gates a sign-in.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import express from "express";
import { createWritBridge, isWritBridgeError } from "@usewrit/server";

const PORT = Number(process.env.PORT ?? 3000);
// The exact origin the page is served from: receipts made on any other origin are refused.
const ORIGIN = process.env.WRIT_ORIGIN ?? `http://127.0.0.1:${PORT}`;
const DEMO_USER = "demo-user";

// Your own contract, exported from Writ desktop. The bridge accepts it parsed or as text.
const contractText = readFileSync(new URL("./writ-contract.json", import.meta.url), "utf8");

// Reads WRIT_BRIDGE_SECRET (at least 32 bytes) from the environment. `required`: functions run
// only on the user's computer, and nothing goes to Writ Cloud.
const writ = createWritBridge({ contract: contractText, mode: "required" });

const app = express();

// The page channel. Mount it before any body parser: it reads the body itself.
app.all("/writ-bridge", writ.express());

app.use(express.static(fileURLToPath(new URL("./public", import.meta.url))));
app.get("/writ-contract.json", (req, res) => res.type("application/json").send(contractText));
app.use("/api", express.json({ limit: "2mb" }));

// The token the page passes to its bridge. It names the user; WRIT_BRIDGE_SECRET signs it.
// DEMO: no sign-in. In your app, mint it only for the signed-in user.
app.get("/api/session", (req, res) => {
  res.set("Cache-Control", "no-store").json({ writToken: writ.userToken(DEMO_USER) });
});

// A server call that runs on the user's computer. The bridge sends it to the user's open page,
// which runs it through Writ and posts the result with its receipt. The bridge verifies the
// receipt before this await returns.
app.post("/api/receive", async (req, res) => {
  const invoice_no = String(req.body?.invoice_no ?? "");
  try {
    const { data, venue } = await writ.user(DEMO_USER).pos.receive({ invoice_no }, { waitForUserMs: 10_000 });
    res.json({ venue, data });
  } catch (error) {
    sendError(res, error);
  }
});

// A page call this server can trust: mint a challenge, let the page run the function with it,
// then verify the receipt the page sends back. `pending` keeps what this server expects for each
// challenge (DEMO: in memory, one process; use your session store).
const pending = new Map();

app.post("/api/lookup/challenge", (req, res) => {
  const sku = String(req.body?.sku ?? "");
  const challenge = writ.challenge({ subject: DEMO_USER, key: "pos.lookup", ttlSeconds: 120 });
  pending.set(challenge, { sku });
  setTimeout(() => pending.delete(challenge), 120_000).unref();
  res.json({ challenge });
});

app.post("/api/lookup/verify", async (req, res) => {
  const { challenge, data, receipt } = req.body ?? {};
  const inputs = pending.get(challenge);
  pending.delete(challenge);
  if (inputs === undefined) return res.status(400).json({ ok: false, reason: "unknown or expired challenge" });

  const check = await writ.verify(receipt, {
    challenge,
    key: "pos.lookup",
    subject: DEMO_USER,
    origin: ORIGIN,
    data,
    inputs, // the call must have run with exactly what this server expected
  });
  if (!check.ok) {
    return res.status(403).json({ ok: false, reason: check.reason, unknownDevice: check.unknownDevice === true });
  }
  res.json({ ok: true, device: check.device?.kid ?? null, data });
});

function sendError(res, error) {
  if (isWritBridgeError(error)) {
    // USER_OFFLINE, WRIT_REQUIRED, NOT_GRANTED, RESULT_UNVERIFIED, CONSENT_DENIED, RUN_FAILED, ...
    return res.status(409).json({ error: { code: error.code, message: error.message } });
  }
  console.error(error);
  res.status(500).json({ error: { code: "INTERNAL", message: "Unexpected error." } });
}

app.listen(PORT, "127.0.0.1", () => {
  console.log(`Writ Bridge example on ${ORIGIN}`);
});
