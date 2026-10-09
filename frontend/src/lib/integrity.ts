/** Display label for an order's stored fee rate. Integer math on basis points, not a fee calculation. */
export function feeRateLabel(feeBps: number): string {
  const abs = Math.abs(Math.trunc(feeBps));
  const whole = Math.trunc(abs / 100);
  const fraction = abs % 100;
  const sign = feeBps < 0 ? "-" : "";
  return `${sign}${whole}.${String(fraction).padStart(2, "0")}%`;
}

export function feeMatchesLabel(feeBps: number): string {
  return `Fee matches the ${feeRateLabel(feeBps)} formula`;
}

export const SPLIT_ADDS_UP_LABEL = "Split adds up to the subtotal";
export const LEDGER_MATCHES_LABEL = "Ledger matches the split";
export const DONATION_MATCHES_LABEL = "Donation matches the rate";
