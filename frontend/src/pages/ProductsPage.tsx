import { useEffect, useRef, useState } from "react";

import { ApiError, apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { InlineError } from "../components/InlineError.tsx";
import { Money } from "../components/Money.tsx";
import { formatCents, parseDollarsToCents } from "../lib/money.ts";

type ProviderProduct = components["schemas"]["ProviderProductResponse"];
type PreviewResponse = components["schemas"]["PreviewResponse"];

const PREVIEW_DELAY_MS = 300;

function stockLabel(stockQty: number): string {
  return stockQty === 0 ? "Out of stock" : `${stockQty} in stock`;
}

export function ProductsPage({ userId }: { userId: number }) {
  const [products, setProducts] = useState<ProviderProduct[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<ProviderProduct[]>("/provider/products", userId)
      .then((rows) => {
        if (!cancelled) {
          setProducts(rows);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(errorText(cause));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (error !== null) {
    return <InlineError message={error} />;
  }
  if (products === null) {
    return <p>Loading products…</p>;
  }

  return (
    <div className="page">
      <h1>Products</h1>
      {products.length === 0 ? <p className="muted">No products yet.</p> : null}
      {products.length > 0 ? (
        <div className="table-wrap">
          <table className="dense">
            <thead>
              <tr>
                <th>Product</th>
                <th>Stock</th>
                <th>Enabled</th>
                <th>Default price</th>
                <th>You earn per unit at qty 1</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {products.map((product) => (
                <ProductRow key={product.product_id} product={product} userId={userId} />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

type UnitMargin = { payoutCents: number; cogsCents: number; feeCents: number };

function ProductRow({ product, userId }: { product: ProviderProduct; userId: number }) {
  const [enabled, setEnabled] = useState(product.enabled);
  const [savedCents, setSavedCents] = useState(product.default_price_cents);
  const [draft, setDraft] = useState(formatCents(product.default_price_cents));
  const [dirty, setDirty] = useState(false);
  const [margin, setMargin] = useState<UnitMargin | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const requestSeq = useRef(0);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      let cents: number;
      if (!dirty) {
        cents = savedCents;
      } else {
        try {
          cents = parseDollarsToCents(draft);
        } catch {
          if (!cancelled) {
            setMargin(null);
            setPreviewError("Invalid dollar amount");
          }
          return;
        }
      }
      apiSend<PreviewResponse>("/orders/preview", userId, "POST", {
        lines: [{ product_id: product.product_id, qty: 1, unit_price_cents: cents }],
      })
        .then((body) => {
          if (cancelled) {
            return;
          }
          setMargin({
            payoutCents: body.provider_payout_cents,
            cogsCents: body.cogs_total_cents,
            feeCents: body.platform_fee_cents,
          });
          setPreviewError(null);
        })
        .catch((cause: unknown) => {
          if (cancelled) {
            return;
          }
          if (cause instanceof ApiError && cause.code === "PRODUCT_UNAVAILABLE") {
            return;
          }
          setMargin(null);
          setPreviewError(errorText(cause));
        });
    }, dirty ? PREVIEW_DELAY_MS : 0);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [dirty, enabled, draft, savedCents, product.product_id, userId]);

  function beginRequest(): number {
    requestSeq.current += 1;
    setBusy(true);
    return requestSeq.current;
  }

  function finishRequest(seq: number) {
    if (seq === requestSeq.current) {
      setBusy(false);
    }
  }

  async function toggleEnabled(next: boolean) {
    const seq = beginRequest();
    try {
      const updated = await apiSend<ProviderProduct>(
        `/provider/products/${product.product_id}`,
        userId,
        "PUT",
        { enabled: next, default_price_cents: savedCents },
      );
      if (seq !== requestSeq.current) {
        return;
      }
      setEnabled(updated.enabled);
      setSavedCents(updated.default_price_cents);
      setSaveError(null);
      if (!updated.enabled) {
        setMargin(null);
        setPreviewError(null);
      }
    } catch (cause: unknown) {
      if (seq !== requestSeq.current) {
        return;
      }
      setSaveError(errorText(cause));
      setPreviewError(null);
    } finally {
      finishRequest(seq);
    }
  }

  async function savePrice() {
    let cents: number;
    try {
      cents = parseDollarsToCents(draft);
    } catch {
      setPreviewError(null);
      setSaveError("Invalid dollar amount");
      return;
    }
    const seq = beginRequest();
    try {
      const updated = await apiSend<ProviderProduct>(
        `/provider/products/${product.product_id}`,
        userId,
        "PUT",
        { enabled, default_price_cents: cents },
      );
      if (seq !== requestSeq.current) {
        return;
      }
      setEnabled(updated.enabled);
      setSavedCents(updated.default_price_cents);
      setDraft(formatCents(updated.default_price_cents));
      setDirty(false);
      setSaveError(null);
      setPreviewError(null);
    } catch (cause: unknown) {
      if (seq !== requestSeq.current) {
        return;
      }
      setSaveError(errorText(cause));
      setPreviewError(null);
    } finally {
      finishRequest(seq);
    }
  }

  const message = previewError ?? saveError;

  return (
    <>
      <tr>
        <td>
          <div className="cell-title">{product.name}</div>
          <div className="muted">{product.sku}</div>
        </td>
        <td>
          <span className={product.stock_qty === 0 ? "stock stock--out" : "stock"}>
            {stockLabel(product.stock_qty)}
          </span>
        </td>
        <td>
          <label className="check-label">
            <input
              type="checkbox"
              checked={enabled}
              disabled={busy}
              onChange={(event) => {
                void toggleEnabled(event.target.checked);
              }}
            />
            Enabled
          </label>
        </td>
        <td>
          <input
            className="input-money"
            aria-label={`Default price for ${product.name}`}
            value={draft}
            inputMode="decimal"
            onChange={(event) => {
              setDraft(event.target.value);
              setDirty(true);
              setSaveError(null);
              setMargin(null);
              setPreviewError(null);
            }}
          />
        </td>
        <td>
          {margin !== null ? (
            <>
              <div>
                <Money cents={margin.payoutCents} emphasize />
              </div>
              <div className="muted">
                after <Money cents={margin.cogsCents} /> cost + <Money cents={margin.feeCents} /> fee
              </div>
            </>
          ) : null}
        </td>
        <td>
          <div className="btn-row">
            <button
              type="button"
              className={dirty ? undefined : "secondary"}
              disabled={busy}
              onClick={() => void savePrice()}
            >
              Save
            </button>
            {busy ? <p className="btn-hint">Saving</p> : null}
          </div>
        </td>
      </tr>
      {message !== null ? (
        <tr>
          <td colSpan={6}>
            <InlineError message={message} />
          </td>
        </tr>
      ) : null}
    </>
  );
}
