import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { EmptyState } from "../components/EmptyState.tsx";
import { InlineError } from "../components/InlineError.tsx";
import { Money } from "../components/Money.tsx";
import { SplitBar } from "../components/SplitBar.tsx";
import { StatusPill } from "../components/StatusPill.tsx";

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
    return <InlineError message={loadError} />;
  }
  if (dashboard === null) {
    return <p>Loading dashboard…</p>;
  }

  const paidCount = dashboard.paid_orders.length;
  const orderWord = paidCount === 1 ? "order" : "orders";
  // Remainder of API cents so the totals bar can draw COGS. Not a fee calculation.
  const totalsCogsCents =
    dashboard.gmv_cents -
    dashboard.platform_fee_cents -
    dashboard.donation_cents -
    dashboard.earnings_cents;

  return (
    <div className="page">
      <h1>Dashboard</h1>
      <p className="lead">
        You&apos;ve earned <Money cents={dashboard.earnings_cents} emphasize /> from {paidCount}{" "}
        paid {orderWord}.
      </p>
      <p className="dashboard-donation">
        Donated to research <Money cents={dashboard.donation_cents} />
      </p>
      <SplitBar
        subtotalCents={dashboard.gmv_cents}
        cogsCents={totalsCogsCents}
        feeCents={dashboard.platform_fee_cents}
        donationCents={dashboard.donation_cents}
        payoutCents={dashboard.earnings_cents}
        subtotalCaption="GMV"
      />

      <section className="section">
        <h2>Paid orders</h2>
        {dashboard.paid_orders.length === 0 ? (
          <EmptyState actionTo="/orders/new" actionLabel="New order">
            No paid orders yet. Create one from
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Patient</th>
                  <th>Status</th>
                  <th className="num">Subtotal</th>
                  <th className="num">Fee</th>
                  <th className="num">Payout</th>
                  <th>Split</th>
                  <th>Audit</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.paid_orders.map((order) => {
                  const cogsCents =
                    order.subtotal_cents -
                    order.platform_fee_cents -
                    order.donation_cents -
                    order.provider_payout_cents;
                  return (
                    <tr key={order.id}>
                      <td>{orderDateLabel(order.paid_at)}</td>
                      <td>{order.patient_name}</td>
                      <td>
                        <StatusPill status="paid" />
                      </td>
                      <td className="num">
                        <Money cents={order.subtotal_cents} />
                      </td>
                      <td className="num">
                        <Money cents={order.platform_fee_cents} />
                      </td>
                      <td className="num">
                        <Money cents={order.provider_payout_cents} emphasize />
                      </td>
                      <td className="split-cell">
                        <SplitBar
                          compact
                          subtotalCents={order.subtotal_cents}
                          cogsCents={cogsCents}
                          feeCents={order.platform_fee_cents}
                          donationCents={order.donation_cents}
                          payoutCents={order.provider_payout_cents}
                        />
                      </td>
                      <td>
                        <Link to={order.audit_link}>Audit</Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="section">
        <h2>Pending orders</h2>
        {dashboard.pending_orders.length === 0 ? <p className="muted">No pending orders.</p> : null}
        {dashboard.pending_orders.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Patient</th>
                  <th>Date</th>
                  <th>Status</th>
                  <th>
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {dashboard.pending_orders.map((order) => {
                  const cancellingThis = cancellingIds.has(order.id);
                  return (
                    <Fragment key={order.id}>
                      <tr>
                        <td>Order {order.id}</td>
                        <td>{order.patient_name}</td>
                        <td>{orderDateLabel(order.created_at)}</td>
                        <td>
                          <StatusPill status="pending_payment" />
                        </td>
                        <td>
                          <div className="btn-row">
                            <button
                              type="button"
                              className="danger-quiet"
                              disabled={cancellingThis}
                              onClick={() => void cancelOrder(order)}
                            >
                              Cancel order
                            </button>
                            {cancellingThis ? <p className="btn-hint">Cancelling this order</p> : null}
                          </div>
                        </td>
                      </tr>
                      {cancelError?.id === order.id ? (
                        <tr>
                          <td colSpan={5}>
                            <InlineError message={cancelError.message} />
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="section">
        <h2>Units sold</h2>
        {dashboard.units_sold.length === 0 ? <p className="muted">No units sold.</p> : null}
        {dashboard.units_sold.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="num">Units</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.units_sold.map((unit) => (
                  <tr key={unit.product_id}>
                    <td>{unit.product_name}</td>
                    <td className="num">{unit.qty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
