import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";

import { apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { formatCents } from "../lib/money.ts";

type OrderResponse = components["schemas"]["OrderResponse"];
type PaymentMethod = "fake_card_ok" | "fake_card_decline";

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

function statusLabel(status: string): string {
  if (status === "pending_payment") {
    return "Pending payment";
  }
  if (status === "paid") {
    return "Paid";
  }
  if (status === "cancelled") {
    return "Cancelled";
  }
  return status;
}

function orderDateLabel(createdAt: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(createdAt);
  if (match === null) {
    return createdAt;
  }
  const month = MONTHS[Number(match[2]) - 1];
  const day = Number(match[3]);
  if (month === undefined || !Number.isInteger(day) || day < 1 || day > 31) {
    return createdAt;
  }
  return `${month} ${day}`;
}

export function PatientOrderRoute({ userId, role }: { userId: number; role: string }) {
  const { orderId } = useParams();
  return <PatientOrderPage key={orderId} userId={userId} role={role} />;
}

function PatientOrderPage({ userId, role }: { userId: number; role: string }) {
  const { orderId } = useParams();
  const [order, setOrder] = useState<OrderResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [method, setMethod] = useState<PaymentMethod>("fake_card_ok");
  const [payError, setPayError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const paying = useRef(false);

  useEffect(() => {
    if (orderId === undefined || !/^\d+$/.test(orderId)) {
      return;
    }
    let cancelled = false;
    apiGet<OrderResponse>(`/orders/${orderId}`, userId)
      .then((loaded) => {
        if (!cancelled) {
          setOrder(loaded);
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
  if (order === null) {
    return <p>Loading order…</p>;
  }

  const canPay = role === "patient" && order.status === "pending_payment";
  const title = order.status === "paid" ? "Receipt" : "Order";

  async function pay() {
    if (paying.current || order === null || order.status !== "pending_payment") {
      return;
    }
    paying.current = true;
    setBusy(true);
    setPayError(null);
    try {
      const paid = await apiSend<OrderResponse>(`/orders/${order.id}/pay`, userId, "POST", {
        payment_method: method,
      });
      setOrder(paid);
    } catch (cause: unknown) {
      setPayError(errorText(cause));
    } finally {
      paying.current = false;
      setBusy(false);
    }
  }

  return (
    <main>
      <h1>{title}</h1>
      <p>Status {statusLabel(order.status)}</p>
      {order.lines.map((line, index) => (
        <article key={`${line.product_id}-${index}`}>
          <header>
            <strong>{line.product_name}</strong>
          </header>
          <p>Qty {line.qty}</p>
          <p>Unit price {formatCents(line.unit_price_cents)}</p>
          <p>Line total {formatCents(line.line_total_cents)}</p>
        </article>
      ))}
      <p>Total {formatCents(order.subtotal_cents)}</p>
      <p>Prices set by your provider on {orderDateLabel(order.created_at)}</p>
      {canPay ? (
        <>
          <label>
            Payment method
            <select
              value={method}
              onChange={(event) => {
                const value = event.target.value;
                if (value === "fake_card_ok" || value === "fake_card_decline") {
                  setMethod(value);
                }
              }}
            >
              <option value="fake_card_ok">OK test card</option>
              <option value="fake_card_decline">Decline test card</option>
            </select>
          </label>
          <button type="button" disabled={busy} onClick={() => void pay()}>
            Pay
          </button>
        </>
      ) : null}
      {payError !== null ? <p role="alert">{payError}</p> : null}
    </main>
  );
}
