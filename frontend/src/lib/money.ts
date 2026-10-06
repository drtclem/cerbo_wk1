const DOLLAR_AMOUNT = /^\d+(\.\d{1,2})?$/;
const THOUSANDS = /^(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d{1,2})?$/;

export function parseDollarsToCents(input: string): number {
  const stripped = stripAffixes(input.trim());
  if (!DOLLAR_AMOUNT.test(stripped)) {
    throw new Error("Invalid dollar amount");
  }
  const [dollars, fraction = ""] = stripped.split(".");
  const cents = `${fraction}00`.slice(0, 2);
  const digits = `${dollars}${cents}`;
  if (digits.length > 15) {
    throw new Error("Invalid dollar amount");
  }
  const value = Number(digits);
  if (!Number.isSafeInteger(value)) {
    throw new Error("Invalid dollar amount");
  }
  return value;
}

export function formatCents(cents: number): string {
  if (!Number.isSafeInteger(cents) || cents < 0) {
    throw new Error("Invalid cents");
  }
  const digits = String(cents).padStart(3, "0");
  const centPart = digits.slice(-2);
  const dollarPart = groupDigits(digits.slice(0, -2));
  return `$${dollarPart}.${centPart}`;
}

function stripAffixes(input: string): string {
  const withoutDollar = input.startsWith("$") ? input.slice(1) : input;
  if (!THOUSANDS.test(withoutDollar)) {
    throw new Error("Invalid dollar amount");
  }
  return withoutDollar.replaceAll(",", "");
}

function groupDigits(digits: string): string {
  const parts: string[] = [];
  let rest = digits;
  while (rest.length > 3) {
    parts.unshift(rest.slice(-3));
    rest = rest.slice(0, -3);
  }
  parts.unshift(rest);
  return parts.join(",");
}
