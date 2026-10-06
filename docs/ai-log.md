# AI Usage Log

_Running notes for the "How you used AI" section of the writeup. Add an entry whenever AI helped notably, got something wrong, or needed a course correction. Short and honest beats polished: the brief explicitly values candor about where AI misled you._

## How the work is split
- **Claude (app):** problem framing, decisions, PRD, architecture, task breakdown → `docs/`.
- **Cursor agent + subagents:** implementation, following `.cursor/rules/workflow.mdc` (tester → implement → verifier → reviewer → diagrammer).

## Entry template
```
### YYYY-MM-DD · T# or topic · Tool (Claude / Cursor agent / subagent name)
- What I asked:
- What happened:
- Worked / didn't:
- What I changed or overrode, and why:
```

---

## Entries

### 2026-10-05 · Planning (D1–D10) · Claude
- **What I asked:** Walk me through the big decisions one at a time, with options and tradeoffs tied to the brief's goals, and log them for the PRD.
- **Worked:** Turned an open-ended brief into 10 explicit decisions (`decisions.md`), then generated `prd.md`, `architecture.md`, `tasks.md`. Surfaced issues I hadn't considered: per-line vs. per-order fee rounding drift, the price = COGS → negative payout bug, card processing fees exceeding 75 bps, and the brief's contradiction about who "updates inventory."
- **Where I overrode it:** Claude recommended TypeScript + Next.js; I chose Python + FastAPI because I can read and review Python more easily, and I'm the one checking what the agents write.
- **Where my idea needed correcting:** I proposed a fixed 1¢ buffer above COGS to cover the fee. Claude showed it fails because the fee scales with price (COGS $20.00, price $20.01 → fee 15¢ → payout −14¢). We kept a check on the actual computed payout and logged a 1¢ *minimum fee* as a later option.
- **Where AI made a mistake:** While editing the decision log, Claude split a sentence about a price ceiling and left half of it stranded at the end of a different section. Claude caught it during its own consistency check and fixed it before the docs went into the repo.
- **Verification:** Every worked money example in the PRD was recomputed with code before committing; all matched to the cent.

### 2026-10-05 · Things to watch for in the build
- The architecture flags one API Claude wasn't sure exists (SQLAlchemy's `sqlite_strict` table option) with a fallback. Record here whether Cursor's version worked.
- Watch for floats creeping into money code (e.g. `price * 100`) — the reviewer should catch these as Blocking.

### 2026-10-05 · T0 scaffold · Cursor agent + verifier/reviewer/diagrammer
- **What happened:** Workflow ran as designed: verifier VERIFIED, reviewer's first pass found 4 real issues (leftover Vite template dir, Ruff import roots, Node version range, `.hypothesis/` missing from `.gitignore`), all fixed; second pass clean.
- **Environment surprises:** `uv` wasn't installed (installed via Homebrew); machine default Python is 3.14, so backend pins 3.12 in `.python-version`. `uv run pytest` couldn't import `app` until the backend was made an installable package (Hatchling).
- **Unfamiliar dependency, verified:** the agent used `httpx2` instead of `httpx` for FastAPI's TestClient. It looked like a possible hallucination or typosquat, so I checked: Starlette's maintainer added httpx2 support to the TestClient and plain `httpx` now triggers a deprecation warning; many projects have made the same switch. Legitimate.
- **Tooling drift:** the current Vite React TS template ships Oxlint; T0 specified ESLint, so the agent used ESLint 10. `npm install` crashed resolving Vitest peers on npm 10.9.2; `--legacy-peer-deps` created the lockfile, and plain `npm install` works afterward.
- **Lesson:** library ecosystems had moved past what the plan assumed (httpx → httpx2, ESLint → Oxlint). Worth checking unfamiliar package names against official sources rather than trusting or rejecting them on sight.

### 2026-10-05 · T1 money module · Cursor agent + tester/verifier/reviewer
- **Result:** VERIFIED, reviewer clean. 22 money tests including every PRD §6.4 example, the 2 × $10.10 per-order rounding case, validation order, a Hypothesis property test of the split invariant, and an AST-based test proving `money.py` imports nothing from FastAPI, SQLAlchemy, or `app`.
- **Reviewed by Claude line by line:** integer-only math (`//`, no floats/Decimal/round), fee formula exactly as specified, payout as remainder, validation order matches the architecture.
- **Process wrinkle:** the tester subagent wrote a working implementation *outside the repo* to check its own tests, which goes beyond its "tests only" role. Harmless here (the real module was written separately and no stray file landed in the repo), but it weakens the "tests written before code, failing first" story. Watch for this in later tasks; tighten the tester's instructions if it repeats.

