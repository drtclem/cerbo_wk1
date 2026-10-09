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

### 2026-10-06 · T15 dashboard, audit view, admin page · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean. All screens read stored/ledger values from the API; none compute money. Audit view shows the three ✓ integrity checks. Admin page enforces whole-number stock ≥ 0 and COGS ≥ 1¢; non-admins see "Wrong role".
- **Claude spot-check of the browser numbers:** order 3 ($24.00 Magnesium, COGS $12.00) → fee (2400×75+5000)//10000 = 18¢ → payout $11.82. Matches the dashboard exactly (GMV $24.00, fees $0.18, earnings $11.82). A COGS edit on the catalog left order 3's stored COGS at $12.00, re-proving the snapshot in the UI.
- **Deferred, accepted (cosmetic):** overlapping Cancel clicks could let a slower dashboard refresh briefly re-show a just-cancelled order as pending; server state is always correct and a reload fixes the view. Stock/COGS fields stay editable during Save.

### 2026-10-06 · T16 end-to-end test & README · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean; 227 backend tests. `test_e2e.py` runs the full flow with seed users: 2× Magnesium @ $24 + 1× D3+K2 @ $18 → subtotal $66.00, COGS $33.00, fee 50¢ (Claude re-derived: (6600×75+5000)//10000 = 50), payout $32.50; decline, then pay; dashboard and audit match to the cent.
- **Claude README review (the deferred "weak README test" item, handled by reading it):** README is complete and accurate. Three fixes made: (1) the "What's stubbed" row still said "idempotent by key", stale since the T7 retry refinement; updated in README and PRD §8; (2) added a "reset the database" note, since the walkthrough's dollar amounts assume a fresh DB and earlier browser tests left orders in the dev DB; (3) relabeled the brief PDF link from "Overview slides" to "Assignment brief".

### 2026-10-06 · T18 design system, app shell, split bar · Cursor agent + verifier/reviewer
- **Result:** VERIFIED, reviewer clean; 18 frontend tests, 227 backend tests untouched. Pico replaced by hand-written tokens from `docs/ui-design.md` (Inter via `@fontsource-variable/inter`). New shared components: `SplitBar` (full + compact), `StatusPill`, `Money`, `InlineError`, `EmptyState`. Agent also ran a Playwright smoke test, including a 375px-wide viewport.
- **Claude review of `splitBar.ts`:** widths are pure display proportions of API-returned cents; labels are `formatCents` of those same cents, so the "frontend never computes the split" rule holds. The 3px minimum for the 0.75% fee segment takes its width from the other two segments proportionally.
- **Git guardrail broken again, by a different path:** despite "no branches" in the prompt, a diagram pass pushed `origin/cursor/t18-diagrams-5a7a`, and a Cursor cloud agent pushed `origin/cursor/cloud-agent-…-lneef` ("Apply local changes for cloud agent", a large diagram-prose trim). Neither was merged into `main`; both deleted from the remote. Lesson: the prompt rule stops the main agent but not every subagent or cloud agent; check `git branch -r` after each task.

### 2026-10-06 · T19 apply the design to every page · Cursor agent + verifier/reviewer, Claude screenshot review
- **Result:** VERIFIED; 22 frontend tests, backend untouched. Two-column order builder with a sticky summary and live split bar, receipt-style patient page, dashboard led by an earnings sentence, ledger-style audit with a three-item integrity checklist, dense admin table. Screenshots of every page committed in `docs/screenshots/t19/`.
- **Claude's screenshot review caught a bug the tests and reviewer missed:** on the dashboard and audit pages the split bar, the redesign's centrepiece, filled only ~7–20% of its track, and the fee sliver vanished. It rendered correctly only in the narrow order-builder panel, so the bar was measuring its own width wrongly. Fixed by switching to percentage widths with a CSS `min-width` for the fee. Lesson: unit tests on the layout math passed while the rendered picture was wrong; for visual work, someone has to look.
- **Other review fixes:** "You receive" now shows on load for every product (it was blank until a price was edited); Save buttons stay quiet until a row has unsaved changes; no wrapping in the builder table; patient shown as a label/value; color dots tie the summary figures to the bar.
- **Numbers re-checked by Claude from the screenshots:** demo order $66.00 / $33.00 / $0.50 / $32.50; product-page payouts $11.82, $8.86, $17.23, $20.68 all match the fee formula exactly.

