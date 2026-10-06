import { useEffect, useState } from "react";
import { useParams } from "react-router";

import { apiGet, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { Money } from "../components/Money.tsx";
import { SplitBar } from "../components/SplitBar.tsx";
import { StatusPill } from "../components/StatusPill.tsx";

type Audit = components["schemas"]["AuditResponse"];

const LEDGER_LABELS: Record<string, string> = {
  patient_payment: "Patient payment",
  cerbo_cogs: "Cerbo COGS",
  cerbo_fee: "Cerbo fee",
  provider_payable: "Provider payable",
};

function ledgerLabel(entryType: string): string {
  return LEDGER_LABELS[entryType] ?? entryType;
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
    return <p role="alert">Not found</p>;
  }
  if (loadError !== null) {
    return <p role="alert">{loadError}</p>;
  }
  if (audit === null) {
    return <p>Loading audit…</p>;
  }

  return (
    <div className="page">
      <h1>Audit</h1>
      <p>Order {audit.id}</p>
      <p>
        <StatusPill status={audit.status} />
      </p>
      <h2>Lines</h2>
      {audit.lines.map((line, index) => (
        <article key={`${line.product_id}-${index}`}>
          <header>
            <strong>{line.product_name}</strong>
          </header>
          <p>Qty {line.qty}</p>
          <p>
            Unit price <Money cents={line.unit_price_cents} />
          </p>
          <p>
            Unit COGS <Money cents={line.unit_cogs_cents} />
          </p>
          <p>
            Line total <Money cents={line.line_total_cents} />
          </p>
        </article>
      ))}
      <h2>Split</h2>
      <SplitBar
        subtotalCents={audit.subtotal_cents}
        cogsCents={audit.cogs_total_cents}
        feeCents={audit.platform_fee_cents}
        payoutCents={audit.provider_payout_cents}
      />
      <h2>Ledger</h2>
      {audit.ledger.length === 0 ? <p>No ledger entries.</p> : null}
      {audit.ledger.map((entry) => (
        <p key={entry.entry_type}>
          {ledgerLabel(entry.entry_type)} <Money cents={entry.amount_cents} />
        </p>
      ))}
      <h2>Integrity</h2>
      <p>{audit.recomputed_fee_matches ? "✓" : "✗"} Fee matches formula</p>
      <p>{audit.split_adds_up ? "✓" : "✗"} Split adds up</p>
      <p>{audit.ledger_matches_split ? "✓" : "✗"} Ledger matches split</p>
    </div>
  );
}
