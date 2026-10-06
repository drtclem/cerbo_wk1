import { useEffect, useState } from "react";
import { Link } from "react-router";

import { apiGet, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { formatCents } from "../lib/money.ts";

type OrderResponse = components["schemas"]["OrderResponse"];

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

export function PatientOrdersPage({ userId }: { userId: number }) {
  const [orders, setOrders] = useState<OrderResponse[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<OrderResponse[]>("/patient/orders", userId)
      .then((listed) => {
        if (!cancelled) {
          setOrders(listed);
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

  if (loadError !== null) {
    return <p role="alert">{loadError}</p>;
  }
  if (orders === null) {
    return <p>Loading orders…</p>;
  }

  return (
    <main>
      <h1>My orders</h1>
      {orders.length === 0 ? <p>No orders.</p> : null}
      {orders.map((order) => (
        <article key={order.id}>
          <header>
            <Link to={`/orders/${order.id}`}>Order {order.id}</Link>
          </header>
          <p>Status {statusLabel(order.status)}</p>
          <p>Total {formatCents(order.subtotal_cents)}</p>
        </article>
      ))}
    </main>
  );
}
