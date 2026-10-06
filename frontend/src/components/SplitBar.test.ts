/**
 * Contract for `splitBarLayout` (pure helper used by SplitBar):
 * - Proportions are cogs/subtotal, fee/subtotal, payout/subtotal from API cents.
 * - Labels are formatCents of those same cents (never derived from bar widths).
 * - Given barWidthPx, segment pixel widths sum to barWidthPx.
 * - When feeCents > 0, the fee segment is never under FEE_MIN_PX (3). When the
 *   fee fraction would paint thinner than that, fee gets FEE_MIN_PX and the
 *   leftover width is split between COGS and payout in their relative share of
 *   (cogs+payout). When feeCents is 0, fee width is 0 (no phantom bar).
 * - Zero subtotal → all widths 0; labels still format the props.
 */
import { expect, test } from "vitest";

import { formatCents } from "../lib/money";
import { FEE_MIN_PX, splitBarLayout } from "./splitBar";

const DEMO = {
  subtotalCents: 6_600,
  cogsCents: 3_300,
  feeCents: 50,
  payoutCents: 3_250,
} as const;

test("splitBarLayout widths match cogs/subtotal, fee/subtotal, and payout/subtotal", () => {
  const barWidthPx = 400;
  const layout = splitBarLayout({ ...DEMO, barWidthPx });
  expect(layout.cogsWidthPx).toBeCloseTo((3_300 / 6_600) * barWidthPx, 5);
  expect(layout.feeWidthPx).toBeCloseTo((50 / 6_600) * barWidthPx, 5);
  expect(layout.payoutWidthPx).toBeCloseTo((3_250 / 6_600) * barWidthPx, 5);
  expect(layout.cogsWidthPx + layout.feeWidthPx + layout.payoutWidthPx).toBeCloseTo(
    barWidthPx,
    5,
  );
});

test("splitBarLayout fee segment is never under the minimum visible width", () => {
  expect(FEE_MIN_PX).toBe(3);
  // Tiny fee fraction of a wide bar would be ~0.15px without the floor.
  const barWidthPx = 1_000;
  const layout = splitBarLayout({
    subtotalCents: 10_000,
    cogsCents: 4_999,
    feeCents: 1,
    payoutCents: 5_000,
    barWidthPx,
  });
  expect(layout.feeWidthPx).toBe(FEE_MIN_PX);
  expect(layout.cogsWidthPx + layout.feeWidthPx + layout.payoutWidthPx).toBe(barWidthPx);
  expect(layout.cogsWidthPx).toBeGreaterThan(0);
  expect(layout.payoutWidthPx).toBeGreaterThan(0);
  const remaining = barWidthPx - FEE_MIN_PX;
  expect(layout.cogsWidthPx).toBeCloseTo(remaining * (4_999 / 9_999), 5);
  expect(layout.payoutWidthPx).toBeCloseTo(remaining * (5_000 / 9_999), 5);
});

test("splitBarLayout labels print formatCents of the props unchanged", () => {
  const layout = splitBarLayout({ ...DEMO, barWidthPx: 400 });
  expect(layout.cogsLabel).toBe(formatCents(DEMO.cogsCents));
  expect(layout.feeLabel).toBe(formatCents(DEMO.feeCents));
  expect(layout.payoutLabel).toBe(formatCents(DEMO.payoutCents));
  expect(layout.subtotalLabel).toBe(formatCents(DEMO.subtotalCents));
  expect(layout.cogsLabel).toBe("$33.00");
  expect(layout.feeLabel).toBe("$0.50");
  expect(layout.payoutLabel).toBe("$32.50");
  expect(layout.subtotalLabel).toBe("$66.00");
});

test("splitBarLayout with zero fee paints no fee segment and keeps proportions", () => {
  const barWidthPx = 200;
  const layout = splitBarLayout({
    subtotalCents: 66,
    cogsCents: 30,
    feeCents: 0,
    payoutCents: 36,
    barWidthPx,
  });
  expect(layout.feeWidthPx).toBe(0);
  expect(layout.feeLabel).toBe(formatCents(0));
  expect(layout.cogsWidthPx).toBeCloseTo((30 / 66) * barWidthPx, 5);
  expect(layout.payoutWidthPx).toBeCloseTo((36 / 66) * barWidthPx, 5);
  expect(layout.cogsWidthPx + layout.feeWidthPx + layout.payoutWidthPx).toBeCloseTo(
    barWidthPx,
    5,
  );
});

test("splitBarLayout with zero subtotal returns zero widths and still formats labels", () => {
  const layout = splitBarLayout({
    subtotalCents: 0,
    cogsCents: 0,
    feeCents: 0,
    payoutCents: 0,
    barWidthPx: 400,
  });
  expect(layout.cogsWidthPx).toBe(0);
  expect(layout.feeWidthPx).toBe(0);
  expect(layout.payoutWidthPx).toBe(0);
  expect(layout.cogsLabel).toBe(formatCents(0));
  expect(layout.feeLabel).toBe(formatCents(0));
  expect(layout.payoutLabel).toBe(formatCents(0));
  expect(layout.subtotalLabel).toBe(formatCents(0));
});
