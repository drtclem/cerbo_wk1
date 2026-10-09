import { useEffect, useRef, useState } from "react";

import { apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { InlineError } from "../components/InlineError.tsx";
import { Money } from "../components/Money.tsx";
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
    return <InlineError message={loadError} />;
  }
  if (products === null) {
    return <p>Loading products…</p>;
  }

  return (
    <div className="page">
      <h1>Stock &amp; COGS</h1>
      {products.length === 0 ? <p className="muted">No products to edit.</p> : null}
      {products.length > 0 ? (
        <div className="table-wrap">
          <table className="dense">
            <thead>
              <tr>
                <th>Product</th>
                <th className="num">Suggested price</th>
                <th>Stock</th>
                <th>COGS</th>
                <th>Default dosing</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {products.map((product) => (
                <AdminProductRow
                  key={product.id}
                  product={product}
                  userId={userId}
                  onUpdated={replaceProduct}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
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
  const [dosing, setDosing] = useState(product.default_dosing);
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
    const trimmedDosing = dosing.trim();
    if (trimmedDosing.length === 0 || trimmedDosing.length > 200) {
      setError("Default dosing is required (at most 200 characters).");
      return;
    }
    saving.current = true;
    setBusy(true);
    setError(null);
    try {
      const updated = await apiSend<AdminProduct>(`/admin/products/${product.id}`, userId, "PUT", {
        stock_qty: stockQty,
        unit_cogs_cents: cogsCents,
        default_dosing: trimmedDosing,
      });
      setStock(String(updated.stock_qty));
      setCogs(formatCents(updated.unit_cogs_cents));
      setDosing(updated.default_dosing);
      onUpdated(updated);
    } catch (cause: unknown) {
      setError(errorText(cause));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }

  const unsaved =
    stock !== String(product.stock_qty) ||
    cogs !== formatCents(product.unit_cogs_cents) ||
    dosing !== product.default_dosing;

  return (
    <>
      <tr>
        <td>
          <div className="cell-title">{product.name}</div>
          <div className="muted">{product.sku}</div>
        </td>
        <td className="num">
          <Money cents={product.suggested_price_cents} />
        </td>
        <td>
          <input
            className="input-qty"
            aria-label={`Stock for ${product.name}`}
            value={stock}
            inputMode="numeric"
            onChange={(event) => {
              setStock(event.target.value);
              setError(null);
            }}
          />
        </td>
        <td>
          <input
            className="input-money"
            aria-label={`COGS for ${product.name}`}
            value={cogs}
            inputMode="decimal"
            onChange={(event) => {
              setCogs(event.target.value);
              setError(null);
            }}
          />
        </td>
        <td>
          <input
            aria-label={`Default dosing for ${product.name}`}
            value={dosing}
            maxLength={200}
            onChange={(event) => {
              setDosing(event.target.value);
              setError(null);
            }}
          />
        </td>
        <td>
          <div className="btn-row">
            <button
              type="button"
              className={unsaved ? undefined : "secondary"}
              disabled={busy}
              onClick={() => void save()}
            >
              Save
            </button>
            {busy ? <p className="btn-hint">Saving</p> : null}
          </div>
        </td>
      </tr>
      {error !== null ? (
        <tr>
          <td colSpan={6}>
            <InlineError message={error} />
          </td>
        </tr>
      ) : null}
    </>
  );
}
