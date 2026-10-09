/**
 * Contract for `splitBarLayout` (pure helper used by SplitBar):
 * - Widths are percentages: cogs/subtotal, fee/subtotal, donation/subtotal,
 *   payout/subtotal.
 * - Those four percentages sum to 100 whenever the subtotal is positive,
 *   so the bar fills its track at every width. No pixel measurement.
 * - Labels are formatCents of those same cents (never derived from widths).
 * - A non-zero fee's minimum visible width is CSS min-width: 3px, not a
 *   change to the percentage. When feeCents or donationCents is 0, that
 *   segment's percentage is 0.
 * - Zero subtotal → all percentages 0; labels still format the props.
 */
import { readFileSync } from "node:fs";
import { expect, test } from "vitest";

import { formatCents } from "../lib/money";
import { splitBarLayout } from "./splitBar";

const DEMO_OFF = {
  subtotalCents: 6_600,
  cogsCents: 3_300,
  feeCents: 50,
  donationCents: 0,
  payoutCents: 3_250,
} as const;

const DEMO_ON = {
  subtotalCents: 6_600,
  cogsCents: 3_300,
  feeCents: 50,
  donationCents: 165,
  payoutCents: 3_085,
} as const;

test("splitBarLayout widths are percentages of subtotal and fill the track", () => {
  const layout = splitBarLayout(DEMO_OFF);
  expect(layout.cogsPercent).toBeCloseTo((3_300 / 6_600) * 100, 5);
  expect(layout.feePercent).toBeCloseTo((50 / 6_600) * 100, 5);
  expect(layout.donationPercent).toBe(0);
  expect(layout.payoutPercent).toBeCloseTo((3_250 / 6_600) * 100, 5);
  expect(
    layout.cogsPercent + layout.feePercent + layout.donationPercent + layout.payoutPercent,
  ).toBe(100);
});

test("splitBarLayout with donation fills the track with four segments", () => {
  const layout = splitBarLayout(DEMO_ON);
  expect(layout.cogsPercent).toBeCloseTo((3_300 / 6_600) * 100, 5);
  expect(layout.feePercent).toBeCloseTo((50 / 6_600) * 100, 5);
  expect(layout.donationPercent).toBeCloseTo((165 / 6_600) * 100, 5);
  expect(layout.payoutPercent).toBeCloseTo((3_085 / 6_600) * 100, 5);
  expect(
    layout.cogsPercent + layout.feePercent + layout.donationPercent + layout.payoutPercent,
  ).toBe(100);
});

test("splitBarLayout keeps a tiny fee at its true percentage", () => {
  const layout = splitBarLayout({
    subtotalCents: 10_000,
    cogsCents: 4_999,
    feeCents: 1,
    donationCents: 0,
    payoutCents: 5_000,
  });
  expect(layout.feePercent).toBeCloseTo((1 / 10_000) * 100, 5);
  expect(layout.feePercent).toBeLessThan(1);
  expect(
    layout.cogsPercent + layout.feePercent + layout.donationPercent + layout.payoutPercent,
  ).toBe(100);
  expect(layout.cogsPercent).toBeGreaterThan(0);
  expect(layout.payoutPercent).toBeGreaterThan(0);
});

test("a non-zero fee segment has a 3px CSS minimum width", () => {
  const css = readFileSync(new URL("../theme.css", import.meta.url), "utf8");
  expect(css).toMatch(/\.split-bar__seg--fee\s*\{[^}]*min-width:\s*3px;/);
});

test("splitBarLayout labels print formatCents of the props unchanged", () => {
  const layout = splitBarLayout(DEMO_ON);
  expect(layout.cogsLabel).toBe(formatCents(DEMO_ON.cogsCents));
  expect(layout.feeLabel).toBe(formatCents(DEMO_ON.feeCents));
  expect(layout.donationLabel).toBe(formatCents(DEMO_ON.donationCents));
  expect(layout.payoutLabel).toBe(formatCents(DEMO_ON.payoutCents));
  expect(layout.subtotalLabel).toBe(formatCents(DEMO_ON.subtotalCents));
  expect(layout.cogsLabel).toBe("$33.00");
  expect(layout.feeLabel).toBe("$0.50");
  expect(layout.donationLabel).toBe("$1.65");
  expect(layout.payoutLabel).toBe("$30.85");
  expect(layout.subtotalLabel).toBe("$66.00");
});

test("splitBarLayout with zero fee and zero donation paints empty segments", () => {
  const layout = splitBarLayout({
    subtotalCents: 66,
    cogsCents: 30,
    feeCents: 0,
    donationCents: 0,
    payoutCents: 36,
  });
  expect(layout.feePercent).toBe(0);
  expect(layout.donationPercent).toBe(0);
  expect(layout.feeLabel).toBe(formatCents(0));
  expect(layout.donationLabel).toBe(formatCents(0));
  expect(layout.cogsPercent).toBeCloseTo((30 / 66) * 100, 5);
  expect(layout.payoutPercent).toBeCloseTo((36 / 66) * 100, 5);
  expect(
    layout.cogsPercent + layout.feePercent + layout.donationPercent + layout.payoutPercent,
  ).toBe(100);
});

test("splitBarLayout with zero subtotal returns zero widths and still formats labels", () => {
  const layout = splitBarLayout({
    subtotalCents: 0,
    cogsCents: 0,
    feeCents: 0,
    donationCents: 0,
    payoutCents: 0,
  });
  expect(layout.cogsPercent).toBe(0);
  expect(layout.feePercent).toBe(0);
  expect(layout.donationPercent).toBe(0);
  expect(layout.payoutPercent).toBe(0);
  expect(layout.cogsLabel).toBe(formatCents(0));
  expect(layout.feeLabel).toBe(formatCents(0));
  expect(layout.donationLabel).toBe(formatCents(0));
  expect(layout.payoutLabel).toBe(formatCents(0));
  expect(layout.subtotalLabel).toBe(formatCents(0));
});
