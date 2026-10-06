import { useEffect, useState } from "react";
import { useParams } from "react-router";

import { apiGet, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { InlineError } from "../components/InlineError.tsx";
import { Money } from "../components/Money.tsx";
import { SplitBar } from "../components/SplitBar.tsx";
import { StatusPill } from "../components/StatusPill.tsx";
import { LEDGER_MATCHES_LABEL, SPLIT_ADDS_UP_LABEL, feeMatchesLabel } from "../lib/integrity.ts";

type Audit = components["schemas"]["AuditResponse"];
type LedgerEntry = components["schemas"]["AuditLedgerResponse"];

const LEDGER_LABELS: Record<string, string> = {
  patient_payment: "Patient payment",
  cerbo_cogs: "Cerbo COGS",
  cerbo_fee: "Cerbo fee",
  provider_payable: "Provider payable",
};

const LEDGER_RANK: Record<string, number> = {
  cerbo_cogs: 0,
  cerbo_fee: 1,
  provider_payable: 2,
  patient_payment: 3,
};

function ledgerLabel(entryType: string): string {
  return LEDGER_LABELS[entryType] ?? entryType;
}

function orderedLedger(entries: LedgerEntry[]): LedgerEntry[] {
  return [...entries].sort(
    (left, right) =>
      (LEDGER_RANK[left.entry_type] ?? 2.5) - (LEDGER_RANK[right.entry_type] ?? 2.5),
  );
}

export function AuditRoute({ userId }: { userId: number }) {
  const { orderId } = useParams();
  return <AuditPage key={orderId} userId={userId} />;
}

function AuditPage({ userId }: { userId: number }) {
  const { orderId } = useParams();
  const [audit, setAudit] = useState<Audit | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (orderId === undefined || !/^\d+$/.test(orderId)) {
      return;
    }
    let cancelled = false;
    apiGet<Audit>(`/orders/${orderId}/audit`, userId)
      .then((loaded) => {
        if (!cancelled) {
          setAudit(loaded);
          setLoadError(null);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setLoadError(errorText(cause));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [orderId, userId]);

  if (orderId === undefined || !/^\d+$/.test(orderId)) {
    return <InlineError message="Not found" />;
  }
  if (loadError !== null) {
    return <InlineError message={loadError} />;
  }
  if (audit === null) {
    return <p>Loading audit…</p>;
  }

  const ledger = orderedLedger(audit.ledger);
  const checks = [
    { ok: audit.recomputed_fee_matches, label: feeMatchesLabel(audit.fee_bps) },
    { ok: audit.split_adds_up, label: SPLIT_ADDS_UP_LABEL },
    { ok: audit.ledger_matches_split, label: LEDGER_MATCHES_LABEL },
  ];

  return (
    <div className="page">
      <header className="page-heading">
        <h1>Audit</h1>
        <StatusPill status={audit.status} />
      </header>
      <p className="muted">Order {audit.id}</p>

      <section className="section">
        <h2>Lines</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th className="num">Qty</th>
                <th className="num">Unit price</th>
                <th className="num">Unit COGS</th>
                <th className="num">Line total</th>
              </tr>
            </thead>
            <tbody>
              {audit.lines.map((line, index) => (
                <tr key={`${line.product_id}-${index}`}>
                  <td className="cell-title">{line.product_name}</td>
                  <td className="num">{line.qty}</td>
                  <td className="num">
                    <Money cents={line.unit_price_cents} />
                  </td>
                  <td className="num">
                    <Money cents={line.unit_cogs_cents} />
                  </td>
                  <td className="num">
                    <Money cents={line.line_total_cents} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section">
        <h2>Split</h2>
        <SplitBar
          subtotalCents={audit.subtotal_cents}
          cogsCents={audit.cogs_total_cents}
          feeCents={audit.platform_fee_cents}
          payoutCents={audit.provider_payout_cents}
        />
      </section>

      <section className="section">
        <h2>Ledger</h2>
        {ledger.length === 0 ? <p className="muted">No ledger entries.</p> : null}
        {ledger.length > 0 ? (
          <div className="table-wrap">
            <table className="ledger">
              <thead>
                <tr>
                  <th>Entry</th>
                  <th className="num">Amount</th>
                </tr>
              </thead>
              <tbody>
                {ledger.map((entry) => (
                  <tr
                    key={entry.entry_type}
                    className={entry.entry_type === "patient_payment" ? "ledger__total" : undefined}
                  >
                    <th scope="row">{ledgerLabel(entry.entry_type)}</th>
                    <td className="num">
                      <Money cents={entry.amount_cents} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="section">
        <h2>Integrity</h2>
        <ul className="checklist">
          {checks.map((check) => (
            <li key={check.label} className={check.ok ? "check check--ok" : "check check--bad"}>
              {check.ok ? <CheckIcon /> : <CrossIcon />}
              <span className="visually-hidden">{check.ok ? "Met" : "Not met"}. </span>
              <span>{check.label}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg className="check-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="7" fill="currentColor" opacity="0.15" />
      <path
        d="M4.5 8.2 6.8 10.5 11.5 5.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CrossIcon() {
  return (
    <svg className="check-icon" width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="7" fill="currentColor" opacity="0.15" />
      <path
        d="M5.5 5.5 10.5 10.5 M10.5 5.5 5.5 10.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}
