# UI design brief

_Owner-approved direction for the interface polish tasks (T18–T19). Frontend only: no API, backend, or money-logic changes._

## Who and what

Providers in functional-medicine and cash practices build supplement orders inside Cerbo, their EHR; patients pay; Cerbo admins manage stock. The interface should feel like a calm, trustworthy part of a clinical product: Cerbo's brand, not a generic demo. The one thing that makes this product different is **the money split**, so that's where the design spends its boldness.

## Signature element: the split bar

One reusable component, `SplitBar`, shows where an order's money goes as a single horizontal bar divided into three segments, proportional to the amounts the API returned:

```
Patient pays $66.00
[████████████████ COGS $33.00 ████████████████|▏|████████ You receive $32.50 ████████]
                                              fee $0.50
```

- **COGS** = neutral slate (Cerbo's cost); **platform fee** = Cerbo blue; **you receive** = Cerbo magenta (the only place magenta is used in the app).
- Segment widths are display proportions of cents the API already returned (e.g. `cogs / subtotal`). That's drawing, not computing the split, so the architecture rule "the frontend never computes the split" still holds. Labels always print the API's cents via `formatCents`.
- The fee is ~0.75% and would be invisible: give it a minimum visible width (3px) and label it outside the bar. Honest about how small Cerbo's cut is.
- Used in: order builder (live, updates as the preview returns; the only animated element in the app, a ~200ms width transition, disabled under `prefers-reduced-motion`), review step, audit page, and dashboard totals. A compact version (no labels, 6px tall) in dashboard paid-order rows.

## Tokens

| Token | Value | Use |
|---|---|---|
| `--ink` | `#101828` | Primary text |
| `--ink-soft` | `#475467` | Secondary text, labels |
| `--line` | `#EAECF0` | Borders, table rules |
| `--canvas` | `#F9FAFB` | Page background |
| `--surface` | `#FFFFFF` | Panels, tables |
| `--blue` | `#1570EF` (hover `#175CD3`, tint `#EFF8FF`) | Primary actions, links, fee segment |
| `--magenta` | `#D70073` (tint `#FDF2FA`) | "You receive" only |
| `--slate` | `#98A2B3` | COGS segment |
| `--good` / `--warn` / `--bad` | `#067647` / `#B54708` / `#B42318` | Paid / pending / errors |

- **Type:** Inter (via `@fontsource-variable/inter`, no CDN), one family. Scale: 13 / 15 (body) / 18 / 24 / 32. Weights 400, 500, 600. **All money uses `font-variant-numeric: tabular-nums`** and right alignment in tables, so columns of cents line up.
- **Shape:** 8px radius on panels and inputs, 6px on buttons, 999px on status pills. Borders, not shadows (one soft shadow allowed on the sticky order summary only).
- **Spacing:** 4px base (4, 8, 12, 16, 24, 32, 48).

## Layout

- **App shell:** a white top bar with the Cerbo-style wordmark ("Cerbo" + "Supplements") on the left, nav in the middle, and the **demo role switcher on the right, visibly marked as a demo tool** (dashed border, label "Viewing as"), since login is a stub. Content left-aligned, max width 1120px, on the light canvas.
- **Order builder:** two columns on desktop. Left: patient picker and line items as an editable table (product, stock, qty, unit price, line total). Right: a **sticky summary panel** with the split bar, the four figures, the disabled-reason text, and Continue. Stacks to one column under 900px with the summary below.
- **Review / created:** same summary panel, read-only, with Confirm as the only primary button. Created state shows the patient link in a copyable field.
- **Patient order page:** narrow (560px), centred, receipt-like: "From Dr. Maya Patel", the date prices were set, items with quantities and line totals, a total, then the payment method and Pay. Paid state turns it into the receipt with a green "Paid" pill. No split bar here: patients see one price, by design (D1).
- **Dashboard:** lead with a sentence, not a stat-card row: "You've earned **$32.50** from 1 paid order." Under it the split bar of totals (GMV → COGS / fees / earnings), then Paid orders (table with compact bars), Pending orders (with Cancel), Units sold.
- **Audit:** a ledger-style page: lines table, the split bar, the four ledger rows in an accountant-style table (right-aligned tabular cents, a rule above the total), and the three integrity checks as a checklist with green check icons and plain-language labels ("Fee matches the 0.75% formula", "Split adds up to the subtotal", "Ledger matches the split").
- **Admin:** a dense table of products with inline stock and COGS inputs and a per-row Save.

## Components

- `StatusPill` (pending = warn tint, paid = good tint, cancelled = neutral), used everywhere a status appears.
- `Money` (formats cents, tabular figures; optional emphasis), so formatting is consistent.
- Buttons: primary (blue fill), secondary (white, line border), danger-quiet (Cancel order). Disabled buttons always have a visible reason next to them.
- Inline errors under the field or line they belong to, in `--bad`, plain language from the API message.
- Empty states say what to do: "No orders yet. Create one from New order." with a link.

## Copy

Sentence case everywhere, no all-caps labels, no exclamation marks. Actions keep their names through a flow: "Confirm order" → "Order created". Errors say what happened and how to fix it.

## Quality floor

Keyboard focus visible on everything (2px blue outline, 2px offset); color never the only signal (pills have text, checks have icons + words); WCAG AA contrast; works at 375px wide; `prefers-reduced-motion` respected.

## Not doing

No dark mode, no charts library, no icon font (inline SVG for the few icons), no new pages, no change to what any page fetches or sends.
