import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../lib/api";
import { usePersona } from "../context/PersonaContext";
import { StatusBadge } from "../components/StatusBadge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "../components/ui/dialog";
import { Checkbox } from "../components/ui/checkbox";
import { toast } from "sonner";
import { ArrowLeft, Sparkles, CalendarPlus, Loader2, UserPlus } from "lucide-react";

export default function PositionDetail() {
  const { id } = useParams();
  const { user } = usePersona();
  const [pos, setPos] = useState(null);
  const [err, setErr] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [selected, setSelected] = useState({});
  const [newCand, setNewCand] = useState({ name: "", email: "", cv_text: "" });
  const [dialogOpen, setDialogOpen] = useState(false);

  const load = useCallback(() => {
    api.get(`/positions/${id}`).then((r) => {
      setPos(r.data);
      setErr(null);
      const sel = {};
      (r.data.evaluation?.ranked_list?.candidates || []).forEach((c) => { if (c.rank <= 2) sel[c.candidate_id] = true; });
      setSelected((prev) => (Object.keys(prev).length ? prev : sel));
    }).catch((e) => setErr(e.response?.data?.detail || e.message));
  }, [id]);

  useEffect(() => { load(); }, [load, user?.id]);

  if (err) return (
    <div className="p-8">
      <p className="font-mono text-sm text-[#FF3B30]" data-testid="position-error">ACCESS: {err}</p>
      <Link to="/" className="font-mono text-xs text-[#007AFF] mt-4 inline-block">← back to pipeline</Link>
    </div>
  );
  if (!pos) return <div className="p-8 font-mono text-sm text-white/40">loading…</div>;

  const runEvaluation = async () => {
    setEvaluating(true);
    try {
      const r = await api.post(`/positions/${id}/evaluate`);
      toast.success(r.data.reused ? "Identical input — existing evaluation reused (idempotent)" : "Evaluation complete — awaiting PM approval");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    setEvaluating(false);
  };

  const decide = async (decision) => {
    const ids = Object.keys(selected).filter((k) => selected[k]);
    if (decision === "approve" && !ids.length) return toast.error("Select at least one candidate");
    try {
      const r = await api.post(`/approvals/${pos.approval.id}/decide`, { decision, approved_candidate_ids: ids, comment: "" });
      if (r.data.already_decided) toast.info("Already decided (idempotent)");
      else toast.success(decision === "approve" ? "Shortlist approved" : "Shortlist rejected");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
  };

  const schedule = async () => {
    setScheduling(true);
    try {
      const r = await api.post(`/positions/${id}/schedule`);
      if (r.data.created.length) toast.success(`${r.data.created.length} interview(s) scheduled`);
      else toast.info("Nothing to schedule — active interviews already exist (idempotent)");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    setScheduling(false);
  };

  const addCandidate = async () => {
    try {
      await api.post(`/positions/${id}/candidates`, newCand);
      toast.success("Candidate added");
      setDialogOpen(false);
      setNewCand({ name: "", email: "", cv_text: "" });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
  };

  const ranked = pos.evaluation?.ranked_list?.candidates || [];
  const approvalPending = pos.approval?.status === "pending";
  const approvalApproved = pos.approval?.status === "approved";
  const canApprove = user && (user.role === "pm" || user.role === "dm" || user.role === "admin");

  return (
    <div className="p-8 space-y-6">
      <Link to="/" className="font-mono text-xs text-white/40 hover:text-white flex items-center gap-2 transition-colors duration-150" data-testid="back-to-pipeline">
        <ArrowLeft size={12} /> PIPELINE
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-4 border border-white/15 bg-[#121212] p-6">
        <div>
          <div className="flex items-center gap-3">
            <span className="font-mono text-sm text-[#007AFF]">{pos.ticket_number}</span>
            <StatusBadge status={pos.status} />
          </div>
          <h1 className="font-heading font-black text-3xl tracking-tight mt-2">{pos.title}</h1>
          <p className="font-mono text-xs text-white/40 mt-1">
            {pos.project_name} · {pos.client} · PRIORITY {pos.priority?.toUpperCase()} · SKILLS: {(pos.meta?.skills || []).join(", ") || "n/a"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={runEvaluation} disabled={evaluating || !pos.candidate_count} data-testid="run-evaluation-button"
            className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm">
            {evaluating ? <Loader2 size={14} className="animate-spin mr-2" /> : <Sparkles size={14} className="mr-2" />}
            {evaluating ? "Evaluating…" : "Run AI Evaluation"}
          </Button>
          {approvalApproved && (
            <Button onClick={schedule} disabled={scheduling} data-testid="schedule-interviews-button"
              className="bg-[#32D74B] hover:bg-[#28B33E] text-black rounded-sm">
              {scheduling ? <Loader2 size={14} className="animate-spin mr-2" /> : <CalendarPlus size={14} className="mr-2" />}
              Schedule Interviews
            </Button>
          )}
        </div>
      </div>

      <Tabs defaultValue="evaluation">
        <TabsList className="bg-[#121212] border border-white/15 rounded-none h-auto p-0">
          {["evaluation", "candidates", "interviews", "timeline", "jd"].map((t) => (
            <TabsTrigger key={t} value={t} data-testid={`tab-${t}`}
              className="rounded-none font-mono text-xs tracking-[0.15em] uppercase px-5 py-3 data-[state=active]:bg-[#007AFF]/10 data-[state=active]:text-[#007AFF] data-[state=active]:shadow-none">
              {t === "jd" ? "Job Description" : t}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="evaluation" className="mt-4 space-y-4">
          {!pos.evaluation && <p className="font-mono text-sm text-white/40 border border-white/15 bg-[#121212] p-6" data-testid="no-evaluation">// no evaluation yet — run AI evaluation on the candidates</p>}
          {pos.evaluation && (
            <>
              <div className="border border-white/15 bg-[#121212] p-6">
                <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase mb-2">Evaluation Agent · {pos.evaluation.model} · RankedCandidateList.v1</p>
                <p className="text-sm text-white/80 leading-relaxed">{pos.evaluation.ranked_list?.summary}</p>
              </div>
              {ranked.sort((a, b) => a.rank - b.rank).map((c) => (
                <div key={c.candidate_id} className="border border-white/15 bg-[#121212] p-6 flex gap-5" data-testid={`ranked-candidate-${c.rank}`}>
                  {approvalPending && canApprove && (
                    <Checkbox checked={!!selected[c.candidate_id]} data-testid={`select-candidate-${c.rank}`}
                      onCheckedChange={(v) => setSelected((s) => ({ ...s, [c.candidate_id]: !!v }))}
                      className="mt-1 border-white/40 data-[state=checked]:bg-[#007AFF] data-[state=checked]:border-[#007AFF]" />
                  )}
                  <div className="font-heading font-black text-3xl text-[#007AFF] w-12">#{c.rank}</div>
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <span className="font-semibold">{c.name}</span>
                      <span className="font-mono text-xs text-[#32D74B]">{c.score}/100</span>
                    </div>
                    <p className="text-sm text-white/70 mt-2 leading-relaxed">{c.reasoning}</p>
                    <div className="flex flex-wrap gap-2 mt-3">
                      {(c.strengths || []).map((s) => <span key={s} className="font-mono text-[10px] border border-[#32D74B]/40 text-[#32D74B] px-2 py-1">+ {s}</span>)}
                      {(c.gaps || []).map((g) => <span key={g} className="font-mono text-[10px] border border-[#FF3B30]/40 text-[#FF3B30] px-2 py-1">− {g}</span>)}
                    </div>
                  </div>
                </div>
              ))}
              {approvalPending && (
                <div className="border border-[#FFD60A]/40 bg-[#FFD60A]/5 p-6 flex flex-wrap items-center justify-between gap-4" data-testid="approval-gate">
                  <div>
                    <p className="font-mono text-xs tracking-[0.2em] text-[#FFD60A] uppercase">Human-in-the-loop gate</p>
                    <p className="text-sm text-white/70 mt-1">
                      {canApprove ? "Select candidates and approve the shortlist to unlock scheduling." : "Only the project PM (or DM override) can approve this shortlist."}
                    </p>
                  </div>
                  {canApprove && (
                    <div className="flex gap-2">
                      <Button onClick={() => decide("approve")} data-testid="approve-shortlist-button" className="bg-[#32D74B] hover:bg-[#28B33E] text-black rounded-sm">Approve shortlist</Button>
                      <Button onClick={() => decide("reject")} data-testid="reject-shortlist-button" variant="outline" className="border-[#FF3B30]/50 text-[#FF3B30] hover:bg-[#FF3B30]/10 rounded-sm">Reject</Button>
                    </div>
                  )}
                </div>
              )}
              {pos.approval && pos.approval.status !== "pending" && (
                <p className="font-mono text-xs text-white/50 border border-white/15 bg-[#121212] p-4" data-testid="approval-status">
                  APPROVAL: {pos.approval.status.toUpperCase()} by {pos.approval.actor}
                </p>
              )}
            </>
          )}
        </TabsContent>

        <TabsContent value="candidates" className="mt-4 space-y-4">
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="outline" data-testid="add-candidate-button" className="border-white/20 rounded-sm hover:bg-white/5"><UserPlus size={14} className="mr-2" />Add candidate</Button>
            </DialogTrigger>
            <DialogContent className="bg-[#121212] border-white/20 text-white">
              <DialogHeader><DialogTitle className="font-heading">Add candidate</DialogTitle></DialogHeader>
              <Input placeholder="Name" value={newCand.name} data-testid="candidate-name-input" onChange={(e) => setNewCand({ ...newCand, name: e.target.value })} className="bg-black border-white/20 rounded-sm" />
              <Input placeholder="Email" value={newCand.email} data-testid="candidate-email-input" onChange={(e) => setNewCand({ ...newCand, email: e.target.value })} className="bg-black border-white/20 rounded-sm" />
              <Textarea placeholder="Paste CV text…" rows={8} value={newCand.cv_text} data-testid="candidate-cv-input" onChange={(e) => setNewCand({ ...newCand, cv_text: e.target.value })} className="bg-black border-white/20 rounded-sm font-mono text-xs" />
              <Button onClick={addCandidate} disabled={!newCand.name || !newCand.cv_text} data-testid="save-candidate-button" className="bg-[#007AFF] rounded-sm">Save</Button>
            </DialogContent>
          </Dialog>
          {pos.candidates.map((c) => (
            <div key={c.id} className="border border-white/15 bg-[#121212] p-5" data-testid={`candidate-row-${c.name.split(" ")[0].toLowerCase()}`}>
              <div className="flex items-center justify-between">
                <span className="font-semibold">{c.name}</span>
                <span className="font-mono text-[10px] text-white/40">{c.source}</span>
              </div>
              <p className="font-mono text-xs text-white/50 mt-2 whitespace-pre-wrap leading-relaxed">{c.cv_text}</p>
            </div>
          ))}
        </TabsContent>

        <TabsContent value="interviews" className="mt-4 space-y-3">
          {!pos.interviews.length && <p className="font-mono text-sm text-white/40 border border-white/15 bg-[#121212] p-6">// no interviews scheduled</p>}
          {pos.interviews.map((iv) => (
            <div key={iv.id} className="border border-white/15 bg-[#121212] p-5">
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-semibold">{iv.candidate_name}</span>
                <span className="font-mono text-xs text-white/40">→ {iv.interviewer_name}</span>
                <span className={`font-mono text-[10px] uppercase border px-2 py-1 ${iv.sla_breached ? "text-[#FF3B30] border-[#FF3B30]/50" : iv.invite_status === "accepted" ? "text-[#32D74B] border-[#32D74B]/40" : "text-white/50 border-white/20"}`}>
                  {iv.sla_breached ? "SLA BREACHED" : iv.invite_status}
                </span>
                {iv.result && <span className={`font-mono text-[10px] uppercase border px-2 py-1 ${iv.result === "pass" ? "text-[#32D74B] border-[#32D74B]/40" : "text-[#FF3B30] border-[#FF3B30]/40"}`}>{iv.result}</span>}
              </div>
              <p className="font-mono text-[11px] text-white/40 mt-2">{iv.match_reason}</p>
              <p className="font-mono text-[11px] text-[#007AFF] mt-1">{iv.meet_link} · transcription enabled</p>
            </div>
          ))}
        </TabsContent>

        <TabsContent value="timeline" className="mt-4">
          <div className="border border-white/15 bg-[#121212] divide-y divide-white/10" data-testid="position-timeline">
            {pos.events.map((e) => (
              <div key={e.id} className="p-4 flex items-center gap-4">
                <span className="font-mono text-[10px] text-white/30 w-40 shrink-0">{new Date(e.created_at).toLocaleString()}</span>
                <span className={`font-mono text-[10px] uppercase w-16 shrink-0 ${e.actor_type === "human" ? "text-[#FFD60A]" : "text-[#007AFF]"}`}>{e.actor_type}</span>
                <span className="font-mono text-xs text-white/80">{e.event_type}</span>
                <span className="font-mono text-[10px] text-white/40 ml-auto">{e.actor_id}</span>
              </div>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="jd" className="mt-4">
          <div className="border border-white/15 bg-[#121212] p-6">
            <p className="font-mono text-xs text-white/70 whitespace-pre-wrap leading-relaxed">{pos.jd_text || "// no JD attached"}</p>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
