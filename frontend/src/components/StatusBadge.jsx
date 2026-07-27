import { STATUS_META } from "../lib/api";

export const StatusBadge = ({ status }) => {
  const meta = STATUS_META[status] || { label: status, color: "text-muted-foreground border-border" };
  return (
    <span data-testid={`status-badge-${status}`}
      className={`inline-block font-mono text-[10px] tracking-[0.15em] uppercase border px-2 py-1 ${meta.color}`}>
      {meta.label}
    </span>
  );
};
