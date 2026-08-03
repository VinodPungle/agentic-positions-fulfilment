import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { toast } from "sonner";
import { Plus, Loader2, Calendar, Pencil, X } from "lucide-react";

const initials = (name) => name.trim().split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();

const EMPTY_FORM = { name: "", email: "", role: "", skills: "", availability: "" };
const toForm = (i) => ({
  name: i.name || "", email: i.email || "", role: i.role || "",
  skills: (i.skills || []).join(", "), availability: (i.availability || []).join("\n"),
});

export default function InterviewPanel() {
  const [interviewers, setInterviewers] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState(null);

  const load = () => api.get("/interviewers").then((r) => setInterviewers(r.data));
  useEffect(() => { load(); }, []);

  const openCreateForm = () => {
    if (showForm && !editingId) { setShowForm(false); return; }
    setEditingId(null);
    setForm(EMPTY_FORM);
    setShowForm(true);
  };

  const startEdit = (ivr) => {
    setEditingId(ivr.id);
    setForm(toForm(ivr));
    setShowForm(true);
  };

  const cancelForm = () => {
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
  };

  const submit = async () => {
    if (!form.name.trim() || !form.email.trim()) return toast.error("Name and email are required");
    setSaving(true);
    try {
      const skills = form.skills.split(",").map((s) => s.trim()).filter(Boolean);
      const availability = form.availability.split("\n").map((s) => s.trim()).filter(Boolean);
      if (editingId) {
        const r = await api.patch(`/interviewers/${editingId}`, { name: form.name.trim(), role: form.role.trim(), skills, availability });
        toast.success(`${r.data.name} updated`);
        cancelForm();
        load();
      } else {
        const r = await api.post("/interviewers", { name: form.name.trim(), email: form.email.trim(), role: form.role.trim(), skills, availability });
        toast.success(`${r.data.name} added to the panel`);
        cancelForm();
        load();
      }
    } catch (e) {
      if (!editingId && e.response?.status === 409) {
        // Already on the roster (e.g. brought in by the CSV importer) — switch to
        // editing that existing record instead of just failing the add.
        const existing = interviewers.find((i) => i.email.toLowerCase() === form.email.trim().toLowerCase());
        if (existing) {
          toast.info(`${existing.name} already exists — editing their record instead`);
          startEdit(existing);
          setSaving(false);
          return;
        }
      }
      toast.error(e.response?.data?.detail || e.message);
    }
    setSaving(false);
  };

  return (
    <div className="p-8 space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs text-muted-foreground tracking-[0.15em]">PANEL</p>
          <h1 className="font-heading font-black text-4xl sm:text-5xl tracking-tight leading-none">Interview Panel</h1>
        </div>
        <Button onClick={openCreateForm} data-testid="add-interviewer-toggle" className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm">
          <Plus size={14} className="mr-2" /> Add Interviewer
        </Button>
      </div>

      {showForm && (
        <div className="border border-white/15 bg-[#121212] p-6 space-y-4" data-testid="add-interviewer-form">
          <div className="flex items-center justify-between">
            <p className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">
              {editingId ? `Editing ${form.name || "interviewer"}` : "New interviewer"}
            </p>
            <button onClick={cancelForm} data-testid="ip-cancel-button" className="text-white/40 hover:text-white" aria-label="Cancel">
              <X size={14} />
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Name *</label>
              <Input data-testid="ip-name-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Name" className="bg-black border-white/20 rounded-sm" />
            </div>
            <div className="space-y-1">
              <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Email {editingId ? "" : "*"}</label>
              <Input data-testid="ip-email-input" value={form.email} disabled={!!editingId}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="Email" className="bg-black border-white/20 rounded-sm disabled:opacity-50" />
            </div>
            <div className="space-y-1">
              <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Role</label>
              <Input data-testid="ip-role-input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}
                placeholder="e.g. Tech Architect" className="bg-black border-white/20 rounded-sm" />
            </div>
            <div className="space-y-1">
              <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Skills (comma)</label>
              <Input data-testid="ip-skills-input" value={form.skills} onChange={(e) => setForm({ ...form, skills: e.target.value })}
                placeholder="Python, PyTorch, LLM" className="bg-black border-white/20 rounded-sm font-mono text-xs" />
            </div>
          </div>
          <div className="space-y-1">
            <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Availability slots, one per line</label>
            <Textarea data-testid="ip-availability-textarea" rows={4} value={form.availability}
              onChange={(e) => setForm({ ...form, availability: e.target.value })}
              placeholder="e.g. 2026-02-20T10:00:00Z" className="bg-black border-white/20 rounded-sm font-mono text-xs leading-relaxed" />
          </div>
          <div className="flex justify-end gap-2">
            <Button onClick={cancelForm} variant="outline" className="border-white/20 text-white/70 hover:bg-white/5 rounded-sm">Cancel</Button>
            <Button onClick={submit} disabled={saving} data-testid="ip-submit-button" className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm">
              {saving ? <Loader2 size={14} className="animate-spin mr-2" /> : <Plus size={14} className="mr-2" />}
              {saving ? (editingId ? "Saving…" : "Adding…") : (editingId ? "Save changes" : "Add")}
            </Button>
          </div>
        </div>
      )}

      {!interviewers.length && (
        <p className="font-mono text-sm text-white/40 border border-white/15 bg-[#121212] p-6" data-testid="no-interviewers">
          // no interviewers on the panel yet
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {interviewers.map((i) => (
          <div key={i.id} className="border border-white/15 bg-[#121212] p-5" data-testid={`interviewer-card-${i.id}`}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-3 min-w-0">
                <div className="w-9 h-9 rounded-full bg-[#007AFF]/15 border border-[#007AFF]/40 flex items-center justify-center font-mono text-xs text-[#007AFF] shrink-0">
                  {initials(i.name)}
                </div>
                <div className="min-w-0">
                  <p className="font-semibold text-sm truncate">{i.name}</p>
                  <p className="font-mono text-[11px] text-white/40 truncate">{i.email}</p>
                </div>
              </div>
              <button onClick={() => startEdit(i)} data-testid={`edit-interviewer-${i.id}`}
                className="text-white/30 hover:text-[#007AFF] shrink-0" aria-label={`Edit ${i.name}`}>
                <Pencil size={13} />
              </button>
            </div>
            {i.role && <p className="text-sm text-white/70 mt-3">{i.role}</p>}
            {!!i.skills?.length && (
              <div className="flex flex-wrap gap-2 mt-2">
                {i.skills.map((s) => <span key={s} className="font-mono text-[10px] border border-white/20 text-white/70 px-2 py-1">{s}</span>)}
              </div>
            )}
            <div className="border-t border-white/10 mt-4 pt-3">
              <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase flex items-center gap-1.5">
                <Calendar size={11} /> Availability
              </p>
              {i.availability?.length ? (
                <div className="mt-2 space-y-1">
                  {i.availability.map((a) => (
                    <p key={a} className="font-mono text-xs text-[#32D74B]">{new Date(a).toLocaleString()}</p>
                  ))}
                </div>
              ) : (
                <p className="font-mono text-xs text-white/30 mt-2">no slots shared yet</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
