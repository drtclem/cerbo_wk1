import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { formatCents } from "../lib/money.ts";

type Dashboard = components["schemas"]["DashboardResponse"];
type PendingOrder = components["schemas"]["PendingOrderResponse"];

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
] as const;

function orderDateLabel(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (match === null) {
    return value;
  }
  const month = MONTHS[Number(match[2]) - 1];
  const day = Number(match[3]);
  if (month === undefined || !Number.isInteger(day) || day < 1 || day > 31) {
    return value;
  }
  return `${month} ${day}`;
}

export function DashboardPage({ userId }: { userId: number }) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<{ id: number; message: string } | null>(null);
  const [cancellingIds, setCancellingIds] = useState<ReadonlySet<number>>(new Set());
  const cancelling = useRef(new Set<number>());

  useEffect(() => {
    let cancelled = false;
    apiGet<Dashboard>("/provider/dashboard", userId)
      .then((loaded) => {
        if (!cancelled) {
          setDashboard(loaded);
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
  }, [userId]);

  async function cancelOrder(order: PendingOrder) {
    if (cancelling.current.has(order.id)) {
      return;
    }
    cancelling.current.add(order.id);
    setCancellingIds((current) => new Set(current).add(order.id));
    setCancelError(null);
    try {
      await apiSend(`/orders/${order.id}/cancel`, userId, "POST", undefined);
      const loaded = await apiGet<Dashboard>("/provider/dashboard", userId);
      setDashboard(loaded);
    } catch (cause: unknown) {
      setCancelError({ id: order.id, message: errorText(cause) });
    } finally {
      cancelling.current.delete(order.id);
      setCancellingIds((current) => {
        const next = new Set(current);
        next.delete(order.id);
        return next;
      });
    }
  }

  if (loadError !== null) {
    return <p role="alert">{loadError}</p>;
  }
  if (dashboard === null) {
    return <p>Loading dashboard…</p>;
  }

  return (
    <main>
      <h1>Dashboard</h1>
      <p>GMV {formatCents(dashboard.gmv_cents)}</p>
      <p>Platform fees {formatCents(dashboard.platform_fee_cents)}</p>
      <p>Earnings {formatCents(dashboard.earnings_cents)}</p>
      <h2>Paid orders</h2>
      {dashboard.paid_orders.length === 0 ? <p>No paid orders.</p> : null}
      {dashboard.paid_orders.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Patient</th>
              <th>Subtotal</th>
              <th>Fee</th>
              <th>Payout</th>
              <th>Audit</th>
            </tr>
          </thead>
          <tbody>
            {dashboard.paid_orders.map((order) => (
              <tr key={order.id}>
                <td>{orderDateLabel(order.paid_at)}</td>
                <td>{order.patient_name}</td>
                <td>{formatCents(order.subtotal_cents)}</td>
                <td>{formatCents(order.platform_fee_cents)}</td>
                <td>{formatCents(order.provider_payout_cents)}</td>
                <td>
                  <Link to={order.audit_link}>Audit</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <h2>Units sold</h2>
      {dashboard.units_sold.length === 0 ? <p>No units sold.</p> : null}
      {dashboard.units_sold.map((unit) => (
        <p key={unit.product_id}>
          {unit.product_name} {unit.qty}
        </p>
      ))}
      <h2>Pending orders</h2>
      {dashboard.pending_orders.length === 0 ? <p>No pending orders.</p> : null}
      {dashboard.pending_orders.map((order) => (
        <article key={order.id}>
          <header>
            <strong>Order {order.id}</strong>
          </header>
          <p>{order.patient_name}</p>
          <p>{orderDateLabel(order.created_at)}</p>
          <button
            type="button"
            className="secondary"
            disabled={cancellingIds.has(order.id)}
            onClick={() => void cancelOrder(order)}
          >
            Cancel
          </button>
          {cancelError?.id === order.id ? <p role="alert">{cancelError.message}</p> : null}
        </article>
      ))}
    </main>
  );
}
