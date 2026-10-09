import { expect, test } from "vitest";

import {
  REMOVED_BY_PATIENT_LABEL,
  activeLines,
  beginRemoveConfirm,
  cancelRemoveConfirm,
  confirmingLineId,
  isRemoveConfirming,
  lineStruckThrough,
  removedLines,
} from "./removeLine";

const ACTIVE = {
  id: 1,
  product_name: "Magnesium Glycinate",
  removed_at: null,
} as const;

const REMOVED = {
  id: 2,
  product_name: "Vitamin D3 + K2",
  removed_at: "2026-10-09T12:00:00Z",
} as const;

test("REMOVED_BY_PATIENT_LABEL is the provider-facing copy", () => {
  expect(REMOVED_BY_PATIENT_LABEL).toBe("Removed by patient");
});

test("activeLines and removedLines partition by removed_at", () => {
  const lines = [ACTIVE, REMOVED];
  expect(activeLines(lines)).toEqual([ACTIVE]);
  expect(removedLines(lines)).toEqual([REMOVED]);
  expect(activeLines([])).toEqual([]);
  expect(removedLines([ACTIVE])).toEqual([]);
});

test("lineStruckThrough is true only when removed_at is set", () => {
  expect(lineStruckThrough(ACTIVE)).toBe(false);
  expect(lineStruckThrough(REMOVED)).toBe(true);
});

test("inline remove confirm is idle until begin, then clears on cancel", () => {
  expect(confirmingLineId(null)).toBeNull();
  expect(isRemoveConfirming(null, 1)).toBe(false);

  const confirming = beginRemoveConfirm(null, 1);
  expect(confirmingLineId(confirming)).toBe(1);
  expect(isRemoveConfirming(confirming, 1)).toBe(true);
  expect(isRemoveConfirming(confirming, 2)).toBe(false);

  // Starting confirm on another line replaces the previous one.
  const other = beginRemoveConfirm(confirming, 2);
  expect(confirmingLineId(other)).toBe(2);
  expect(isRemoveConfirming(other, 1)).toBe(false);

  expect(cancelRemoveConfirm()).toBeNull();
  expect(isRemoveConfirming(cancelRemoveConfirm(), 2)).toBe(false);
});
