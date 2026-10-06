import { useLayoutEffect, useRef, useState } from "react";

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
  payoutCents,
  compact = false,
  subtotalCaption = "Patient pays",
}: SplitBarProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [barWidthPx, setBarWidthPx] = useState(0);

  useLayoutEffect(() => {
    const node = trackRef.current;
    if (node === null) {
      return;
    }
    const sync = () => {
      setBarWidthPx(node.getBoundingClientRect().width);
    };
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, []);

  const layout = splitBarLayout({
    subtotalCents,
    cogsCents,
    feeCents,
    payoutCents,
    barWidthPx,
  });

  return (
    <div className={compact ? "split-bar split-bar--compact" : "split-bar"}>
      {!compact ? (
        <p className="split-bar__subtotal">
          {subtotalCaption} <span className="money">{layout.subtotalLabel}</span>
        </p>
      ) : null}
      <div
        ref={trackRef}
        className="split-bar__track"
        role="img"
        aria-label={`COGS ${layout.cogsLabel}, fee ${layout.feeLabel}, you receive ${layout.payoutLabel}`}
      >
        <span
          className="split-bar__seg split-bar__seg--cogs"
          style={{ width: `${layout.cogsWidthPx}px` }}
          title={compact ? undefined : `COGS ${layout.cogsLabel}`}
        />
        <span
          className="split-bar__seg split-bar__seg--fee"
          style={{ width: `${layout.feeWidthPx}px` }}
          title={compact ? undefined : `Fee ${layout.feeLabel}`}
        />
        <span
          className="split-bar__seg split-bar__seg--payout"
          style={{ width: `${layout.payoutWidthPx}px` }}
          title={compact ? undefined : `You receive ${layout.payoutLabel}`}
        />
      </div>
      {!compact ? (
        <div className="split-bar__legend">
          <span className="split-bar__legend-cogs">COGS {layout.cogsLabel}</span>
          <span className="split-bar__legend-fee">Fee {layout.feeLabel}</span>
          <span className="split-bar__legend-payout">You receive {layout.payoutLabel}</span>
        </div>
      ) : null}
    </div>
  );
}
