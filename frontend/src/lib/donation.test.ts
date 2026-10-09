import { expect, test } from "vitest";

import {
  DEMO_FUND_NOTE,
  DONATE_DEFAULT_KEY,
  patientDonationFunds,
  patientDonationIntro,
  readDonateDefault,
  shouldShowPatientDonation,
  writeDonateDefault,
} from "./donation";

const LINES_ON = [
  {
    fund_name: "American Migraine Foundation",
    fund_url: "https://americanmigrainefoundation.org/",
    donation_cents: 120,
  },
  {
    fund_name: "ASBMR Fund for Research and Education",
    fund_url: "https://www.asbmr.org/About/Fund-for-Research-and-Education",
    donation_cents: 45,
  },
] as const;

test("readDonateDefault is false until localStorage stores true", () => {
  const store = new Map<string, string>();
  const storage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
  };
  expect(readDonateDefault(storage)).toBe(false);
  writeDonateDefault(true, storage);
  expect(store.get(DONATE_DEFAULT_KEY)).toBe("true");
  expect(readDonateDefault(storage)).toBe(true);
  writeDonateDefault(false, storage);
  expect(readDonateDefault(storage)).toBe(false);
});

test("patientDonationFunds lists unique funds with a donation and no amounts", () => {
  const funds = patientDonationFunds([
    ...LINES_ON,
    {
      fund_name: "American Migraine Foundation",
      fund_url: "https://americanmigrainefoundation.org/",
      donation_cents: 10,
    },
    { fund_name: "Unused", fund_url: null, donation_cents: 0 },
  ]);
  expect(funds).toEqual([
    {
      name: "American Migraine Foundation",
      url: "https://americanmigrainefoundation.org/",
    },
    {
      name: "ASBMR Fund for Research and Education",
      url: "https://www.asbmr.org/About/Fund-for-Research-and-Education",
    },
  ]);
  for (const fund of funds) {
    expect(JSON.stringify(fund)).not.toMatch(/\$|\d+\.\d{2}|cents?/i);
  }
});

test("patientDonationFunds includes zero-amount funds when donation_bps is on", () => {
  expect(
    patientDonationFunds(
      [{ fund_name: "American Migraine Foundation", fund_url: null, donation_cents: 0 }],
      500,
    ),
  ).toEqual([{ name: "American Migraine Foundation", url: null }]);
  expect(
    patientDonationFunds(
      [{ fund_name: "American Migraine Foundation", fund_url: null, donation_cents: 0 }],
      0,
    ),
  ).toEqual([]);
});

test("shouldShowPatientDonation follows donation_bps or line donations", () => {
  expect(shouldShowPatientDonation(500, LINES_ON)).toBe(true);
  expect(shouldShowPatientDonation(0, LINES_ON)).toBe(true);
  expect(
    shouldShowPatientDonation(0, [
      { fund_name: "American Migraine Foundation", fund_url: null, donation_cents: 0 },
    ]),
  ).toBe(false);
  expect(shouldShowPatientDonation(500, [])).toBe(true);
});

test("patient-facing donation copy never includes dollar or cent amounts", () => {
  const intro = patientDonationIntro("Dr. Maya Patel");
  expect(intro).toBe(
    "Dr. Maya Patel is donating part of their earnings from this order to medical research:",
  );
  expect(intro).not.toMatch(/\$/);
  expect(intro).not.toMatch(/\d+\.\d{2}/);
  expect(intro).not.toMatch(/cents?/i);
  expect(DEMO_FUND_NOTE).not.toMatch(/\$/);
  expect(DEMO_FUND_NOTE).not.toMatch(/\d+\.\d{2}/);
  for (const fund of patientDonationFunds(LINES_ON)) {
    expect(fund.name).not.toMatch(/\$/);
    expect(fund.name).not.toMatch(/\d+\.\d{2}/);
  }
});
