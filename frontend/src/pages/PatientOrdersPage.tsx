import { useEffect, useState } from "react";
import { Link } from "react-router";

import { apiGet, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { EmptyState } from "../components/EmptyState.tsx";
import { InlineError } from "../components/InlineError.tsx";
import { Money } from "../components/Money.tsx";
import { StatusPill } from "../components/StatusPill.tsx";

type OrderResponse = components["schemas"]["OrderResponse"];

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
    return <InlineError message={loadError} />;
  }
  if (orders === null) {
    return <p>Loading orders…</p>;
  }

  return (
    <div className="page">
      <h1>My orders</h1>
      {orders.length === 0 ? <EmptyState>No orders yet.</EmptyState> : null}
      {orders.map((order) => (
        <article key={order.id}>
          <header>
            <Link to={`/orders/${order.id}`}>Order {order.id}</Link>
          </header>
          <p>
            <StatusPill status={order.status} />
          </p>
          <p>
            Total <Money cents={order.subtotal_cents} />
          </p>
        </article>
      ))}
    </div>
  );
}
