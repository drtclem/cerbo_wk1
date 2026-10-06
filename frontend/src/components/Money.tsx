import { formatCents } from "../lib/money.ts";

type MoneyProps = {
  cents: number;
  /** Magenta emphasis for "you receive". */
  emphasize?: boolean;
  className?: string;
};

export function Money({ cents, emphasize = false, className }: MoneyProps) {
  const classes = ["money", emphasize ? "money--receive" : null, className]
    .filter((part): part is string => part !== null && part !== undefined && part !== "")
    .join(" ");
  return <span className={classes}>{formatCents(cents)}</span>;
}
