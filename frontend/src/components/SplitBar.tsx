import { splitBarLayout, type SplitBarAmounts } from "./splitBar.ts";

type SplitBarProps = SplitBarAmounts & {
  /** Compact bar for table rows: no labels, 6px tall. */
  compact?: boolean;
  /** Shown above the bar in the full variant. Defaults to "Patient pays". */
  subtotalCaption?: string;
};

export function SplitBar({
  subtotalCents,
  cogsCents,
  feeCents,
  donationCents,
  payoutCents,
  compact = false,
  subtotalCaption = "Patient pays",
}: SplitBarProps) {
  const layout = splitBarLayout({
    subtotalCents,
    cogsCents,
    feeCents,
    donationCents,
    payoutCents,
  });

  return (
    <div className={compact ? "split-bar split-bar--compact" : "split-bar"}>
      {!compact ? (
        <p className="split-bar__subtotal">
          {subtotalCaption} <span className="money">{layout.subtotalLabel}</span>
        </p>
      ) : null}
      <div
        className="split-bar__track"
        role="img"
        aria-label={`COGS ${layout.cogsLabel}, fee ${layout.feeLabel}, research ${layout.donationLabel}, you receive ${layout.payoutLabel}`}
      >
        <span
          className="split-bar__seg split-bar__seg--cogs"
          style={{ width: `${layout.cogsPercent}%` }}
          title={compact ? undefined : `COGS ${layout.cogsLabel}`}
        />
        <span
          className={
            layout.feePercent === 0
              ? "split-bar__seg split-bar__seg--fee split-bar__seg--empty"
              : "split-bar__seg split-bar__seg--fee"
          }
          style={{ width: `${layout.feePercent}%` }}
          title={compact ? undefined : `Fee ${layout.feeLabel}`}
        />
        <span
          className={
            layout.donationPercent === 0
              ? "split-bar__seg split-bar__seg--donation split-bar__seg--empty"
              : "split-bar__seg split-bar__seg--donation"
          }
          style={{ width: `${layout.donationPercent}%` }}
          title={compact ? undefined : `Research ${layout.donationLabel}`}
        />
        <span
          className="split-bar__seg split-bar__seg--payout"
          style={{ width: `${layout.payoutPercent}%` }}
          title={compact ? undefined : `You receive ${layout.payoutLabel}`}
        />
      </div>
      {!compact ? (
        <div className="split-bar__legend">
          <span className="split-bar__legend-cogs">COGS {layout.cogsLabel}</span>
          <span className="split-bar__legend-fee">Fee {layout.feeLabel}</span>
          <span className="split-bar__legend-donation">Research {layout.donationLabel}</span>
          <span className="split-bar__legend-payout">You receive {layout.payoutLabel}</span>
        </div>
      ) : null}
    </div>
  );
}
