import { expect, test } from "vitest";

import { stockOverWarning } from "./stock";

test("stockOverWarning is null when qty is within stock", () => {
  expect(stockOverWarning(1, 50)).toBeNull();
  expect(stockOverWarning(50, 50)).toBeNull();
});

test("stockOverWarning names available stock when qty exceeds it", () => {
  expect(stockOverWarning(55, 50)).toBe(
    "Only 50 in stock. Payment will fail unless stock is added.",
  );
  expect(stockOverWarning(1, 0)).toBe(
    "Only 0 in stock. Payment will fail unless stock is added.",
  );
});
