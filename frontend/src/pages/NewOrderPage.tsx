import { useEffect, useRef, useState } from "react";

import { ApiError, apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import type { User } from "../components/RoleSwitcher.tsx";
import { formatCents, parseDollarsToCents } from "../lib/money.ts";

type ProviderProduct = components["schemas"]["ProviderProductResponse"];
type PreviewResponse = components["schemas"]["PreviewResponse"];
type PreviewLine = components["schemas"]["PreviewLineResponse"];
type OrderResponse = components["schemas"]["OrderResponse"];

type DraftLine = {
  key: number;
  productId: number;
  qty: string;
  price: string;
};

type ReadyLine = {
  product_id: number;
  qty: number;
  unit_price_cents: number;
};

type PreviewProblem = {
  message: string;
  lineIndex: number | null;
};

type Step = "build" | "review" | "created";

const PREVIEW_DELAY_MS = 300;
const QTY_PATTERN = /^[1-9]\d*$/;

function stockLabel(stockQty: number): string {
  return stockQty === 0 ? "Out of stock" : `${stockQty} in stock`;
}

function lineError(line: DraftLine): string | null {
  const qty = line.qty.trim();
  if (!QTY_PATTERN.test(qty)) {
    return "Quantity must be at least 1.";
  }
  const parsedQty = Number(qty);
  if (!Number.isSafeInteger(parsedQty)) {
    return "Quantity must be at least 1.";
  }
  try {
    parseDollarsToCents(line.price);
  } catch (cause: unknown) {
    return cause instanceof Error ? cause.message : "Invalid dollar amount";
  }
  return null;
}

function readyLines(lines: DraftLine[]): ReadyLine[] | null {
  if (lines.length === 0) {
    return null;
  }
  const ready: ReadyLine[] = [];
  for (const line of lines) {
    if (lineError(line) !== null) {
      return null;
    }
    ready.push({
      product_id: line.productId,
      qty: Number(line.qty.trim()),
      unit_price_cents: parseDollarsToCents(line.price),
    });
  }
  return ready;
}

function lineSignature(ready: ReadyLine[]): string {
  return JSON.stringify(ready);
}

function productById(
  products: ProviderProduct[],
  productId: number,
): ProviderProduct | undefined {
  return products.find((product) => product.product_id === productId);
}

function SplitBreakdown({
  split,
  subtotalLabel,
}: {
  split: Pick<
    PreviewResponse,
    "subtotal_cents" | "cogs_total_cents" | "platform_fee_cents" | "provider_payout_cents"
  >;
  subtotalLabel: string;
}) {
  return (
    <div>
      <p>
        {subtotalLabel} {formatCents(split.subtotal_cents)}
      </p>
      <p>COGS {formatCents(split.cogs_total_cents)}</p>
      <p>Platform fee {formatCents(split.platform_fee_cents)}</p>
      <p>
        You receive <span className="you-receive">{formatCents(split.provider_payout_cents)}</span>
      </p>
    </div>
  );
}

export function NewOrderPage({ userId }: { userId: number }) {
  const [users, setUsers] = useState<User[] | null>(null);
  const [products, setProducts] = useState<ProviderProduct[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [patientId, setPatientId] = useState<number | null>(null);
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [addProductId, setAddProductId] = useState("");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewFor, setPreviewFor] = useState<string | null>(null);
  const [previewProblem, setPreviewProblem] = useState<PreviewProblem | null>(null);
  const [step, setStep] = useState<Step>("build");
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [created, setCreated] = useState<OrderResponse | null>(null);
  const lineKey = useRef(1);
  const confirming = useRef(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      apiGet<User[]>("/users", userId),
      apiGet<ProviderProduct[]>("/provider/products", userId),
    ])
      .then(([listedUsers, listedProducts]) => {
        if (!cancelled) {
          setUsers(listedUsers);
          setProducts(listedProducts);
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

  useEffect(() => {
    const ready = readyLines(lines);
    if (ready === null) {
      return;
    }
    const signature = lineSignature(ready);
    let cancelled = false;
    const timer = setTimeout(() => {
      apiSend<PreviewResponse>("/orders/preview", userId, "POST", { lines: ready })
        .then((body) => {
          if (cancelled) {
            return;
          }
          setPreview(body);
          setPreviewFor(signature);
          setPreviewProblem(null);
        })
        .catch((cause: unknown) => {
          if (cancelled) {
            return;
          }
          setPreview(null);
          setPreviewFor(null);
          if (cause instanceof ApiError) {
            setPreviewProblem({ message: cause.message, lineIndex: cause.lineIndex });
            return;
          }
          setPreviewProblem({ message: errorText(cause), lineIndex: null });
        });
    }, PREVIEW_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [lines, userId]);

  if (loadError !== null) {
    return <p role="alert">{loadError}</p>;
  }
  if (users === null || products === null) {
    return <p>Loading order…</p>;
  }

  const patients = users.filter((user) => user.role === "patient");
  const enabled = products.filter((product) => product.enabled);
  const selectedAddId =
    addProductId !== ""
      ? addProductId
      : enabled[0] !== undefined
        ? String(enabled[0].product_id)
        : "";
  const ready = readyLines(lines);
  const signature = ready === null ? null : lineSignature(ready);
  const shownPreview = preview !== null && previewFor === signature ? preview : null;
  const patient = patients.find((user) => user.id === patientId) ?? null;
  const canContinue = patient !== null && shownPreview !== null && previewProblem === null;
  let continueReason: string | null = null;
  if (!canContinue) {
    if (patient === null) {
      continueReason = "Pick a patient";
    } else if (lines.length === 0) {
      continueReason = "Add at least one item";
    } else if (lines.some((line) => lineError(line) !== null) || previewProblem !== null) {
      continueReason = "Fix the errors above";
    } else {
      continueReason = "Checking prices";
    }
  }

  function editLines(next: DraftLine[]) {
    setLines(next);
    setPreviewProblem(null);
  }

  function addLine() {
    const product = enabled.find((item) => String(item.product_id) === selectedAddId);
    if (product === undefined) {
      return;
    }
    editLines([
      ...lines,
      {
        key: lineKey.current,
        productId: product.product_id,
        qty: "1",
        price: formatCents(product.default_price_cents),
      },
    ]);
    lineKey.current += 1;
  }

  async function confirmOrder() {
    if (confirming.current || patientId === null || shownPreview === null) {
      return;
    }
    confirming.current = true;
    setBusy(true);
    setCreateError(null);
    try {
      const order = await apiSend<OrderResponse>("/orders", userId, "POST", {
        patient_id: patientId,
        lines: shownPreview.lines.map((line) => ({
          product_id: line.product_id,
          qty: line.qty,
          unit_price_cents: line.unit_price_cents,
        })),
      });
      setCreated(order);
      setStep("created");
    } catch (cause: unknown) {
      if (cause instanceof ApiError && cause.lineIndex !== null) {
        setPreview(null);
        setPreviewFor(null);
        setPreviewProblem({ message: cause.message, lineIndex: cause.lineIndex });
        setStep("build");
        return;
      }
      setCreateError(errorText(cause));
    } finally {
      confirming.current = false;
      setBusy(false);
    }
  }

  if (step === "created" && created !== null) {
    return <CreatedOrder order={created} patientName={patient?.name ?? "Patient"} />;
  }

  if (step === "review") {
    const reviewError = previewProblem?.message ?? createError;
    return (
      <main>
        <h1>Review order</h1>
        {patient !== null ? <p>Patient {patient.name}</p> : null}
        {shownPreview !== null
          ? shownPreview.lines.map((line, index) => (
              <ReviewLine
                key={`${line.product_id}-${index}`}
                line={line}
                productName={productById(products, line.product_id)?.name ?? "Product"}
              />
            ))
          : null}
        {shownPreview !== null ? (
          <SplitBreakdown split={shownPreview} subtotalLabel="Patient pays" />
        ) : null}
        <p>Later catalog changes don&apos;t affect this order.</p>
        {shownPreview === null && previewProblem === null ? <p>Checking prices</p> : null}
        {reviewError !== null ? <p role="alert">{reviewError}</p> : null}
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => {
            if (confirming.current) {
              return;
            }
            setCreateError(null);
            setStep("build");
          }}
        >
          Back
        </button>
        <button
          type="button"
          disabled={busy || shownPreview === null || patientId === null || previewProblem !== null}
          onClick={() => void confirmOrder()}
        >
          Confirm
        </button>
      </main>
    );
  }

  const orderProblem =
    previewProblem !== null && previewProblem.lineIndex === null ? previewProblem.message : null;

  return (
    <main>
      <h1>New order</h1>
      <label>
        Patient
        <select
          value={patientId === null ? "" : String(patientId)}
          onChange={(event) => {
            const value = event.target.value;
            setPatientId(value === "" ? null : Number(value));
          }}
        >
          <option value="">Select a patient</option>
          {patients.map((user) => (
            <option key={user.id} value={user.id}>
              {user.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Product
        <select
          value={selectedAddId}
          onChange={(event) => {
            setAddProductId(event.target.value);
          }}
        >
          {enabled.map((product) => (
            <option key={product.product_id} value={product.product_id}>
              {product.name} ({stockLabel(product.stock_qty)})
            </option>
          ))}
        </select>
      </label>
      <button type="button" disabled={selectedAddId === ""} onClick={addLine}>
        Add
      </button>
      {enabled.length === 0 ? <p>No enabled products.</p> : null}
      {lines.map((line, index) => {
        const product = productById(products, line.productId);
        const localError = lineError(line);
        const remoteError =
          previewProblem?.lineIndex === index ? previewProblem.message : null;
        const message = localError ?? remoteError;
        const priced = shownPreview?.lines[index];
        return (
          <article key={line.key}>
            <header>
              <strong>{product?.name ?? "Product"}</strong>
            </header>
            {product !== undefined ? <p>{stockLabel(product.stock_qty)}</p> : null}
            <label>
              Qty
              <input
                value={line.qty}
                inputMode="numeric"
                onChange={(event) => {
                  const qty = event.target.value;
                  editLines(lines.map((item) => (item.key === line.key ? { ...item, qty } : item)));
                }}
              />
            </label>
            <label>
              Unit price
              <input
                value={line.price}
                inputMode="decimal"
                onChange={(event) => {
                  const price = event.target.value;
                  editLines(
                    lines.map((item) => (item.key === line.key ? { ...item, price } : item)),
                  );
                }}
              />
            </label>
            {priced !== undefined ? <LineAmounts line={priced} /> : null}
            {message !== null ? <p role="alert">{message}</p> : null}
            <button
              type="button"
              className="secondary"
              onClick={() => {
                editLines(lines.filter((item) => item.key !== line.key));
              }}
            >
              Remove
            </button>
          </article>
        );
      })}
      {shownPreview !== null ? (
        <SplitBreakdown split={shownPreview} subtotalLabel="Subtotal" />
      ) : null}
      {orderProblem !== null ? <p role="alert">{orderProblem}</p> : null}
      <button
        type="button"
        disabled={!canContinue}
        onClick={() => {
          setCreateError(null);
          setStep("review");
        }}
      >
        Continue
      </button>
      {continueReason !== null ? <p>{continueReason}</p> : null}
    </main>
  );
}

function LineAmounts({ line }: { line: PreviewLine }) {
  return (
    <p>
      Line total {formatCents(line.line_total_cents)}, COGS {formatCents(line.line_cogs_cents)},
      margin {formatCents(line.line_margin_cents)}
    </p>
  );
}

function ReviewLine({ line, productName }: { line: PreviewLine; productName: string }) {
  return (
    <article>
      <header>
        <strong>{productName}</strong>
      </header>
      <p>Qty {line.qty}</p>
      <p>Unit price {formatCents(line.unit_price_cents)}</p>
      <LineAmounts line={line} />
    </article>
  );
}

function CreatedOrder({ order, patientName }: { order: OrderResponse; patientName: string }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(order.patient_link);
      setCopied(true);
      setCopyError(null);
    } catch {
      setCopied(false);
      setCopyError("Could not copy the link");
    }
  }

  return (
    <main>
      <h1>Order created</h1>
      <p>Patient {patientName}</p>
      <p>Patient link {order.patient_link}</p>
      <button type="button" onClick={() => void copyLink()}>
        Copy
      </button>
      {copied ? <p>Copied</p> : null}
      {copyError !== null ? <p role="alert">{copyError}</p> : null}
    </main>
  );
}
