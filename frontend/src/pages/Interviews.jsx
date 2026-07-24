import { useEffect, useState, useCallback } from "react";
import { api } from "../lib/api";
import { usePersona } from "../context/PersonaContext";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../components/ui/dialog";
import { toast } from "sonner";
import { RadioTower, Check, X, Loader2 } from "lucide-react";

export default function Interviews() {
  const { user } = usePersona();
  const [interviews, setInterviews] = useState([]);
  const [fbFor, setFbFor] = useState(null);
  const [fb, setFb] = useState({ result: "pass", comments: "" });
  const [submitting, setSubmitting] = useState(false);
  const [sweeping, setSweeping] = useState(false);

  const load = useCallback(() => { api.get("/interviews").then((r) => setInterviews(r.data)); }, []);
  useEffect(() => { load(); }, [load, user?.id]);

  const respond = async (iv, action) => {
    const r = await api.post(`/interviews/${iv.id}/respond`, { action });
    toast[r.data.already_responded ? "info" : "success"](r.data.already_responded ? "Already responded (idempotent)" : `Invite ${r.data.invite_status}`);
    load();
  };

  const sweep = async () => {
    setSweeping(true);
    try {
      const r = await api.post("/monitoring/sweep");
      toast.success(`SLA sweep: ${r.data.reminders_sent.length} reminder(s) sent, ${r.data.checked} checked`);
      load();
    } catch (e) { toast.error(e.message); }
    setSweeping(false);
  };

  const submitFeedback = async () => {
    setSubmitting(true);
    try {
      const r = await api.post(`/interviews/${fbFor.id}/feedback`, fb);
      toast[r.data.already_submitted ? "info" : "success"](r.data.already_submitted ? "Feedback already submitted (idempotent)" : "Feedback + transcript summary distributed");
      setFbFor(null);
      setFb({ result: "pass", comments: "" });
      load();
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    setSubmitting(false);
  };

  return (
    <div className="p-8 space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-heading font-black text-4xl sm:text-5xl tracking-tight leading-none">Interviews</h1>
          <p className="font-mono text-xs text-white/40 mt-2 tracking-[0.15em]">MONITORING AGENT · INVITE SLA 1H · {interviews.length} IN SCOPE</p>
        </div>
        <Button onClick={sweep} disabled={sweeping} data-testid="sla-sweep-button" variant="outline" className="border-[#FF9F0A]/50 text-[#FF9F0A] hover:bg-[#FF9F0A]/10 rounded-sm">
          {sweeping ? <Loader2 size={14} className="animate-spin mr-2" /> : <RadioTower size={14} className="mr-2" />}
          Run SLA sweep
        </Button>
      </div>

      <div className="space-y-3">
        {!interviews.length && <p className="font-mono text-sm text-white/40 border border-white/15 bg-[#121212] p-6">// no interviews in your scope</p>}
        {interviews.map((iv) => (
          <div key={iv.id} className="border border-white/15 bg-[#121212] p-5" data-testid={`interview-card-${iv.ticket_number}`}>
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-xs text-[#007AFF]">{iv.ticket_number}</span>
              <span className="font-semibold">{iv.candidate_name}</span>
              <span className="font-mono text-xs text-white/40">→ {iv.interviewer_name}</span>
              <span className={`font-mono text-[10px] uppercase border px-2 py-1 ${iv.sla_breached ? "text-[#FF3B30] border-[#FF3B30]/50 animate-pulse" : iv.invite_status === "accepted" ? "text-[#32D74B] border-[#32D74B]/40" : iv.invite_status === "declined" ? "text-[#FF3B30] border-[#FF3B30]/40" : "text-white/50 border-white/20"}`}>
                {iv.sla_breached ? "SLA BREACHED" : iv.invite_status}
              </span>
              {iv.result && <span className={`font-mono text-[10px] uppercase border px-2 py-1 ${iv.result === "pass" ? "text-[#32D74B] border-[#32D74B]/40" : "text-[#FF3B30] border-[#FF3B30]/40"}`}>RESULT: {iv.result}</span>}
              <div className="ml-auto flex gap-2">
                {iv.invite_status === "pending" && (
                  <>
                    <Button size="sm" onClick={() => respond(iv, "accept")} data-testid={`accept-invite-${iv.ticket_number}`} className="bg-[#32D74B]/15 text-[#32D74B] hover:bg-[#32D74B]/25 rounded-sm border border-[#32D74B]/40">
                      <Check size={13} className="mr-1" /> Simulate accept
                    </Button>
                    <Button size="sm" onClick={() => respond(iv, "decline")} data-testid={`decline-invite-${iv.ticket_number}`} className="bg-[#FF3B30]/15 text-[#FF3B30] hover:bg-[#FF3B30]/25 rounded-sm border border-[#FF3B30]/40">
                      <X size={13} className="mr-1" /> Decline
                    </Button>
                  </>
                )}
                {iv.invite_status === "accepted" && !iv.feedback && (
                  <Button size="sm" onClick={() => setFbFor(iv)} data-testid={`submit-feedback-${iv.ticket_number}`} className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm">Submit feedback</Button>
                )}
              </div>
            </div>
            <p className="font-mono text-[11px] text-white/40 mt-2">{iv.match_reason}</p>
            <p className="font-mono text-[11px] text-[#007AFF] mt-1">{iv.meet_link} · transcription enabled · feedback form linked</p>
            {iv.feedback && (
              <div className="mt-3 border border-white/10 bg-black p-4">
                <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase">Feedback packet</p>
                <p className="text-sm text-white/80 mt-1">{iv.feedback.comments}</p>
                {iv.transcript_summary && (
                  <>
                    <p className="font-mono text-[10px] tracking-[0.2em] text-[#007AFF] uppercase mt-3">AI transcript summary</p>
                    <p className="text-sm text-[#7cb8ff] whitespace-pre-wrap mt-1 leading-relaxed">{iv.transcript_summary}</p>
                  </>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <Dialog open={!!fbFor} onOpenChange={(o) => !o && setFbFor(null)}>
        <DialogContent className="bg-[#121212] border-white/20 text-white">
          <DialogHeader><DialogTitle className="font-heading">Interview feedback — {fbFor?.candidate_name}</DialogTitle></DialogHeader>
          <div className="flex gap-2">
            {["pass", "fail"].map((r) => (
              <button key={r} onClick={() => setFb({ ...fb, result: r })} data-testid={`feedback-result-${r}`}
                className={`flex-1 font-mono text-xs uppercase tracking-[0.15em] border px-4 py-3 transition-colors duration-150 ${fb.result === r ? (r === "pass" ? "border-[#32D74B] text-[#32D74B] bg-[#32D74B]/10" : "border-[#FF3B30] text-[#FF3B30] bg-[#FF3B30]/10") : "border-white/20 text-white/50"}`}>
                {r}
              </button>
            ))}
          </div>
          <Textarea rows={5} placeholder="Comments…" value={fb.comments} data-testid="feedback-comments-input"
            onChange={(e) => setFb({ ...fb, comments: e.target.value })} className="bg-black border-white/20 rounded-sm" />
          <Button onClick={submitFeedback} disabled={submitting} data-testid="feedback-submit-button" className="bg-[#007AFF] rounded-sm">
            {submitting ? <Loader2 size={14} className="animate-spin mr-2" /> : null}
            {submitting ? "Summarizing transcript…" : "Submit — triggers AI transcript summary"}
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
