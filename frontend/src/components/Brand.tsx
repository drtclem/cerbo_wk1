/** Original app mark (a two-tone capsule) and wordmark. Not Cerbo's logo. */

export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg
      className="brand-mark"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <g transform="rotate(-45 16 16)">
        <path className="brand-mark__fill" d="M16 10.5H9.5a5.5 5.5 0 0 0 0 11H16Z" />
        <path
          className="brand-mark__outline"
          d="M16 10.5h6.5a5.5 5.5 0 0 1 0 11H16Z"
          strokeWidth="1.5"
        />
      </g>
    </svg>
  );
}

export function BrandText() {
  return (
    <span className="app-brand__text">
      <span className="app-brand__name">Cerbo</span>
      <span className="app-brand__product">Supplements</span>
    </span>
  );
}

export const DEMO_DISCLAIMER =
  "Demo built for the Cerbo take-home project. Not affiliated with or operated by Cerbo.";
