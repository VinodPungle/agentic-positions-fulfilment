import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { usePersona } from "../context/PersonaContext";
import { Button } from "../components/ui/button";
import { Checkbox } from "../components/ui/checkbox";
import { toast } from "sonner";

export default function Approvals() {
  const { user } = usePersona();
  const [approvals, setApprovals] = useState([]);
  const [selected, setSelected] = useState({});

  const load = useCallback(() => { api.get("/approvals").then((r) => setApprovals(r.data)); }, []);
  useEffect(() => { load(); }, [load, user?.id]);

  const decide = async (ap, decision) => {
    const ids = Object.entries(selected).filter(([k, v]) => v && k.startsWith(ap.id)).map(([k]) => k.split("::")[1]);
    if (decision === "approve" && !ids.length) return toast.error("Select at least one candidate");
    try {
      const r = await api.post(`/approvals/${ap.id}/decide`, { decision, approved_candidate_ids: ids, comment: "" });
      toast[r.data.already_decided ? "info" : "success"](r.data.already_decided ? "Already decided (idempotent)" : `Shortlist ${r.data.status}`);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
  };

  const decideFitment = async (ap, decision) => {
    try {
      const r = await api.post(`/interviews/${ap.id}/fitment`, { decision, comment: "" });
      toast[r.data.already_decided ? "info" : "success"](r.data.already_decided ? "Already decided (idempotent)" : decision === "fit" ? "Marked Internal Fit" : "Marked Internal Fit Rejected");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
  };

  const pending = approvals.filter((a) => a.status === "pending");
  const pendingShortlists = pending.filter((a) => a.type === "shortlist");
  const pendingFitments = pending.filter((a) => a.type === "fitment");
  const decided = approvals.filter((a) => a.type === "shortlist" && a.status !== "pending");
  const canApprove = user && ["pm", "service_line_leader", "admin"].includes(user.role);

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="font-heading font-black text-4xl sm:text-5xl tracking-tight leading-none">Approvals</h1>
        <p className="font-mono text-xs text-white/40 mt-2 tracking-[0.15em]">HUMAN-IN-THE-LOOP GATES · {pending.length} PENDING IN YOUR SCOPE</p>
      </div>
      {!canApprove && <p className="font-mono text-xs text-[#FFD60A] border border-[#FFD60A]/30 bg-[#FFD60A]/5 p-4" data-testid="approval-role-warning">Your role ({user?.role}) cannot decide approvals — only project PMs (or Service Line Leader override).</p>}
      {!pending.length && <p className="font-mono text-sm text-white/40 border border-white/15 bg-[#121212] p-6" data-testid="no-pending-approvals">// no pending approvals in your scope</p>}

      {pendingShortlists.length > 0 && (
        <div className="space-y-4">
          <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase">Gate 1 · Shortlist approval</p>
          {pendingShortlists.map((ap) => (
            <div key={ap.id} className="border border-white/15 bg-[#121212]" data-testid={`approval-card-${ap.ticket_number}`}>
              <div className="p-5 border-b border-white/15 flex items-center justify-between">
                <div>
                  <Link to={`/positions/${ap.position_id}`} className="font-mono text-sm text-[#007AFF] hover:underline">{ap.ticket_number}</Link>
                  <p className="font-semibold mt-1">{ap.title}</p>
                </div>
                <div className="flex gap-2">
                  <Button onClick={() => decide(ap, "approve")} disabled={!canApprove} data-testid={`approve-button-${ap.ticket_number}`} className="bg-[#32D74B] hover:bg-[#28B33E] text-black rounded-sm">Shortlist</Button>
                  <Button onClick={() => decide(ap, "reject")} disabled={!canApprove} variant="outline" data-testid={`reject-button-${ap.ticket_number}`} className="border-[#FF3B30]/50 text-[#FF3B30] hover:bg-[#FF3B30]/10 rounded-sm">Reject</Button>
                </div>
              </div>
              <div className="divide-y divide-white/10">
                {(ap.ranked_list?.candidates || []).sort((a, b) => a.rank - b.rank).map((c) => (
                  <label key={c.candidate_id} className="flex items-start gap-4 p-5 cursor-pointer hover:bg-white/[0.02]">
                    <Checkbox checked={!!selected[`${ap.id}::${c.candidate_id}`]} data-testid={`approval-select-${ap.ticket_number}-rank${c.rank}`}
                      onCheckedChange={(v) => setSelected((s) => ({ ...s, [`${ap.id}::${c.candidate_id}`]: !!v }))}
                      className="mt-1 border-white/40 data-[state=checked]:bg-[#007AFF] data-[state=checked]:border-[#007AFF]" />
                    <span className="font-heading font-black text-xl text-[#007AFF]">#{c.rank}</span>
                    <div>
                      <span className="font-semibold">{c.name}</span> <span className="font-mono text-xs text-[#32D74B] ml-2">{c.score}/100</span>
                      <p className="text-sm text-white/60 mt-1">{c.reasoning}</p>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {pendingFitments.length > 0 && (
        <div className="space-y-4">
          <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase">Gate 2 · Internal fit decision</p>
          {pendingFitments.map((ap) => (
            <div key={ap.id} className="border border-[#FFD60A]/40 bg-[#FFD60A]/5" data-testid={`fitment-approval-card-${ap.ticket_number}`}>
              <div className="p-5 border-b border-[#FFD60A]/20 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <Link to={`/positions/${ap.position_id}`} className="font-mono text-sm text-[#007AFF] hover:underline">{ap.ticket_number}</Link>
                  <p className="font-semibold mt-1">{ap.title}</p>
                  <p className="font-mono text-xs text-white/50 mt-1">{ap.candidate_name} · interviewed by {ap.interviewer_name} · interviewer said <span className={ap.interview_result === "pass" ? "text-[#32D74B]" : "text-[#FF3B30]"}>{ap.interview_result}</span></p>
                </div>
                <div className="flex gap-2 shrink-0">
                  <Button onClick={() => decideFitment(ap, "fit")} disabled={!canApprove} data-testid={`mark-fit-button-${ap.ticket_number}`} className="bg-[#32D74B] hover:bg-[#28B33E] text-black rounded-sm">Mark Internal Fit</Button>
                  <Button onClick={() => decideFitment(ap, "reject")} disabled={!canApprove} variant="outline" data-testid={`mark-reject-button-${ap.ticket_number}`} className="border-[#FF3B30]/50 text-[#FF3B30] hover:bg-[#FF3B30]/10 rounded-sm">Reject</Button>
                </div>
              </div>
              {ap.transcript_summary && (
                <div className="p-5">
                  <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase mb-2">Monitoring Agent · transcript summary</p>
                  <p className="text-sm text-white/70 whitespace-pre-wrap leading-relaxed">{ap.transcript_summary}</p>
                  {ap.feedback_comments && <p className="text-xs text-white/50 mt-3 border-t border-white/10 pt-3">Interviewer comments: {ap.feedback_comments}</p>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {decided.length > 0 && (
        <div>
          <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase mb-3">Decision history</p>
          <div className="border border-white/15 bg-[#121212] divide-y divide-white/10">
            {decided.map((ap) => (
              <div key={ap.id} className="p-4 flex items-center gap-4 font-mono text-xs">
                <span className="text-[#007AFF]">{ap.ticket_number}</span>
                <span className="text-white/70">{ap.title}</span>
                <span className={`ml-auto uppercase ${ap.status === "approved" ? "text-[#32D74B]" : "text-[#FF3B30]"}`}>{ap.status}</span>
                <span className="text-white/40">{ap.actor}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
