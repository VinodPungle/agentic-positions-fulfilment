import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../lib/api";
import { usePersona } from "../context/PersonaContext";
import { StatusBadge } from "../components/StatusBadge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { Checkbox } from "../components/ui/checkbox";
import { toast } from "sonner";
import { ArrowLeft, Sparkles, CalendarPlus, Loader2, UserPlus, Upload, FileText, Pencil, FilePlus2, X } from "lucide-react";

export default function PositionDetail() {
  const { id } = useParams();
  const { user } = usePersona();
  const [pos, setPos] = useState(null);
  const [err, setErr] = useState(null);
  const [evaluating, setEvaluating] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [selected, setSelected] = useState({});
  const [newCand, setNewCand] = useState({ name: "", email: "", cv_text: "" });
  const [showCandidateForm, setShowCandidateForm] = useState(false);
  const [editingCandidateId, setEditingCandidateId] = useState(null);
  const [jdEditOpen, setJdEditOpen] = useState(false);
  const [jdDraft, setJdDraft] = useState("");
  const [jdSkillsDraft, setJdSkillsDraft] = useState("");
  const [jdBusy, setJdBusy] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState(null);
  const bulkInputRef = useRef(null);
  const cvInputRef = useRef(null);
  const [cvParsing, setCvParsing] = useState(false);

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
      <Link to="/" className="font-mono text-xs text-[#007AFF] mt-4 inline-block">← back to dashboard</Link>
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

  const decideFitment = async (iid, decision) => {
    try {
      const r = await api.post(`/interviews/${iid}/fitment`, { decision, comment: "" });
      if (r.data.already_decided) toast.info("Already decided (idempotent)");
      else toast.success(decision === "fit" ? "Marked Internal Fit — ready to share with client" : "Marked Internal Fit Rejected");
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

  const openCreateCandidateForm = () => {
    if (showCandidateForm && !editingCandidateId) { setShowCandidateForm(false); return; }
    setEditingCandidateId(null);
    setNewCand({ name: "", email: "", cv_text: "" });
    setShowCandidateForm(true);
  };

  const startEditCandidate = (c) => {
    setEditingCandidateId(c.id);
    setNewCand({ name: c.name || "", email: c.email || "", cv_text: c.cv_text || "" });
    setShowCandidateForm(true);
  };

  const cancelCandidateForm = () => {
    setShowCandidateForm(false);
    setEditingCandidateId(null);
    setNewCand({ name: "", email: "", cv_text: "" });
  };

  const saveCandidate = async () => {
    try {
      if (editingCandidateId) {
        await api.patch(`/positions/${id}/candidates/${editingCandidateId}`, { name: newCand.name, cv_text: newCand.cv_text });
        toast.success("Candidate updated");
      } else {
        await api.post(`/positions/${id}/candidates`, newCand);
        toast.success("Candidate added");
      }
      cancelCandidateForm();
      load();
    } catch (e) {
      if (!editingCandidateId && e.response?.status === 409) {
        // Already on this position (e.g. brought in by CV bulk upload or the CSV
        // importer) — switch to editing that existing record instead of failing.
        const email = newCand.email.trim().toLowerCase();
        const name = newCand.name.trim().toLowerCase();
        const existing = pos.candidates.find((c) =>
          (email && c.email?.toLowerCase() === email) || (!email && c.name?.toLowerCase() === name));
        if (existing) {
          toast.info(`${existing.name} already exists for this position — editing their record instead`);
          startEditCandidate(existing);
          return;
        }
      }
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const parseCvIntoDialog = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setCvParsing(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api.post("/parse/file", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setNewCand((prev) => ({ ...prev, cv_text: r.data.text }));
      toast.success(`Parsed ${r.data.chars.toLocaleString()} chars from ${f.name}`);
    } catch (err) { toast.error(err.response?.data?.detail || err.message); }
    setCvParsing(false);
    if (cvInputRef.current) cvInputRef.current.value = "";
  };

  const openJdEdit = () => {
    setJdDraft(pos.jd_text || "");
    setJdSkillsDraft((pos.meta?.skills || []).join(", "));
    setJdEditOpen(true);
  };

  const parseJdIntoEditor = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setJdBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api.post("/parse/file", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setJdDraft(r.data.text);
      toast.success(`Parsed ${r.data.chars.toLocaleString()} chars from ${f.name}`);
    } catch (err) { toast.error(err.response?.data?.detail || err.message); }
    setJdBusy(false);
  };

  const saveJd = async () => {
    setJdBusy(true);
    try {
      const skills = jdSkillsDraft.split(",").map((s) => s.trim()).filter(Boolean);
      await api.patch(`/positions/${id}/jd`, { jd_text: jdDraft, skills });
      toast.success("Job description updated");
      setJdEditOpen(false);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    setJdBusy(false);
  };

  const bulkUpload = async (fileList) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    setBulkBusy(true);
    setBulkResult(null);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      const r = await api.post(`/positions/${id}/candidates/bulk`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setBulkResult(r.data);
      if (r.data.count) toast.success(`${r.data.count} candidate(s) added from ${files.length} file(s)`);
      else toast.info("No new candidates created — check errors below");
      load();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    setBulkBusy(false);
    if (bulkInputRef.current) bulkInputRef.current.value = "";
  };

  const ranked = pos.evaluation?.ranked_list?.candidates || [];
  const approvalPending = pos.approval?.status === "pending";
  const approvalApproved = pos.approval?.status === "approved";
  const canApprove = user && (user.role === "pm" || user.role === "service_line_leader" || user.role === "admin");

  return (
    <div className="p-8 space-y-6">
      <Link to="/" className="font-mono text-xs text-white/40 hover:text-white flex items-center gap-2 transition-colors duration-150" data-testid="back-to-pipeline">
        <ArrowLeft size={12} /> DASHBOARD
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
                      {canApprove ? "Select candidates and approve the shortlist to unlock scheduling." : "Only the project PM (or Service Line Leader override) can approve this shortlist."}
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
          <div className="flex flex-wrap gap-2 items-center">
            <Button variant="outline" onClick={openCreateCandidateForm} data-testid="add-candidate-button" className="border-white/20 rounded-sm hover:bg-white/5">
              <UserPlus size={14} className="mr-2" />Add candidate
            </Button>

            <label
              data-testid="bulk-cv-upload-label"
              className={`inline-flex items-center gap-2 border border-[#007AFF]/50 text-[#007AFF] px-4 py-2 cursor-pointer hover:bg-[#007AFF]/10 font-mono text-xs uppercase tracking-[0.15em] rounded-sm ${bulkBusy ? "opacity-60 pointer-events-none" : ""}`}
            >
              {bulkBusy ? <Loader2 size={14} className="animate-spin" /> : <FilePlus2 size={14} />}
              {bulkBusy ? "processing…" : "Bulk upload CVs"}
              <input
                ref={bulkInputRef}
                type="file"
                data-testid="bulk-cv-input"
                accept=".pdf,.docx,.txt"
                multiple
                onChange={(e) => bulkUpload(e.target.files)}
                className="hidden"
              />
            </label>
            <span className="font-mono text-[10px] text-white/40">Drop multiple PDF / DOCX / TXT — LLM extracts name + email per file</span>
          </div>

          {showCandidateForm && (
            <div className="border border-white/15 bg-[#121212] p-6 space-y-4" data-testid="add-candidate-form">
              <div className="flex items-center justify-between">
                <p className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">
                  {editingCandidateId ? `Editing ${newCand.name || "candidate"}` : "New candidate"}
                </p>
                <button onClick={cancelCandidateForm} data-testid="cancel-candidate-button" className="text-white/40 hover:text-white" aria-label="Cancel">
                  <X size={14} />
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Name *</label>
                  <Input placeholder="Name" value={newCand.name} data-testid="candidate-name-input" onChange={(e) => setNewCand({ ...newCand, name: e.target.value })} className="bg-black border-white/20 rounded-sm" />
                </div>
                <div className="space-y-1">
                  <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Email</label>
                  <Input placeholder="Email" value={newCand.email} disabled={!!editingCandidateId} data-testid="candidate-email-input" onChange={(e) => setNewCand({ ...newCand, email: e.target.value })} className="bg-black border-white/20 rounded-sm disabled:opacity-50" />
                </div>
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">CV text *</label>
                  <label className={`inline-flex items-center gap-2 border border-white/20 px-3 py-1.5 cursor-pointer hover:bg-white/5 font-mono text-[10px] uppercase tracking-[0.15em] ${cvParsing ? "opacity-60 pointer-events-none" : ""}`}>
                    {cvParsing ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
                    {cvParsing ? "parsing…" : "upload PDF/DOCX"}
                    <input ref={cvInputRef} type="file" accept=".pdf,.docx,.txt" onChange={parseCvIntoDialog} className="hidden" data-testid="add-cand-file-input" />
                  </label>
                </div>
                <Textarea placeholder="Paste CV text…" rows={8} value={newCand.cv_text} data-testid="candidate-cv-input" onChange={(e) => setNewCand({ ...newCand, cv_text: e.target.value })} className="bg-black border-white/20 rounded-sm font-mono text-xs" />
              </div>
              <div className="flex justify-end gap-2">
                <Button onClick={cancelCandidateForm} variant="outline" className="border-white/20 text-white/70 hover:bg-white/5 rounded-sm">Cancel</Button>
                <Button onClick={saveCandidate} disabled={!newCand.name || !newCand.cv_text} data-testid="save-candidate-button" className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm">
                  {editingCandidateId ? "Save changes" : "Save"}
                </Button>
              </div>
            </div>
          )}

          {bulkResult && (
            <div className="border border-white/15 bg-[#0A0A0A] p-4 space-y-2" data-testid="bulk-cv-result">
              <p className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Bulk upload result</p>
              <p className="font-mono text-xs text-[#32D74B]">✓ {bulkResult.count} candidate(s) added</p>
              {bulkResult.created?.map((c) => (
                <p key={c.id} className="font-mono text-[11px] text-white/60">— {c.name} {c.email ? `<${c.email}>` : ""} <span className="text-white/30">({c.filename})</span></p>
              ))}
              {(bulkResult.errors || []).map((e, i) => (
                <p key={i} className="font-mono text-[11px] text-[#FF3B30]">✗ {e}</p>
              ))}
            </div>
          )}

          {pos.candidates.map((c) => (
            <div key={c.id} className="border border-white/15 bg-[#121212] p-5" data-testid={`candidate-row-${c.name.split(" ")[0].toLowerCase()}`}>
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-semibold">{c.name}</span>
                  {c.email && <span className="font-mono text-[11px] text-white/40 ml-3">{c.email}</span>}
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-mono text-[10px] text-white/40">{c.source}</span>
                  <button onClick={() => startEditCandidate(c)} data-testid={`edit-candidate-${c.id}`}
                    className="text-white/30 hover:text-[#007AFF]" aria-label={`Edit ${c.name}`}>
                    <Pencil size={12} />
                  </button>
                </div>
              </div>
              <p className="font-mono text-xs text-white/50 mt-2 whitespace-pre-wrap leading-relaxed">{c.cv_text}</p>
            </div>
          ))}
        </TabsContent>

        <TabsContent value="interviews" className="mt-4 space-y-3">
          {!pos.interviews.length && <p className="font-mono text-sm text-white/40 border border-white/15 bg-[#121212] p-6">// no interviews scheduled</p>}
          {pos.interviews.map((iv) => (
            <div key={iv.id} className="border border-white/15 bg-[#121212] p-5" data-testid={`interview-row-${iv.id}`}>
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-semibold">{iv.candidate_name}</span>
                <span className="font-mono text-xs text-white/40">→ {iv.interviewer_name}</span>
                <span className={`font-mono text-[10px] uppercase border px-2 py-1 ${iv.sla_breached ? "text-[#FF3B30] border-[#FF3B30]/50" : iv.invite_status === "accepted" ? "text-[#32D74B] border-[#32D74B]/40" : "text-white/50 border-white/20"}`}>
                  {iv.sla_breached ? "SLA BREACHED" : iv.invite_status}
                </span>
                {iv.result && <span className={`font-mono text-[10px] uppercase border px-2 py-1 ${iv.result === "pass" ? "text-[#32D74B] border-[#32D74B]/40" : "text-[#FF3B30] border-[#FF3B30]/40"}`}>interviewer: {iv.result}</span>}
                {iv.fitment_decision && (
                  <span className={`font-mono text-[10px] uppercase border px-2 py-1 ${iv.fitment_decision === "fit" ? "text-[#32D74B] border-[#32D74B]/60" : "text-[#FF3B30] border-[#FF3B30]/60"}`}>
                    {iv.fitment_decision === "fit" ? "Internal Fit" : "Internal Fit Rejected"}
                  </span>
                )}
              </div>
              <p className="font-mono text-[11px] text-white/40 mt-2">{iv.match_reason}</p>
              <p className="font-mono text-[11px] text-[#007AFF] mt-1">{iv.meet_link} · transcription enabled</p>

              {iv.transcript_summary && (
                <div className="mt-3 border border-white/10 bg-black/40 p-3" data-testid={`transcript-summary-${iv.id}`}>
                  <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase mb-2">Monitoring Agent · transcript summary</p>
                  <p className="text-xs text-white/70 whitespace-pre-wrap leading-relaxed">{iv.transcript_summary}</p>
                </div>
              )}

              {iv.feedback && !iv.fitment_decision && canApprove && (
                <div className="mt-3 border border-[#FFD60A]/40 bg-[#FFD60A]/5 p-4 flex flex-wrap items-center justify-between gap-3" data-testid={`fitment-gate-${iv.id}`}>
                  <p className="text-xs text-white/70">Feedback and transcript summary are in — decide if {iv.candidate_name} can be shared with the client.</p>
                  <div className="flex gap-2 shrink-0">
                    <Button onClick={() => decideFitment(iv.id, "fit")} data-testid={`mark-fit-${iv.id}`} className="bg-[#32D74B] hover:bg-[#28B33E] text-black rounded-sm h-8">Mark Internal Fit</Button>
                    <Button onClick={() => decideFitment(iv.id, "reject")} data-testid={`mark-reject-${iv.id}`} variant="outline" className="border-[#FF3B30]/50 text-[#FF3B30] hover:bg-[#FF3B30]/10 rounded-sm h-8">Reject</Button>
                  </div>
                </div>
              )}
              {iv.fitment_decision && (
                <p className="font-mono text-[11px] text-white/50 mt-3 border-t border-white/10 pt-3">
                  FITMENT: {iv.fitment_decision.toUpperCase()} by {iv.fitment_decided_by}{iv.fitment_comment ? ` — "${iv.fitment_comment}"` : ""}
                </p>
              )}
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
          <div className="border border-white/15 bg-[#121212] p-6 space-y-3">
            <div className="flex items-center justify-between">
              <p className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Job description</p>
              <Button
                variant="outline"
                onClick={openJdEdit}
                data-testid="edit-jd-button"
                className="border-white/20 hover:bg-white/5 rounded-sm h-8"
              >
                <Pencil size={12} className="mr-2" />
                {pos.jd_text ? "Edit JD" : "Add JD"}
              </Button>
            </div>
            <p className="font-mono text-xs text-white/70 whitespace-pre-wrap leading-relaxed">
              {pos.jd_text || "// no JD attached — click Add JD to paste or upload"}
            </p>
          </div>

          <Dialog open={jdEditOpen} onOpenChange={setJdEditOpen}>
            <DialogContent className="bg-[#0D0D0D] border-white/20 text-white max-w-2xl max-h-[90vh] overflow-y-auto" data-testid="edit-jd-dialog">
              <DialogHeader>
                <DialogTitle className="font-heading font-black text-2xl tracking-tight">Edit job description</DialogTitle>
              </DialogHeader>
              <div className="flex items-center justify-between gap-3 mt-2">
                <div className="flex items-center gap-2">
                  <FileText size={14} className="text-[#007AFF]" />
                  <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/60">Paste or upload</span>
                </div>
                <label className={`inline-flex items-center gap-2 border border-white/20 px-3 py-1.5 cursor-pointer hover:bg-white/5 font-mono text-[10px] uppercase tracking-[0.15em] ${jdBusy ? "opacity-60 pointer-events-none" : ""}`}>
                  {jdBusy ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
                  {jdBusy ? "parsing…" : "upload PDF / DOCX"}
                  <input type="file" accept=".pdf,.docx,.txt,.md" onChange={parseJdIntoEditor} className="hidden" data-testid="edit-jd-file-input" />
                </label>
              </div>
              <Textarea
                data-testid="edit-jd-textarea"
                rows={14}
                value={jdDraft}
                onChange={(e) => setJdDraft(e.target.value)}
                placeholder="Paste JD text…"
                className="bg-black border-white/20 rounded-sm font-mono text-xs leading-relaxed mt-3"
              />
              <div className="mt-3 space-y-1">
                <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Skills (comma-separated)</label>
                <Input
                  data-testid="edit-jd-skills-input"
                  value={jdSkillsDraft}
                  onChange={(e) => setJdSkillsDraft(e.target.value)}
                  placeholder="Python, FastAPI, PostgreSQL"
                  className="bg-black border-white/20 rounded-sm font-mono text-xs"
                />
              </div>
              <div className="flex justify-end gap-2 mt-4">
                <Button variant="outline" onClick={() => setJdEditOpen(false)} className="border-white/20 rounded-sm hover:bg-white/5">Cancel</Button>
                <Button onClick={saveJd} disabled={jdBusy} data-testid="save-jd-button" className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm">
                  {jdBusy ? <Loader2 size={14} className="animate-spin mr-2" /> : null}
                  Save JD
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </TabsContent>
      </Tabs>
    </div>
  );
}
