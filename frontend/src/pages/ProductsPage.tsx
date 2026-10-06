import { useEffect, useRef, useState } from "react";

import { ApiError, apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
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
    return <p role="alert">{error}</p>;
  }
  if (products === null) {
    return <p>Loading products…</p>;
  }

  return (
    <div className="page">
      <h1>Products</h1>
      {products.map((product) => (
        <ProductRow key={product.product_id} product={product} userId={userId} />
      ))}
    </div>
  );
}

function ProductRow({ product, userId }: { product: ProviderProduct; userId: number }) {
  const [enabled, setEnabled] = useState(product.enabled);
  const [savedCents, setSavedCents] = useState(product.default_price_cents);
  const [draft, setDraft] = useState(formatCents(product.default_price_cents));
  const [dirty, setDirty] = useState(false);
  const [payoutCents, setPayoutCents] = useState<number | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const requestSeq = useRef(0);

  useEffect(() => {
    if (!dirty || !enabled) {
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      let cents: number;
      try {
        cents = parseDollarsToCents(draft);
      } catch {
        if (!cancelled) {
          setPayoutCents(null);
          setPreviewError("Invalid dollar amount");
        }
        return;
      }
      apiSend<PreviewResponse>("/orders/preview", userId, "POST", {
        lines: [{ product_id: product.product_id, qty: 1, unit_price_cents: cents }],
      })
        .then((body) => {
          if (cancelled) {
            return;
          }
          setPayoutCents(body.provider_payout_cents);
          setPreviewError(null);
        })
        .catch((cause: unknown) => {
          if (cancelled) {
            return;
          }
          if (cause instanceof ApiError && cause.code === "PRODUCT_UNAVAILABLE") {
            return;
          }
          setPayoutCents(null);
          setPreviewError(errorText(cause));
        });
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [dirty, enabled, draft, product.product_id, userId]);

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
        setPayoutCents(null);
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
    <article>
      <header>
        <strong>{product.name}</strong>
        <p>{product.sku}</p>
      </header>
      <p>{stockLabel(product.stock_qty)}</p>
      <label>
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
      <label>
        Default price
        <input
          value={draft}
          inputMode="decimal"
          onChange={(event) => {
            setDraft(event.target.value);
            setDirty(true);
            setSaveError(null);
            setPayoutCents(null);
            setPreviewError(null);
          }}
        />
      </label>
      {payoutCents !== null ? (
        <p>
          you'd receive <span className="you-receive">{formatCents(payoutCents)}</span> at qty 1
        </p>
      ) : null}
      {message !== null ? <p role="alert">{message}</p> : null}
      <button type="button" disabled={busy} onClick={() => void savePrice()}>
        Save
      </button>
    </article>
  );
}
