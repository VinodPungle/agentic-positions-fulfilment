import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, BOARD_COLUMNS, STATUS_META } from "../lib/api";
import { usePersona } from "../context/PersonaContext";
import { StatusBadge } from "../components/StatusBadge";
import { Users, AlertTriangle, CheckSquare, Briefcase } from "lucide-react";

const Stat = ({ label, value, icon: Icon, accent, testId }) => (
  <div data-testid={testId} className="border border-white/15 bg-[#121212] p-6 flex items-start justify-between hover:-translate-y-[1px] transition-transform duration-150">
    <div>
      <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase">{label}</p>
      <p className={`font-heading font-black text-4xl mt-2 ${accent || "text-white"}`}>{value}</p>
    </div>
    <Icon size={18} className="text-white/30" />
  </div>
);

export default function Dashboard() {
  const { user } = usePersona();
  const [positions, setPositions] = useState([]);
  const [summary, setSummary] = useState(null);

  useEffect(() => {
    if (!user) return;
    api.get("/positions").then((r) => setPositions(r.data));
    api.get("/reports/summary").then((r) => setSummary(r.data));
  }, [user?.id]);

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="font-heading font-black text-4xl sm:text-5xl tracking-tight leading-none">Pipeline</h1>
        <p className="font-mono text-xs text-white/40 mt-2 tracking-[0.15em]">
          {user?.role === "pm" ? `SCOPED TO ${user.projects.join(", ").toUpperCase()}` : "ACCOUNT-WIDE VIEW"} · {positions.length} POSITIONS
        </p>
      </div>

      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <Stat testId="stat-total" label="Total positions" value={summary.total_positions} icon={Briefcase} />
          <Stat testId="stat-approvals" label="Pending approvals" value={summary.pending_approvals} icon={CheckSquare} accent={summary.pending_approvals ? "text-[#FFD60A]" : undefined} />
          <Stat testId="stat-sla" label="SLA breaches" value={summary.sla_breaches} icon={AlertTriangle} accent={summary.sla_breaches ? "text-[#FF3B30]" : undefined} />
          <Stat testId="stat-filled" label="Filled" value={summary.by_status?.FILLED || 0} icon={Users} accent="text-[#32D74B]" />
        </div>
      )}

      <div className="overflow-x-auto pb-4">
        <div className="flex gap-4 min-w-max">
          {BOARD_COLUMNS.map((col) => {
            const items = positions.filter((p) => col.statuses.includes(p.status));
            return (
              <div key={col.key} className="w-64 shrink-0 border border-white/15 bg-[#0D0D0D]" data-testid={`board-column-${col.key}`}>
                <div className="px-4 py-3 border-b border-white/15 flex items-center justify-between">
                  <span className="font-mono text-[10px] tracking-[0.2em] text-white/50 uppercase">
                    {col.label || STATUS_META[col.key]?.label || col.key}
                  </span>
                  <span className="font-mono text-[10px] text-white/40">{items.length}</span>
                </div>
                <div className="p-3 space-y-3 min-h-[120px]">
                  {items.map((p) => (
                    <Link to={`/positions/${p.id}`} key={p.id} data-testid={`position-card-${p.ticket_number}`}
                      className="block border border-white/10 bg-[#121212] p-4 hover:border-[#007AFF]/50 hover:-translate-y-[1px] transition-[border-color,transform] duration-150">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs text-[#007AFF]">{p.ticket_number}</span>
                        <span className={`font-mono text-[9px] uppercase ${p.priority === "high" ? "text-[#FF3B30]" : "text-white/40"}`}>{p.priority}</span>
                      </div>
                      <p className="text-sm font-medium mt-2 leading-snug">{p.title}</p>
                      <div className="flex items-center justify-between mt-3">
                        <span className="font-mono text-[10px] text-white/40">{p.project_name}</span>
                        <span className="font-mono text-[10px] text-white/40">{p.candidate_count} CVs</span>
                      </div>
                      <div className="mt-2"><StatusBadge status={p.status} /></div>
                    </Link>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
