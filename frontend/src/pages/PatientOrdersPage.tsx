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
      {orders.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Order</th>
                <th>Status</th>
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.id}>
                  <td>
                    <Link to={`/orders/${order.id}`}>Order {order.id}</Link>
                  </td>
                  <td>
                    <StatusPill status={order.status} />
                  </td>
                  <td className="num">
                    <Money cents={order.subtotal_cents} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
