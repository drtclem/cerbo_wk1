# Writeup: In-House Supplement Ordering

_Draft. Supporting detail: [`decisions.md`](decisions.md) (every decision with options and tradeoffs), [`ai-log.md`](ai-log.md) (dated record of AI use), [`prd.md`](prd.md), [`architecture.md`](architecture.md)._

## What I built

A vertical slice where a provider builds a supplement order for a patient, the patient pays Cerbo (stubbed processor), and the money is split into COGS (Cerbo), provider payout, and Cerbo's 75 bps platform fee. Every paid order can be audited to the cent: the audit view shows the stored split, the ledger rows, and three automated checks (fee matches formula, split adds up, ledger matches split). Python/FastAPI + SQLite backend, React frontend, 227 backend tests, built task by task with AI agents.

I prioritized the integrity of the money flow over breadth. Where something had to give, it was polish and features, not correctness.

---

## 1. Key decisions and tradeoffs

**Fee is 0.75% of the merchandise subtotal, deducted from the provider's payout.** The patient pays exactly the price their provider set. Alternatives were adding the fee on top for the patient (an extra line item on a clinical recommendation, and an ambiguous base) or charging it on the provider's margin only (doesn't match "75 bps on the transaction" or the GMV metric). This is the only option where the fee is exactly 0.75% of GMV and the split needs no extra rules. Tax and shipping are explicitly excluded from the fee base so adding them later can't silently change the fee.

**Integer cents everywhere, one rounding step, provider absorbs the fraction.** Money is stored and computed as integer cents; the fee rate is integer basis points. The fee is computed once per order, not per line. Per-line rounding drifts (2 × $10.10 gives a 16¢ fee per line vs. 15¢ per order). The fee is the only value that can produce a fraction of a cent, so it's the only thing rounded (half up, in integer math: `(subtotal × 75 + 5000) // 10000`). The payout is the remainder, so `subtotal = COGS + fee + payout` holds by construction. The known bias: half-cent ties always round up, which at 75 bps happens on roughly 1 in 400 orders, +0.5¢ each. Negligible, and documented rather than hidden.

**Provider sets the patient price; two guardrails.** Each line must be priced at or above its COGS, and the order's payout must be at least $0, checked by running the same split function that computes the real money. A fixed buffer (e.g. "COGS + 1¢") doesn't work because the fee scales with price: at COGS $20.00, a $20.01 price still leaves the provider owing 14¢. I considered a 1¢ minimum fee (orders under $0.67 currently incur no fee) and left it out because it breaks "fee = exactly 0.75%" for no realistic gain.

**Snapshot at order creation, plus a ledger.** Unit price, unit COGS, product name, and fee rate are copied onto the order when it's created, so a later catalog change can't rewrite a past split. The order's columns record *what was agreed*; a small append-only ledger, written in the same transaction as the payment, records *what money moved*. This costs one extra table, but makes "where did every cent go" a single query and gives refunds and payouts a natural home later (new rows, never edits).

**Payment safety in layers.** The pay step claims the order with a conditional update (`… WHERE status = 'pending_payment'`), takes stock with another (`… WHERE stock_qty >= qty`), charges, and writes the ledger, all in one transaction. Stock is taken before the charge, so an out-of-stock order is never charged. A uniqueness constraint on the ledger is a backstop. Tests fire concurrent requests at the real database: double-pay charges once, two patients racing for the last unit lets exactly one win, and pay-vs-cancel lets exactly one win.

**The database enforces the money rules too.** Strict-typed SQLite tables with CHECK constraints: the split must add up, the payout can't be negative, price ≥ COGS per line, stock ≥ 0, one ledger row per type per order. If application code ever computed a bad split, the write would fail loudly.

**Resolving an ambiguity in the brief: who "updates inventory."** The requirements say the provider dashboard should update inventory; the out-of-scope section says Cerbo holds the inventory. A provider editing Cerbo's warehouse counts is an ownership mismatch, so I split by ownership: providers manage which products they offer and at what default price; Cerbo admins manage stock and COGS. Stock is decremented at payment, not reserved at order creation (reservation needs expiry logic for abandoned orders).

**Stack: Python + FastAPI, SQLite, React.** My planning assistant recommended TypeScript + Next.js (one language, very AI-fluent). I chose Python because I can read and review it more easily, and since agents wrote most of the code, my ability to review it mattered more than single-language convenience. SQLite means zero setup for anyone cloning the repo; the code uses SQLAlchemy so moving to Postgres is a configuration change.

**Clean seams.** Auth, payments, notifications, and fulfillment are each a small interface with a fake implementation, chosen in one config file. Auth is fake (a role switcher), but role and ownership checks are real on every endpoint, because real auth would rely on exactly those rules.

---

## 2. What I cut, and what I'd do next

**Cut deliberately (per the brief or for time):** real payments, auth, email, and shipping; tax and shipping cost; catalog browsing/search; a draft order state (orders are locked at creation; to change one, cancel and rebuild); refunds; fulfillment states beyond "paid"; database migrations; component tests for the UI (UI was verified by clicking through checklists; logic like dollar parsing is unit-tested).

**Known limitations I'd fix first:**
- **Card processing fees.** Real processors charge more than 75 bps. Someone has to absorb that (provider payout, COGS markup, or Cerbo). That's a business decision the model is ready for (another ledger allocation line), but I didn't make it.
- **Payment idempotency key.** The fake treats "same order + same card + same amount" as one attempt so a patient can retry after a decline. Real processors treat a reused key as the same request regardless, so production needs a per-attempt key (e.g. `order-12-attempt-2`) recorded in the database.
- **External call inside a DB transaction.** The fake charge runs while the write lock is held. Fine for a stub; production should authorize outside the transaction, commit, capture, and reconcile via processor webhooks (which also covers "charge succeeded, database write failed").
- **SQLite serializes writes**, so the concurrency tests are gentler than Postgres would be. The guarantees come from conditional updates and constraints, which behave the same on Postgres, but I'd re-run them there.
- **Append-only is enforced in code only.** Next step: database permissions or triggers.
- **Admin stock edits set an absolute number**, so a sale at the same instant can be overwritten. Production should record stock movements (+N/−N), like the ledger.
- **Raising COGS above a provider's saved default price** leaves that default invalid until edited. Safe (the guardrail rejects it), but providers should be warned.

**Open product questions:** a price ceiling (large provider markups on supplements raise conflict-of-interest concerns), what happens when catalog costs drop on an unpaid order (who benefits?), and order expiry.

---

## 3. How I used AI

### Tools and workflow
- **Claude (claude.ai app):** planning and review. I walked through ten decisions one at a time, each with options and tradeoffs tied to the brief's goals, logged in `decisions.md`, then generated the PRD, architecture, and an 18-task build plan. During the build, Claude reviewed each task's report and, for the money-critical tasks, read the actual code line by line.
- **Cursor with five subagents:** a tester (writes failing tests first), the implementing agent, a verifier (runs everything), a reviewer (with "Blocking" rules from the architecture, like *no floats in money*), a design-critic for structural changes, and a diagrammer. A task was done only when the verifier said VERIFIED and the reviewer found no blocking issues.
- **Me:** decisions, judgment calls when the agents surfaced conflicts, clicking through the UI, and committing after every verified task.

### What worked
- **Deciding before building.** Ten explicit decisions up front meant the agents rarely had to guess, and when they did, they flagged it.
- **The review layers caught real bugs**, each of which would have survived "the tests pass":
  - The design-critic caught that SQLite silently ignores the foreign-keys setting if it runs at the wrong moment. Foreign keys would have looked on in the code but been off.
  - The reviewer caught that an absurdly large user ID crashed the server instead of returning "not logged in."
  - The framework's default request parsing silently accepted `2500.0`, `"2500"`, and `true` as integer cents, quietly undermining the "integer cents only" rule at the front door. Fixed by making request models strict.
  - Claude's review of the dollar-parsing code found that "19,99" (European format) parsed as $1,999.00, 100× the intended price, with no downstream guardrail to catch it.
  - Claude's review flagged that cancel used check-then-set, which would race with payment on Postgres. Fixed with the same conditional update as payment, plus a concurrent pay-vs-cancel test.
  - Claude pushed for the audit to *prove* integrity (the two extra flags), not just display numbers. A test that tampers with a stored fee shows the check flipping to false.
- **Agents asked instead of guessing.** The best example: my own decisions conflicted. I'd made the order ID the payment idempotency key ("same key, same result") *and* required that a declined card can be retried. The agent stopped and asked which rule wins instead of silently picking one.
- **Verifying numbers independently.** Every worked money example in the PRD was recomputed with code before building, and I spot-checked the amounts the agents reported from the running app (e.g. $24.00 order → 18¢ fee → $11.82 payout).

### What didn't go as expected, and how I course-corrected
- **A background agent went rogue on git.** Cursor created its own branch, committed one task under an unrelated message ("Planning docs; oracle: Switchboard"), and left nothing pushed since four tasks earlier. While I was fixing it, the agent ran `git reset` in the background, un-committing that task mid-cleanup. Nothing was lost (git's history showed every step), but it took three rounds to untangle. **Fix:** one agent at a time, every task prompt now says "do not create branches or run git commit/reset/push", and I own commits. The agents followed that rule for every task afterward.
- **The tester overstepped its role.** It's supposed to write tests only, but on the money module it built its own working implementation outside the repo to check its tests. Harmless in the end, but it weakens the claim that tests were written before any code existed, so I note it here rather than claim pure test-first.
- **The ecosystem had moved past my plan.** The test client now wants `httpx2` instead of `httpx`. That looked like a possible hallucinated or impostor package, so I checked: it's the real, maintainer-endorsed replacement. The Vite template now ships a different linter than the plan specified, and two packages needed peer-dependency workarounds. Lesson: verify unfamiliar package names against official sources rather than trusting *or* rejecting them on sight.
- **My own planning idea was wrong.** I proposed a flat 1¢ buffer above COGS to cover the fee; working through the numbers showed it fails because the fee grows with the price. We guard on the actual computed payout instead.
- **I overrode the AI where my context mattered more.** On stack choice (Python over the recommended TypeScript), because I'm the reviewer. On several deferred "should fix" items, accepting cosmetic ones with a written reason instead of letting the queue grow.
- **Even the planning assistant made a mistake:** while editing the decision log, it misplaced half a sentence into the wrong section. It caught this in its own consistency check before the docs reached the repo.

### Net
The agents were fast and, with verification and review built into every task, mostly reliable on correctness. The value I added was in the decisions, in noticing when two reasonable rules collided, and in keeping control of the parts where a mistake is expensive: money, concurrency, and version control.
