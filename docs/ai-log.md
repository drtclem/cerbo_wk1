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
