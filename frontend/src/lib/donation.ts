/** Research-donation display helpers. No money math — API cents only. */

export const DONATE_DEFAULT_KEY = "cerbo.donateDefault";

export const DEMO_FUND_NOTE =
  "Example organizations for this demo. Not affiliated; no donations are made.";

export type DonationFundLine = {
  fund_name: string | null;
  fund_url: string | null;
  donation_cents: number;
};

export type PatientDonationFund = {
  name: string;
  url: string | null;
};

/** Provider default for the donate switch, remembered per browser. */
export function readDonateDefault(
  storage: Pick<Storage, "getItem"> = localStorage,
): boolean {
  return storage.getItem(DONATE_DEFAULT_KEY) === "true";
}

export function writeDonateDefault(
  value: boolean,
  storage: Pick<Storage, "setItem"> = localStorage,
): void {
  storage.setItem(DONATE_DEFAULT_KEY, value ? "true" : "false");
}

/**
 * Unique funds that received a donation on this order (by name).
 * Patient UI lists these without amounts.
 */
/**
 * Unique funds for the patient notice.
 * When donation_bps > 0, list every snapshotted fund; otherwise only funds
 * that actually received a donation_cents > 0.
 */
export function patientDonationFunds(
  lines: readonly DonationFundLine[],
  donationBps = 0,
): PatientDonationFund[] {
  const seen = new Set<string>();
  const funds: PatientDonationFund[] = [];
  for (const line of lines) {
    if (line.fund_name === null) {
      continue;
    }
    if (donationBps <= 0 && line.donation_cents <= 0) {
      continue;
    }
    if (seen.has(line.fund_name)) {
      continue;
    }
    seen.add(line.fund_name);
    funds.push({ name: line.fund_name, url: line.fund_url });
  }
  return funds;
}

/** Show the patient donation notice when the order donated (rate or line amounts). */
export function shouldShowPatientDonation(
  donationBps: number,
  lines: readonly DonationFundLine[],
): boolean {
  return donationBps > 0 || patientDonationFunds(lines, donationBps).length > 0;
}

/**
 * Patient-facing intro. Uses the provider display name as stored (e.g. "Dr. Maya Patel").
 * Never includes dollar or cent amounts.
 */
export function patientDonationIntro(providerName: string): string {
  return `${providerName} is donating part of their earnings from this order to medical research:`;
}
