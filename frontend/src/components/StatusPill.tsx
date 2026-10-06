type Status = "pending_payment" | "paid" | "cancelled" | string;

const LABELS: Record<string, string> = {
  pending_payment: "Pending payment",
  paid: "Paid",
  cancelled: "Cancelled",
};

function toneFor(status: Status): "warn" | "good" | "neutral" {
  if (status === "paid") {
    return "good";
  }
  if (status === "pending_payment") {
    return "warn";
  }
  return "neutral";
}

export function StatusPill({ status }: { status: Status }) {
  const label = LABELS[status] ?? status;
  return <span className={`status-pill status-pill--${toneFor(status)}`}>{label}</span>;
}
