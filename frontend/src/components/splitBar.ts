import { formatCents } from "../lib/money.ts";

export type SplitBarAmounts = {
  subtotalCents: number;
  cogsCents: number;
  feeCents: number;
  donationCents: number;
  payoutCents: number;
};

export type SplitBarLayout = {
  /** Percent of the track. The four segments sum to 100 when subtotal is positive. */
  cogsPercent: number;
  feePercent: number;
  donationPercent: number;
  payoutPercent: number;
  cogsLabel: string;
  feeLabel: string;
  donationLabel: string;
  payoutLabel: string;
  subtotalLabel: string;
};

/**
 * Display layout for the split bar. Widths are percentages of API cents
 * (drawing only — not recomputing the money split). A non-zero fee's 3px
 * floor is CSS (`min-width` on the fee segment), not a pixel measurement.
 * Labels are formatCents of those same cents.
 */
export function splitBarLayout(input: SplitBarAmounts): SplitBarLayout {
  const { subtotalCents, cogsCents, feeCents, donationCents, payoutCents } = input;
  const labels = {
    cogsLabel: formatCents(cogsCents),
    feeLabel: formatCents(feeCents),
    donationLabel: formatCents(donationCents),
    payoutLabel: formatCents(payoutCents),
    subtotalLabel: formatCents(subtotalCents),
  };

  if (subtotalCents <= 0) {
    return {
      cogsPercent: 0,
      feePercent: 0,
      donationPercent: 0,
      payoutPercent: 0,
      ...labels,
    };
  }

  const cogsPercent = (cogsCents / subtotalCents) * 100;
  const feePercent = feeCents === 0 ? 0 : (feeCents / subtotalCents) * 100;
  const donationPercent =
    donationCents === 0 ? 0 : (donationCents / subtotalCents) * 100;
  const payoutPercent = 100 - cogsPercent - feePercent - donationPercent;
  return { cogsPercent, feePercent, donationPercent, payoutPercent, ...labels };
}
