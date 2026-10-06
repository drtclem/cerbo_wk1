import { readFileSync } from "node:fs";
import { expect, test } from "vitest";

import { formatCents, parseDollarsToCents } from "./money";

test("parseDollarsToCents converts 19.99 dollars to 1999 cents", () => {
  expect(parseDollarsToCents("19.99")).toBe(1999);
});

test("parseDollarsToCents converts a whole dollar amount to cents", () => {
  expect(parseDollarsToCents("20")).toBe(2000);
});

test("parseDollarsToCents converts a single decimal digit to cents", () => {
  expect(parseDollarsToCents("0.5")).toBe(50);
});

test("parseDollarsToCents accepts a leading dollar sign and thousands commas", () => {
  expect(parseDollarsToCents("$1,234.56")).toBe(123456);
});

test("parseDollarsToCents accepts commas only as thousands separators", () => {
  expect(parseDollarsToCents("1,234.56")).toBe(123456);
  expect(parseDollarsToCents("12,345")).toBe(1234500);
  expect(() => parseDollarsToCents("19,99")).toThrow();
  expect(() => parseDollarsToCents("1,23")).toThrow();
  expect(() => parseDollarsToCents("1,2345")).toThrow();
});

test("parseDollarsToCents rejects extra decimals, negatives, non-numeric text, and empty input", () => {
  expect(() => parseDollarsToCents("1.999")).toThrow();
  expect(() => parseDollarsToCents("-5")).toThrow();
  expect(() => parseDollarsToCents("abc")).toThrow();
  expect(() => parseDollarsToCents("")).toThrow();
});

// After trim, one leading $, and comma removal, the only accepted form is /^\d+(\.\d{1,2})?$/.
test("parseDollarsToCents rejects a leading or trailing dot", () => {
  expect(() => parseDollarsToCents(".5")).toThrow();
  expect(() => parseDollarsToCents("20.")).toThrow();
});

test("formatCents formats 1999 cents as $19.99", () => {
  expect(formatCents(1999)).toBe("$19.99");
});

test("formatCents formats amounts under one dollar with a leading zero", () => {
  expect(formatCents(5)).toBe("$0.05");
});

test("formatCents formats thousands with a comma", () => {
  expect(formatCents(123456)).toBe("$1,234.56");
});

test("formatCents formats zero cents as $0.00", () => {
  expect(formatCents(0)).toBe("$0.00");
});

test("money.ts source does not multiply by 100 or call parseFloat", () => {
  const source = readFileSync(new URL("./money.ts", import.meta.url), "utf8");
  expect(source).not.toContain("* 100");
  expect(source).not.toContain("parseFloat");
});