### 2026-10-05 · T2 database, models, seed · Cursor agent + design-critic/verifier/reviewer
- **Result:** VERIFIED, reviewer clean. Six STRICT SQLite tables; 14 DB tests prove the database itself rejects bad data (negative stock, qty 0, price below COGS, a split that doesn't add up, negative payout, duplicate ledger row, unknown status/role/entry type, non-integer money, dangling foreign keys) and that `BEGIN IMMEDIATE` takes the write lock.
- **Planning uncertainty resolved:** the architecture hedged on whether SQLAlchemy's `sqlite_strict` option exists. It does (documented since 2.0.37), so the `typeof` CHECK fallback wasn't needed. Flagging uncertainty in the plan, with a fallback, worked better than asserting a guess.
- **Design-critic earned its keep:** it caught that `PRAGMA foreign_keys` is silently ignored if run inside a transaction, so pragmas now run on the raw connection after autocommit is disabled. Without this, foreign keys could have been "on" in the code but off in practice.
- **Agent's own test bug:** the first "seed doesn't commit" test opened a second connection, which blocked on the write lock and timed out. The agent diagnosed it and rewrote the test to roll back the same session. Good example of the concurrency setup working as intended, surfacing in a test.
- **Reviewed by Claude:** schema constraints match architecture §5, including the DB-level split invariant and `UNIQUE(order_id, entry_type)` on the ledger.

### 2026-10-05 · T3 auth seam · Cursor agent + design-critic/verifier/reviewer
- **Result:** VERIFIED, reviewer clean on second pass. `X-User-Id` identifies the caller; `require_role` (403) and `require_order_access` (404, so other users' orders aren't revealed to exist) are ready for later endpoints. App startup now creates and seeds the database, closing the wiring T2 deferred.
- **Reviewer catch:** an `X-User-Id` larger than SQLite's 64-bit integer limit crashed with a 500 instead of a clean 401. Fixed by validating before the query. Good example of the reviewer finding an edge case neither the plan nor the tests anticipated.
- **Plan gap filled sensibly:** the architecture defined the error envelope but not the auth error codes. The agent chose `UNAUTHENTICATED` / `FORBIDDEN` / `NOT_FOUND`, and design-critic said to log the choice rather than edit the approved architecture doc.

### 2026-10-05 · T4 catalog & provider product list · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean. Default prices are validated with the same `validate_order` used for real orders (at qty 1), so the guardrail can't drift from the money math.
- **Real catch (correction):** Pydantic's default "lax" mode silently converted `2500.0`, `"2500"`, and `true` into integer cents, and `1` into a boolean. That would have let floats and strings into the money path despite the "integer cents only" rule. The request model is now strict. Lesson: a framework's convenience defaults can quietly undermine a core invariant; the "no floats" rule had to be enforced at the API boundary too, not just in the money module.
- **Plan gap filled:** malformed requests return `VALIDATION_ERROR` / "Invalid request" in the standard error envelope; the architecture didn't name this code.

### 2026-10-05 · T5 order preview · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean. Preview runs the real `validate_order`/`compute_split` with COGS read from the catalog (never trusted from the client) and writes nothing; tests prove row counts are unchanged after success and error.
- **Plan gap filled:** chose the message "Product is not available for this provider." for `PRODUCT_UNAVAILABLE` (architecture named only the code). Unknown, not-on-list, and disabled products deliberately share one error so the response doesn't reveal which products exist for other providers.
- **Deliberate behavior:** quantity above stock still previews; stock is enforced at payment (D6).

### 2026-10-05 · T6 create / view / cancel orders · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean. Orders snapshot product name, unit price, unit COGS, and fee rate at creation; reads use only stored amounts, and tests prove later catalog changes don't alter existing orders (AC2.5). Notifier is called only after commit, and a notifier failure doesn't lose the order.
- **Plan gaps filled:** patient link is the relative path `/orders/{id}` (no public host configured); chose `INVALID_PATIENT` ("Patient must be a patient user.") and the message "Order cannot be cancelled." for `ORDER_NOT_CANCELLABLE`.
- **Claude review note:** cancel is check-then-set (`if status != pending: …; status = cancelled`). Safe on SQLite because `BEGIN IMMEDIATE` holds the write lock from the read onward, but on Postgres it could race with a concurrent payment, the exact pattern D5 rejected. Folded into T8: make cancel a conditional `UPDATE … WHERE status = 'pending_payment'` and add a concurrent pay-vs-cancel test.

### 2026-10-05 · T7 payment seam: idempotency vs. retry conflict · Cursor agent (asked) + Claude
- **Agent surfaced a real design conflict:** D5 made the order ID the payment idempotency key ("same key → same result"), but AC3.3 requires a declined card to be retryable. Under a strict reading, the first decline would be replayed forever and block the retry.
- **Decision:** the fake replays only the *same attempt* (same key + amount + payment method). An approval is permanent for that key; a stored decline followed by a different payment method counts as a new attempt.
- **Why:** keeps both guarantees that matter (a paid order is never charged twice; double-clicks are harmless) and lets patients recover from a decline. Double-pay protection doesn't rely on the fake alone: the DB's conditional `UPDATE … WHERE status = 'pending_payment'` enforces it too.
- **Known divergence, for the writeup:** real processors (e.g. Stripe) treat a reused key as the same request regardless of parameters. In production the key should be per attempt (e.g. `order-12-attempt-2`), with attempts recorded in the DB. Not built here.
- **Lesson:** the planning docs had two rules that were each reasonable but conflicted at the edges; the agent asked instead of silently picking one.

### 2026-10-05 · T7 payment seam (built) · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean. `FakePaymentProvider` built to the retry rule decided above; the only construction site is `config.build_payment_provider`, so swapping in a real processor touches one place (G2).
- **Details chosen by the agent:** approval ref `fake_{idempotency_key}`; decline reason "Card declined." After a decline, a different payment method *or* a different amount counts as a new attempt; an approval stays sticky for the key.
- **Docs kept in sync:** architecture §8, decisions D5/D10, and the T7 checkbox were updated to state this rule, so later reviews don't flag it as a violation of the original "same key → same result" wording.

### 2026-10-05 · T8 pay endpoint (+ cancel race fix) · Cursor agent + verifier/reviewer, Claude line-by-line review
- **Result:** VERIFIED, reviewer clean. One DB transaction per payment: claim the order (`UPDATE … WHERE status='pending_payment'`), take stock (`UPDATE … WHERE stock_qty >= qty`), charge, write the 4 ledger rows from the *stored* split, commit, then ship. Decline or stock miss rolls back everything; nothing is charged for an out-of-stock order because stock is taken before the charge.
- **Concurrency tests (threads, file-based DB):** double pay → one charge, one receipt; last probiotic → exactly one order pays, stock ends at 0; pay vs. cancel → exactly one wins, and if cancel wins nothing is charged or written.
- **Claude-requested change, folded in:** `cancel_order` moved from check-then-set to the same conditional update as pay, closing a race that would have mattered on Postgres (flagged during the T6 review).
- **Claude review notes:** ownership is checked before payment (patient-only role + must be this order's patient; others get 404). If a charge succeeds but the commit fails, a retry replays the stored approval from the fake rather than charging again, so the per-attempt idempotency design (T7) also covers the charge-then-crash gap for this build.
- **Plan gaps filled:** messages "Payment was declined." / "Not enough stock." / "Order cannot be paid." A request that loses the claim race re-reads the order and returns the winner's receipt (if paid) or 409 (if cancelled).
- **Known tradeoff (already in architecture §7):** the fake charge runs inside the DB transaction, holding the write lock during the call. Fine for a stub; production would authorize outside the transaction and reconcile via webhooks.

### 2026-10-05 · T9 dashboard & audit · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean. Dashboard headline totals (GMV, fees, earnings) are summed from the ledger; per-order rows and units come from stored order snapshots; cancelled orders excluded; provider sees only their own data. Audit returns lines, split, ledger rows, and `recomputed_fee_matches`. Both routes read-only.
- **Claude review note:** the audit's only automated check was the fee formula (AC4.4). It didn't check that the ledger matches the stored split (AC4.3) or that the split adds up, which are the strongest "every cent accounted for" signals. Requested two extra flags, `ledger_matches_split` and `split_adds_up`, as a small follow-up.
- **Follow-up done:** `split_adds_up` and `ledger_matches_split` added (VERIFIED, reviewer clean). A test that deliberately shifts a stored fee after payment shows `ledger_matches_split` flipping to false, so the check actually detects tampering rather than always returning true. Architecture, PRD AC4.4, and tasks updated (owner-approved) to describe the three flags.

### 2026-10-06 · T10 admin stock & COGS · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean; backend complete (225 tests). Admin can set stock and/or COGS (omitted fields untouched); non-admins 403; COGS changes don't alter existing orders (re-proves AC2.5). Reuses existing `VALIDATION_ERROR` / `NOT_FOUND` codes.
- **Two edge cases noted by Claude (documented, not fixed):**
  - Raising COGS above a provider's saved default price leaves that default invalid. The order builder will pre-fill a price that's rejected with `LINE_BELOW_COGS` until the provider edits it. Safe (the guardrail catches it) but slightly awkward; a production version might flag affected providers or re-validate defaults when COGS changes.
  - Admin stock edits set an absolute number. If a payment decrements stock at the same moment, the admin's value wins (a "lost update"). Acceptable for a manual restock screen; production would use stock adjustments (+N/−N) recorded as movements, like the ledger.

### 2026-10-06 · T11 frontend foundation · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean. Role switcher, nav by role, generated API types, fetch client, and `lib/money.ts`. Agent also clicked through role switching in a real browser.
- **Claude review of `money.ts`:** correct approach. Dollars→cents is pure string manipulation (split on ".", pad the fraction, concatenate digits), so no float ever touches a price. Better than the reviewer's string-scan test for `* 100`, which only catches one spelling of the bug.
- **Edge case found by Claude:** commas are stripped *anywhere*, so a European-style "19,99" parses as $1,999.00 (100× the intended price). No guardrail catches it (it's above COGS, and there's no price ceiling). The review-and-confirm screen would show $1,999.00, but it's an easy typo to miss. Fix folded into T12: accept commas only as thousands separators in valid positions (`1,234.56` ok; `19,99` and `1,23` rejected).
- **Tooling:** `openapi-typescript` 7 still declares a TypeScript 5 peer, so `frontend/.npmrc` sets `legacy-peer-deps=true` (same family of peer-dependency friction as T0).

### 2026-10-06 · T12 provider product list page (+ comma fix) · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean. Product list with stock status, enable toggle, default-price edit with a live "you'd receive $X at qty 1" from the backend preview (no split math in the browser), and API errors shown inline.
- **Comma fix from T11 review done:** commas accepted only as thousands separators; "19,99", "1,23", "1,2345" rejected, with Vitest cases.
- **Agent clicked through it in a real browser** and cleaned up after itself (restored the seed catalog). Claude spot-checked its displayed number: $25.00 price on Magnesium (COGS $12.00) → fee 19¢ → payout $12.81, matching the screen exactly.
- **Thoughtful UI detail from the agent:** the enable toggle saves the *last saved* price, not an unsaved draft in the text field, so toggling can't silently persist a half-typed price.

### 2026-10-06 · T13 order builder (builder → review → created) · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean on second pass. The split shown at every step comes only from `POST /orders/preview`; Confirm sends exactly the previewed product, qty, and unit price, so what the provider reviews is what gets created. Pricing errors render on the offending line; order-level errors (e.g. `NEGATIVE_PAYOUT`) show once and block Continue.
- **Reviewer catch:** the first version showed only unit amounts; for qty > 1 the line needed line total, line COGS, and line margin from the preview. Fixed (2 × Magnesium → $48.00 / $24.00 / $24.00).
- **Agent's choices:** patient picker uses `GET /users` filtered to patients (no patients endpoint exists); all three steps on one route. Browser testing created and then cancelled orders 1–2 for Jane Doe, leaving stock unchanged.
- **Deferred should-fixes, triaged by Claude:**
  - Fixed in T14 prompt: Continue disabled with no explanation; a failed re-preview kicking the provider from review back to the builder.
  - Accepted as-is: leaving the page mid-Confirm can still create the order (correct: the server request completed, and it shows on the dashboard as pending); `formatCents` could throw on an unsafe integer (the backend never returns one; money columns are SQLite integers far below 2^53 cents).
- **Note:** the automated "Copy link" click failed only because the test browser window wasn't focused (a clipboard-permission quirk of automation), not a code bug.

### 2026-10-06 · Git workflow incident (between T12 and T14) · Cursor background agent
- **What happened:** a Cursor agent created its own branch (`cursor/admin-catalog-and-provider-products`), committed T13 under an unrelated message ("Planning docs; oracle: Switchboard"), and nothing after T9 was pushed. While fixing it, the agent ran `git reset HEAD~1` in the background, un-committing T13 mid-cleanup and blocking branch switches.
- **Resolution:** stopped the agent, re-committed T13, fast-forwarded `main`, pushed, deleted the stray branch. No work lost (git's reflog showed every step). Also set a global git identity; earlier commits had used an auto-guessed address.
- **Lesson:** agents need explicit guardrails on version control. Going forward: one agent at a time, start each task on `main` (`git branch --show-current`), and the human owns commits and pushes.

### 2026-10-06 · T14 patient order, pay, receipt (+ T13 fixes) · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean. My orders → order page (items, total, "Prices set by your provider on {date}") → pay with OK or decline test card → receipt. Decline and out-of-stock show the API's message and leave the order payable; Pay is disabled while a request is in flight (the backend is idempotent anyway). The page never computes money.
- **T13 fixes done:** disabled Continue now explains why ("Pick a patient", "Add at least one item", "Fix the errors above", "Checking prices"); a failed preview on the review step stays on review.
- **Agent stayed inside the git guardrail:** told "do not create branches or run git commit/reset/push", it left everything uncommitted on `main`.
- **Deferred, accepted:** a malformed date like `2026-02-31` would render as "Feb 31". Not reachable: the server generates `created_at` itself.
- **Browser check:** the agent paid order 3 for Jane Doe after a decline and an out-of-stock attempt (stock temporarily set to 0 via admin, then restored to 50).
