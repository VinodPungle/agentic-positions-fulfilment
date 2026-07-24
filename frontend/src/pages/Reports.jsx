import { useEffect, useState, useCallback } from "react";
import { api } from "../lib/api";
import { usePersona } from "../context/PersonaContext";
import { Button } from "../components/ui/button";
import { toast } from "sonner";
import { Send } from "lucide-react";

export default function Reports() {
  const { user } = usePersona();
  const [summary, setSummary] = useState(null);
  const [lastDigest, setLastDigest] = useState(null);

  const load = useCallback(() => { api.get("/reports/summary").then((r) => setSummary(r.data)); }, []);
  useEffect(() => { load(); }, [load, user?.id]);

  const distribute = async () => {
    try {
      const r = await api.post("/reports/send");
      setLastDigest(r.data.digest);
      toast[r.data.already_sent_today ? "info" : "success"](
        r.data.already_sent_today ? "Today's report was already distributed — duplicate blocked by idempotency key" : "Report distributed to stakeholders (Slack + email)");
    } catch (e) { toast.error(e.message); }
  };

  if (!summary) return <div className="p-8 font-mono text-sm text-white/40">loading…</div>;

  return (
    <div className="p-8 space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-heading font-black text-4xl sm:text-5xl tracking-tight leading-none">Reports</h1>
          <p className="font-mono text-xs text-white/40 mt-2 tracking-[0.15em]">
            REPORTING AGENT · SCOPE: {Array.isArray(summary.scope) ? summary.scope.join(", ").toUpperCase() : "ALL PROJECTS"}
          </p>
        </div>
        <Button onClick={distribute} data-testid="distribute-report-button" className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm">
          <Send size={14} className="mr-2" /> Distribute to stakeholders
        </Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[["Total positions", summary.total_positions], ["Pending approvals", summary.pending_approvals],
          ["SLA breaches", summary.sla_breaches], ["Filled", summary.by_status?.FILLED || 0]].map(([label, val]) => (
          <div key={label} className="border border-white/15 bg-[#121212] p-6">
            <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase">{label}</p>
            <p className="font-heading font-black text-4xl mt-2">{val}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="border border-white/15 bg-[#121212]" data-testid="report-by-project">
          <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase p-4 border-b border-white/15">By project</p>
          <table className="w-full font-mono text-xs">
            <thead><tr className="border-b border-white/10 text-white/40">
              <th className="text-left p-3 font-normal">PROJECT</th><th className="text-right p-3 font-normal">TOTAL</th>
              <th className="text-right p-3 font-normal">IN PIPELINE</th><th className="text-right p-3 font-normal">FILLED</th>
            </tr></thead>
            <tbody>
              {summary.by_project.map((bp) => (
                <tr key={bp.project} className="border-b border-white/5">
                  <td className="p-3 text-[#007AFF]">{bp.project}</td>
                  <td className="p-3 text-right">{bp.total}</td>
                  <td className="p-3 text-right">{bp.in_pipeline}</td>
                  <td className="p-3 text-right text-[#32D74B]">{bp.filled}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="border border-white/15 bg-[#121212]" data-testid="report-by-status">
          <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase p-4 border-b border-white/15">By status</p>
          <div className="divide-y divide-white/5">
            {Object.entries(summary.by_status).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between p-3 font-mono text-xs">
                <span className="text-white/70">{k}</span><span>{v}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {lastDigest && (
        <div className="border border-white/15 bg-black p-6" data-testid="last-digest">
          <p className="font-mono text-[10px] tracking-[0.2em] text-[#007AFF] uppercase mb-2">Distributed digest</p>
          <pre className="font-mono text-xs text-[#7cb8ff] whitespace-pre-wrap leading-relaxed">{lastDigest}</pre>
        </div>
      )}
    </div>
  );
}
