import { formatCents } from "../lib/money.ts";

/** Minimum painted width for a non-zero fee segment (ui-design.md). */
export const FEE_MIN_PX = 3;

export type SplitBarAmounts = {
  subtotalCents: number;
  cogsCents: number;
  feeCents: number;
  payoutCents: number;
};

export type SplitBarLayoutInput = SplitBarAmounts & {
  barWidthPx: number;
};

export type SplitBarLayout = {
  cogsWidthPx: number;
  feeWidthPx: number;
  payoutWidthPx: number;
  cogsLabel: string;
  feeLabel: string;
  payoutLabel: string;
  subtotalLabel: string;
};

/**
 * Display layout for the split bar. Widths are proportions of API cents
 * (drawing only — not recomputing the money split). Labels are formatCents
 * of those same cents.
 */
export function splitBarLayout(input: SplitBarLayoutInput): SplitBarLayout {
  const { subtotalCents, cogsCents, feeCents, payoutCents, barWidthPx } = input;
  const labels = {
    cogsLabel: formatCents(cogsCents),
    feeLabel: formatCents(feeCents),
    payoutLabel: formatCents(payoutCents),
    subtotalLabel: formatCents(subtotalCents),
  };

  if (subtotalCents === 0 || barWidthPx === 0) {
    return {
      cogsWidthPx: 0,
      feeWidthPx: 0,
      payoutWidthPx: 0,
      ...labels,
    };
  }

  if (feeCents > 0) {
    const rawFee = (feeCents / subtotalCents) * barWidthPx;
    if (rawFee < FEE_MIN_PX) {
      const feeWidthPx = Math.min(FEE_MIN_PX, barWidthPx);
      const remaining = Math.max(0, barWidthPx - feeWidthPx);
      const rest = cogsCents + payoutCents;
      if (rest === 0) {
        return { cogsWidthPx: 0, feeWidthPx, payoutWidthPx: remaining, ...labels };
      }
      const cogsWidthPx = remaining * (cogsCents / rest);
      const payoutWidthPx = remaining - cogsWidthPx;
      return { cogsWidthPx, feeWidthPx, payoutWidthPx, ...labels };
    }
  }

  const cogsWidthPx = (cogsCents / subtotalCents) * barWidthPx;
  const feeWidthPx = feeCents === 0 ? 0 : (feeCents / subtotalCents) * barWidthPx;
  const payoutWidthPx = barWidthPx - cogsWidthPx - feeWidthPx;
  return { cogsWidthPx, feeWidthPx, payoutWidthPx, ...labels };
}
