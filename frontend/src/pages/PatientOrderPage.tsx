import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";

import { apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { InlineError } from "../components/InlineError.tsx";
import { Money } from "../components/Money.tsx";
import type { User } from "../components/RoleSwitcher.tsx";
import { StatusPill } from "../components/StatusPill.tsx";

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

export function PatientOrderRoute({
  userId,
  role,
  users,
}: {
  userId: number;
  role: string;
  users: User[];
}) {
  const { orderId } = useParams();
  return <PatientOrderPage key={orderId} userId={userId} role={role} users={users} />;
}

function PatientOrderPage({
  userId,
  role,
  users,
}: {
  userId: number;
  role: string;
  users: User[];
}) {
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
    return <InlineError message="Not found" />;
  }
  if (loadError !== null) {
    return <InlineError message={loadError} />;
  }
  if (order === null) {
    return <p>Loading order…</p>;
  }

  const canPay = role === "patient" && order.status === "pending_payment";
  const title = order.status === "paid" ? "Receipt" : "Order";
  const providerName = users.find((user) => user.id === order.provider_id)?.name ?? "your provider";

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
    <article className="receipt">
      <header className="receipt__header">
        <h1>{title}</h1>
        <StatusPill status={order.status} />
      </header>
      <p className="receipt__from">From {providerName}</p>
      <p className="muted">Prices set by your provider on {orderDateLabel(order.created_at)}</p>
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th className="num">Qty</th>
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {order.lines.map((line, index) => (
            <tr key={`${line.product_id}-${index}`}>
              <td>
                <div className="cell-title">{line.product_name}</div>
                <div className="muted">
                  <Money cents={line.unit_price_cents} /> each
                </div>
                <p className="line-instructions">
                  <span className="line-instructions__label">How to take it:</span>{" "}
                  {line.dosing}
                </p>
                {line.note !== null && line.note.length > 0 ? (
                  <p className="line-instructions">
                    <span className="line-instructions__label">
                      Why {providerName} recommends it:
                    </span>{" "}
                    {line.note}
                  </p>
                ) : null}
              </td>
              <td className="num">{line.qty}</td>
              <td className="num">
                <Money cents={line.line_total_cents} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="receipt__total">
        <span>Total</span>
        <Money cents={order.subtotal_cents} />
      </p>
      {order.status === "paid" ? (
        <>
          {order.paid_at !== null ? (
            <p className="muted">Paid {orderDateLabel(order.paid_at)}</p>
          ) : null}
          {order.payment_ref !== null ? (
            <p className="muted">Payment reference {order.payment_ref}</p>
          ) : null}
          <p className="muted">{"What happens next: Cerbo ships your order. You don’t need to do anything else."}</p>
        </>
      ) : null}
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
                  setPayError(null);
                }
              }}
            >
              <option value="fake_card_ok">OK test card</option>
              <option value="fake_card_decline">Decline test card</option>
            </select>
          </label>
          <div className="btn-row">
            <button type="button" disabled={busy} onClick={() => void pay()}>
              Pay
            </button>
            {busy ? <p className="btn-hint">Taking payment</p> : null}
          </div>
        </>
      ) : null}
      {canPay && payError !== null ? <InlineError message={payError} /> : null}
    </article>
  );
}