### 2026-10-08 · Owner click-through, walkthrough review, writeup update · Me + Claude
- **My own click-through fixes:** a stale "Payment was declined" error stayed visible after choosing a different card; the patient link showed as a relative path (now a full URL); the Products page now shows "You earn per unit" with the cost and fee behind it.
- **Claude review of the repo and my walkthrough video:** found that quantity has no upper bound (a huge qty previews absurd amounts and overflows SQLite's integer column on create, a 500), orders above current stock and duplicate product lines are accepted at creation, the audit/receipt lack the payment reference and paid date, and the per-unit earnings figure can be 1¢ off at qty > 1 because the fee is rounded per order. Logged as known limitations in the writeup.
- **README:** Vite binds to `localhost`, which on a Mac can be IPv6-only, so the README's `127.0.0.1:5173` didn't load. Use `localhost:5173`.
- **Writeup:** updated for T18–T19, the git-guardrail leak via subagents, the users/roles framing, and the items above. Test counts re-run: 227 backend, 22 frontend.

### 2026-10-09 · Deploy, Phase 6 features (T20–T24), live check · Me + Claude + Cursor
- **Deploy (T20):** one Docker image (API under `/api`, built site at `/`), demo login/log out that reset the shared seed data, `POST /demo/reset` only in demo mode. DigitalOcean App Platform (smallest plan, one container) builds from a GitHub mirror of the Gauntlet repo and redeploys on every push. Claude declined to use Cerbo's real logo on a public page with a Log in button; we used an original mark and a "not affiliated" footer.
- **Planning:** I asked what a provider and a patient would want. My idea, a research donation popup per item funded by a patient round-up or the provider's margin, became D12: a single switch, 5% of the provider's margin per line, matched to a research fund per product, patient sees funds but never amounts. Plus D11 (dosing and notes written by the provider, never generated), D13 (patient removes items before paying), D14 (input limits). Claude verified every fund link; one candidate domain (Migraine Research Foundation) now serves gambling content and was dropped.
- **T21 limits and receipt:** Claude added specific builder messages for the limits (the API returned only "Invalid request"), removed "(stubbed)" from a patient-facing line, and found a T20 bug: `serve.py` built the app at import, so `uv run pytest` failed on a fresh clone without a frontend build. Fixed with `uvicorn --factory`.
- **T22 dosing and notes:** Claude added labels on the patient page ("How to take it", "Why Dr. … recommends it") and made the note a two-line box.
- **T23 donations:** Claude re-derived the README order by hand ($66.00 → fee $0.50, donations $1.20 + $0.45, payout $30.85; donation off unchanged at $32.50) and found that `DONATION_EXCEEDS_PAYOUT` fired even when the price alone was too low; the agent's own test asserted the wrong behavior. Replaced with two exact cases ($27.00/$26.80 → donation is the cause; $27.40/$27.20 → price is the cause).
- **Git guardrail, third failure:** mid-T23 the diagram subagent switched to a new branch, committed, and pushed it. Moved the rule into `.cursor/rules/workflow.mdc` and every agent file. T24 ran with no git writes (the agent over-read it as "no diagram updates"; clarified).
- **T24 patient removal:** Claude found that removing an item could leave a negative payout, which hit the database CHECK as a 500. Removal now runs the same validation as creation and returns `LINE_NOT_REMOVABLE` with a clear message; new test with exact numbers (2 × Omega-3 at $18.60 + Magnesium; removing Magnesium would leave −$0.09).
- **Live check:** Claude clicked through the deployed site as provider, patient, and admin: builder with donation and fund links, review, confirm, patient page with dosing/notes and no donation amounts, remove with confirmation, decline then pay, receipt with payment reference, dashboard, audit with the removed line and four ✓ checks, admin stock (only paid items decremented), log out reset. All numbers matched.
- **Final counts:** 266 backend tests, 40 frontend tests.
