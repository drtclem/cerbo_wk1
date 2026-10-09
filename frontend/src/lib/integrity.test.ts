import { expect, test } from "vitest";

import {
  DONATION_MATCHES_LABEL,
  LEDGER_MATCHES_LABEL,
  SPLIT_ADDS_UP_LABEL,
  feeMatchesLabel,
  feeRateLabel,
} from "./integrity";

test("feeRateLabel prints 75 basis points as 0.75%", () => {
  expect(feeRateLabel(75)).toBe("0.75%");
});

test("feeRateLabel prints whole percents and sub-percent rates from basis points", () => {
  expect(feeRateLabel(0)).toBe("0.00%");
  expect(feeRateLabel(7)).toBe("0.07%");
  expect(feeRateLabel(100)).toBe("1.00%");
  expect(feeRateLabel(750)).toBe("7.50%");
});

test("integrity checklist uses the design's plain-language labels", () => {
  expect(feeMatchesLabel(75)).toBe("Fee matches the 0.75% formula");
  expect(DONATION_MATCHES_LABEL).toBe("Donation matches the rate");
  expect(SPLIT_ADDS_UP_LABEL).toBe("Split adds up to the subtotal");
  expect(LEDGER_MATCHES_LABEL).toBe("Ledger matches the split");
});
