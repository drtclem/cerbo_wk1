/** Non-blocking builder warning when preview qty exceeds available stock. */
export function stockOverWarning(qty: number, stockAvailable: number): string | null {
  if (qty <= stockAvailable) {
    return null;
  }
  return `Only ${stockAvailable} in stock. Payment will fail unless stock is added.`;
}
