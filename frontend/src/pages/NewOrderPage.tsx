import { useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError, apiGet, apiSend, errorText } from "../api/client.ts";
import type { components } from "../api/schema.ts";
import { InlineError } from "../components/InlineError.tsx";
import { Money } from "../components/Money.tsx";
import type { User } from "../components/RoleSwitcher.tsx";
import { SplitBar } from "../components/SplitBar.tsx";
import { formatCents, parseDollarsToCents } from "../lib/money.ts";
import { stockOverWarning } from "../lib/stock.ts";

type ProviderProduct = components["schemas"]["ProviderProductResponse"];
type PreviewResponse = components["schemas"]["PreviewResponse"];
type PreviewLine = components["schemas"]["PreviewLineResponse"];
type OrderResponse = components["schemas"]["OrderResponse"];

type DraftLine = {
  key: number;
  productId: number;
  qty: string;
  price: string;
  dosing: string;
  note: string;
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

type SplitFigures = Pick<
  PreviewResponse,
  "subtotal_cents" | "cogs_total_cents" | "platform_fee_cents" | "provider_payout_cents"
>;

const PREVIEW_DELAY_MS = 300;
const QTY_PATTERN = /^[1-9]\d*$/;

function stockLabel(stockQty: number): string {
  return stockQty === 0 ? "Out of stock" : `${stockQty} in stock`;
}

// Mirrors the API's request limits (D14) so the provider sees a specific message.
const MAX_QTY = 1_000;
const MAX_PRICE_CENTS = 1_000_000;

function lineError(line: DraftLine): string | null {
  const qty = line.qty.trim();
  if (!QTY_PATTERN.test(qty)) {
    return "Quantity must be at least 1.";
  }
  const parsedQty = Number(qty);
  if (!Number.isSafeInteger(parsedQty)) {
    return "Quantity must be at least 1.";
  }
  if (parsedQty > MAX_QTY) {
    return "Quantity can be at most 1,000.";
  }
  let priceCents: number;
  try {
    priceCents = parseDollarsToCents(line.price);
  } catch (cause: unknown) {
    return cause instanceof Error ? cause.message : "Invalid dollar amount";
  }
  if (priceCents > MAX_PRICE_CENTS) {
    return "Price can be at most $10,000.00.";
  }
  const dosing = line.dosing.trim();
  if (dosing.length === 0) {
    return "Dosing is required.";
  }
  if (dosing.length > 200) {
    return "Dosing must be at most 200 characters.";
  }
  if (line.note.trim().length > 500) {
    return "Note must be at most 500 characters.";
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

function SplitFigures({
  split,
  subtotalLabel,
}: {
  split: SplitFigures;
  subtotalLabel: string;
}) {
  return (
    <dl className="figures">
      <div>
        <dt>{subtotalLabel}</dt>
        <dd>
          <Money cents={split.subtotal_cents} />
        </dd>
      </div>
      <div>
        <dt>
          <span className="swatch swatch--cogs" aria-hidden="true" />
          COGS
        </dt>
        <dd>
          <Money cents={split.cogs_total_cents} />
        </dd>
      </div>
      <div>
        <dt>
          <span className="swatch swatch--fee" aria-hidden="true" />
          Platform fee
        </dt>
        <dd>
          <Money cents={split.platform_fee_cents} />
        </dd>
      </div>
      <div>
        <dt>
          <span className="swatch swatch--payout" aria-hidden="true" />
          You receive
        </dt>
        <dd>
          <Money cents={split.provider_payout_cents} emphasize />
        </dd>
      </div>
    </dl>
  );
}

function OrderSummary({
  split,
  subtotalLabel,
  children,
}: {
  split: SplitFigures | null;
  subtotalLabel: string;
  children: ReactNode;
}) {
  return (
    <aside className="summary panel panel--sticky">
      {split !== null ? (
        <>
          <div className="summary__bar">
            <SplitBar
              subtotalCents={split.subtotal_cents}
              cogsCents={split.cogs_total_cents}
              feeCents={split.platform_fee_cents}
              payoutCents={split.provider_payout_cents}
              subtotalCaption={subtotalLabel}
            />
          </div>
          <SplitFigures split={split} subtotalLabel={subtotalLabel} />
        </>
      ) : (
        <p className="muted">The split appears when every line is valid.</p>
      )}
      {children}
    </aside>
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
    return <InlineError message={loadError} />;
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
        dosing: product.default_dosing,
        note: "",
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
        lines: shownPreview.lines.map((line, index) => {
          const draft = lines[index];
          const note = draft?.note.trim() ?? "";
          return {
            product_id: line.product_id,
            qty: line.qty,
            unit_price_cents: line.unit_price_cents,
            dosing: draft?.dosing.trim() ?? "",
            note: note.length === 0 ? null : note,
          };
        }),
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
    let confirmReason: string | null = null;
    if (busy) {
      confirmReason = "Creating the order";
    } else if (patientId === null) {
      confirmReason = "Pick a patient";
    } else if (previewProblem !== null) {
      confirmReason = "Fix the errors above";
    } else if (shownPreview === null) {
      confirmReason = "Checking prices";
    }
    return (
      <div className="builder">
        <div className="builder__main">
          <h1>Review order</h1>
          {patient !== null ? (
            <dl className="meta-pair">
              <dt>Patient</dt>
              <dd>{patient.name}</dd>
            </dl>
          ) : null}
          {shownPreview !== null ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Product</th>
                    <th className="num">Qty</th>
                    <th className="num">Unit price</th>
                    <th className="num">Line total</th>
                  </tr>
                </thead>
                <tbody>
                  {shownPreview.lines.map((line, index) => (
                    <ReviewLine
                      key={`${line.product_id}-${index}`}
                      line={line}
                      productName={productById(products, line.product_id)?.name ?? "Product"}
                      dosing={lines[index]?.dosing.trim() ?? ""}
                      note={lines[index]?.note.trim() ?? ""}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
        <OrderSummary split={shownPreview} subtotalLabel="Patient pays">
          <p className="muted">Later catalog changes don&apos;t affect this order.</p>
          {reviewError !== null ? <InlineError message={reviewError} /> : null}
          <div className="btn-row">
            <button
              type="button"
              disabled={busy || shownPreview === null || patientId === null || previewProblem !== null}
              onClick={() => void confirmOrder()}
            >
              Confirm order
            </button>
            {confirmReason !== null ? <p className="btn-hint">{confirmReason}</p> : null}
          </div>
          <div className="btn-row">
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
          </div>
        </OrderSummary>
      </div>
    );
  }

  const orderProblem =
    previewProblem !== null && previewProblem.lineIndex === null ? previewProblem.message : null;

  return (
    <div className="builder">
      <div className="builder__main">
        <h1>New order</h1>
        <div className="builder__controls">
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
                  {product.name}
                </option>
              ))}
            </select>
          </label>
          <div className="btn-row">
            <button
              type="button"
              className="secondary"
              disabled={selectedAddId === ""}
              onClick={addLine}
            >
              Add
            </button>
            {enabled.length === 0 ? <p className="btn-hint">No enabled products.</p> : null}
          </div>
        </div>
        {lines.length > 0 ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th className="nowrap">Stock</th>
                  <th className="num">Qty</th>
                  <th className="num">Unit price</th>
                  <th className="num nowrap">Line total</th>
                  <th>
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line, index) => {
                  const product = productById(products, line.productId);
                  const localError = lineError(line);
                  const remoteError =
                    previewProblem?.lineIndex === index ? previewProblem.message : null;
                  const message = localError ?? remoteError;
                  const priced = shownPreview?.lines[index];
                  const ready = readyLines([line]);
                  const stockWarning =
                    priced !== undefined && ready !== null
                      ? stockOverWarning(ready[0].qty, priced.stock_available)
                      : null;
                  const name = product?.name ?? "Product";
                  return (
                    <DraftRow
                      key={line.key}
                      name={name}
                      stock={product !== undefined ? stockLabel(product.stock_qty) : null}
                      outOfStock={product?.stock_qty === 0}
                      qty={line.qty}
                      price={line.price}
                      dosing={line.dosing}
                      note={line.note}
                      lineTotalCents={priced?.line_total_cents}
                      message={message}
                      stockWarning={stockWarning}
                      onQty={(qty) => {
                        editLines(
                          lines.map((item) => (item.key === line.key ? { ...item, qty } : item)),
                        );
                      }}
                      onPrice={(price) => {
                        editLines(
                          lines.map((item) => (item.key === line.key ? { ...item, price } : item)),
                        );
                      }}
                      onDosing={(dosing) => {
                        editLines(
                          lines.map((item) => (item.key === line.key ? { ...item, dosing } : item)),
                        );
                      }}
                      onNote={(note) => {
                        editLines(
                          lines.map((item) => (item.key === line.key ? { ...item, note } : item)),
                        );
                      }}
                      onRemove={() => {
                        editLines(lines.filter((item) => item.key !== line.key));
                      }}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
      <OrderSummary split={shownPreview} subtotalLabel="Subtotal">
        {orderProblem !== null ? <InlineError message={orderProblem} /> : null}
        <div className="btn-row">
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
          {continueReason !== null ? <p className="btn-hint">{continueReason}</p> : null}
        </div>
      </OrderSummary>
    </div>
  );
}

function DraftRow({
  name,
  stock,
  outOfStock,
  qty,
  price,
  dosing,
  note,
  lineTotalCents,
  message,
  stockWarning,
  onQty,
  onPrice,
  onDosing,
  onNote,
  onRemove,
}: {
  name: string;
  stock: string | null;
  outOfStock: boolean;
  qty: string;
  price: string;
  dosing: string;
  note: string;
  lineTotalCents: number | undefined;
  message: string | null;
  stockWarning: string | null;
  onQty: (qty: string) => void;
  onPrice: (price: string) => void;
  onDosing: (dosing: string) => void;
  onNote: (note: string) => void;
  onRemove: () => void;
}) {
  return (
    <>
      <tr>
        <td className="cell-title">{name}</td>
        <td className="nowrap">
          {stock !== null ? (
            <span className={outOfStock ? "stock stock--out" : "stock"}>{stock}</span>
          ) : (
            "—"
          )}
        </td>
        <td className="num">
          <input
            className="input-qty"
            aria-label={`Quantity for ${name}`}
            value={qty}
            inputMode="numeric"
            onChange={(event) => {
              onQty(event.target.value);
            }}
          />
        </td>
        <td className="num">
          <input
            className="input-money"
            aria-label={`Unit price for ${name}`}
            value={price}
            inputMode="decimal"
            onChange={(event) => {
              onPrice(event.target.value);
            }}
          />
        </td>
        <td className="num nowrap">
          {lineTotalCents !== undefined ? <Money cents={lineTotalCents} /> : "—"}
        </td>
        <td>
          <button type="button" className="secondary" onClick={onRemove}>
            Remove
          </button>
        </td>
      </tr>
      <tr>
        <td colSpan={6}>
          <label>
            Dosing
            <input
              aria-label={`Dosing for ${name}`}
              value={dosing}
              maxLength={200}
              onChange={(event) => {
                onDosing(event.target.value);
              }}
            />
          </label>
          <label>
            Why I recommend this
            <textarea
              aria-label={`Note for ${name}`}
              value={note}
              maxLength={500}
              rows={2}
              placeholder="Optional. Shown to the patient."
              onChange={(event) => {
                onNote(event.target.value);
              }}
            />
          </label>
        </td>
      </tr>
      {message !== null ? (
        <tr>
          <td colSpan={6}>
            <InlineError message={message} />
          </td>
        </tr>
      ) : null}
      {message === null && stockWarning !== null ? (
        <tr>
          <td colSpan={6}>
            <p className="muted">{stockWarning}</p>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function ReviewLine({
  line,
  productName,
  dosing,
  note,
}: {
  line: PreviewLine;
  productName: string;
  dosing: string;
  note: string;
}) {
  return (
    <tr>
      <td>
        <div className="cell-title">{productName}</div>
        {dosing.length > 0 ? <div className="muted">{dosing}</div> : null}
        {note.length > 0 ? <div className="muted">{note}</div> : null}
      </td>
      <td className="num">{line.qty}</td>
      <td className="num">
        <Money cents={line.unit_price_cents} />
      </td>
      <td className="num">
        <Money cents={line.line_total_cents} />
      </td>
    </tr>
  );
}

function CreatedOrder({ order, patientName }: { order: OrderResponse; patientName: string }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);
  const patientUrl = new URL(order.patient_link, window.location.origin).toString();

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(patientUrl);
      setCopied(true);
      setCopyError(null);
    } catch {
      setCopied(false);
      setCopyError("Could not copy the link");
    }
  }

  return (
    <div className="created">
      <h1>Order created</h1>
      <p>Patient {patientName}</p>
      <aside className="summary panel">
        <div className="summary__bar">
          <SplitBar
            subtotalCents={order.subtotal_cents}
            cogsCents={order.cogs_total_cents}
            feeCents={order.platform_fee_cents}
            payoutCents={order.provider_payout_cents}
            subtotalCaption="Patient pays"
          />
        </div>
        <SplitFigures split={order} subtotalLabel="Patient pays" />
        <div className="stack">
          <span className="field-label" id="patient-link-label">
            Patient link
          </span>
          <div className="copy-field">
            <input
              aria-labelledby="patient-link-label"
              readOnly
              value={patientUrl}
              onFocus={(event) => {
                event.target.select();
              }}
            />
            <button type="button" onClick={() => void copyLink()}>
              Copy
            </button>
          </div>
          {copied ? <p className="muted">Copied</p> : null}
          {copyError !== null ? <InlineError message={copyError} /> : null}
        </div>
      </aside>
    </div>
  );
}
