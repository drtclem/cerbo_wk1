import { useEffect, useRef, useState } from "react";

import { apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { formatCents, parseDollarsToCents } from "../lib/money.ts";

type AdminProduct = components["schemas"]["AdminProductResponse"];

function parseStock(input: string): number | null {
  const trimmed = input.trim();
  if (!/^\d+$/.test(trimmed)) {
    return null;
  }
  const value = Number(trimmed);
  if (!Number.isSafeInteger(value)) {
    return null;
  }
  return value;
}

export function AdminProductsPage({ userId }: { userId: number }) {
  const [products, setProducts] = useState<AdminProduct[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<AdminProduct[]>("/admin/products", userId)
      .then((listed) => {
        if (!cancelled) {
          setProducts(listed);
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

  function replaceProduct(updated: AdminProduct) {
    setProducts((current) =>
      current === null
        ? current
        : current.map((product) => (product.id === updated.id ? updated : product)),
    );
  }

  if (loadError !== null) {
    return <p role="alert">{loadError}</p>;
  }
  if (products === null) {
    return <p>Loading products…</p>;
  }

  return (
    <main>
      <h1>Stock &amp; COGS</h1>
      {products.map((product) => (
        <AdminProductRow
          key={product.id}
          product={product}
          userId={userId}
          onUpdated={replaceProduct}
        />
      ))}
    </main>
  );
}

function AdminProductRow({
  product,
  userId,
  onUpdated,
}: {
  product: AdminProduct;
  userId: number;
  onUpdated: (product: AdminProduct) => void;
}) {
  const [stock, setStock] = useState(String(product.stock_qty));
  const [cogs, setCogs] = useState(formatCents(product.unit_cogs_cents));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const saving = useRef(false);

  async function save() {
    if (saving.current) {
      return;
    }
    const stockQty = parseStock(stock);
    if (stockQty === null) {
      setError("Stock must be at least 0.");
      return;
    }
    let cogsCents: number;
    try {
      cogsCents = parseDollarsToCents(cogs);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Invalid dollar amount");
      return;
    }
    if (cogsCents < 1) {
      setError("COGS must be greater than zero.");
      return;
    }
    saving.current = true;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiSend<AdminProduct>(`/admin/products/${product.id}`, userId, "PUT", {
        stock_qty: stockQty,
        unit_cogs_cents: cogsCents,
      });
      setStock(String(updated.stock_qty));
      setCogs(formatCents(updated.unit_cogs_cents));
      onUpdated(updated);
    } catch (cause: unknown) {
      setError(errorText(cause));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  return (
    <article>
      <header>
        <strong>{product.name}</strong>
      </header>
      <p>{product.sku}</p>
      <p>Suggested price {formatCents(product.suggested_price_cents)}</p>
      <label>
        Stock
        <input
          value={stock}
          inputMode="numeric"
          onChange={(event) => {
            setStock(event.target.value);
            setError(null);
          }}
        />
      </label>
      <label>
        COGS
        <input
          value={cogs}
          inputMode="decimal"
          onChange={(event) => {
            setCogs(event.target.value);
            setError(null);
          }}
        />
      </label>
      <button type="button" disabled={busy} onClick={() => void save()}>
        Save
      </button>
      {error !== null ? <p role="alert">{error}</p> : null}
    </article>
  );
}
