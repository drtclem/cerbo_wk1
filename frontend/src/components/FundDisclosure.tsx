import { useState } from "react";

import { DEMO_FUND_NOTE } from "../lib/donation.ts";

type FundDisclosureProps = {
  name: string;
  url: string | null;
  description: string | null;
  /** When false, omit the demo note (parent already shows it once). */
  showNote?: boolean;
};

export function FundDisclosure({
  name,
  url,
  description,
  showNote = true,
}: FundDisclosureProps) {
  const [open, setOpen] = useState(false);
  const detailId = `fund-detail-${name.replace(/\W+/g, "-").toLowerCase()}`;

  return (
    <div className="fund">
      <button
        type="button"
        className="fund__toggle"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={() => {
          setOpen((current) => !current);
        }}
      >
        {name}
      </button>
      {open ? (
        <div className="fund__detail" id={detailId}>
          {description !== null && description.length > 0 ? (
            <p className="fund__description">{description}</p>
          ) : null}
          {url !== null && url.length > 0 ? (
            <p>
              <a href={url} target="_blank" rel="noopener noreferrer">
                Learn more
              </a>
            </p>
          ) : null}
          {showNote ? <p className="muted fund__note">{DEMO_FUND_NOTE}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

export function DemoFundNote() {
  return <p className="muted fund__note">{DEMO_FUND_NOTE}</p>;
}
