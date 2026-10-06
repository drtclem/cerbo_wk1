import { Link } from "react-router";

type EmptyStateProps = {
  children: string;
  actionTo?: string;
  actionLabel?: string;
};

export function EmptyState({ children, actionTo, actionLabel }: EmptyStateProps) {
  return (
    <p className="empty-state">
      {children}
      {actionTo !== undefined && actionLabel !== undefined ? (
        <>
          {" "}
          <Link to={actionTo}>{actionLabel}</Link>
        </>
      ) : null}
    </p>
  );
}
