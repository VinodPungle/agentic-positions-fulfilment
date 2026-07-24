import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogDescription } from "./ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { toast } from "sonner";
import { Plus, Loader2, Upload, FileText } from "lucide-react";

const PRIORITIES = ["low", "medium", "high"];

export default function NewPositionDialog({ onCreated, trigger }) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState([]);
  const [form, setForm] = useState({
    ticket_number: "",
    title: "",
    project_id: "",
    priority: "medium",
    skills: "",
    jd_text: "",
  });
  const [parsing, setParsing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [jdFilename, setJdFilename] = useState("");

  useEffect(() => {
    if (open) {
      api.get("/projects").then((r) => {
        setProjects(r.data);
        if (r.data.length && !form.project_id) setForm((f) => ({ ...f, project_id: r.data[0].id }));
      }).catch(() => {});
    }
  }, [open]);

  const onJdFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setJdFilename(f.name);
    setParsing(true);
    try {
      const fd = new FormData();
      fd.append("file", f);
      const r = await api.post("/parse/file", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setForm((prev) => ({ ...prev, jd_text: r.data.text }));
      toast.success(`Parsed ${r.data.chars.toLocaleString()} chars from ${f.name}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message);
    }
    setParsing(false);
  };

  const submit = async () => {
    if (!form.ticket_number || !form.title || !form.project_id) {
      return toast.error("Ticket number, title and project are required");
    }
    setSaving(true);
    try {
      const skills = form.skills.split(",").map((s) => s.trim()).filter(Boolean);
      const r = await api.post("/positions", {
        ticket_number: form.ticket_number.trim(),
        title: form.title.trim(),
        project_id: form.project_id,
        priority: form.priority,
        skills,
        jd_text: form.jd_text,
      });
      toast.success(`Position ${r.data.ticket_number} created`);
      setOpen(false);
      setForm({ ticket_number: "", title: "", project_id: projects[0]?.id || "", priority: "medium", skills: "", jd_text: "" });
      setJdFilename("");
      if (onCreated) onCreated(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
    setSaving(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button data-testid="new-position-button" className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm">
            <Plus size={14} className="mr-2" /> New Position
          </Button>
        )}
      </DialogTrigger>
      <DialogContent
        data-testid="new-position-dialog"
        className="bg-[#0D0D0D] border-white/20 text-white max-w-2xl max-h-[90vh] overflow-y-auto"
      >
        <DialogHeader>
          <DialogTitle className="font-heading font-black text-2xl tracking-tight">Open a new position</DialogTitle>
          <DialogDescription className="font-mono text-[11px] tracking-[0.15em] uppercase text-white/40">
            Ticket · JD · Skills · assigned to a project
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-2">
          <div className="space-y-1">
            <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Ticket number *</label>
            <Input
              data-testid="np-ticket-input"
              value={form.ticket_number}
              onChange={(e) => setForm({ ...form, ticket_number: e.target.value })}
              placeholder="POS-107"
              className="bg-black border-white/20 rounded-sm font-mono"
            />
          </div>
          <div className="space-y-1">
            <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Priority</label>
            <Select value={form.priority} onValueChange={(v) => setForm({ ...form, priority: v })}>
              <SelectTrigger data-testid="np-priority-select" className="bg-black border-white/20 rounded-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#0D0D0D] border-white/20 text-white">
                {PRIORITIES.map((p) => (
                  <SelectItem key={p} value={p} className="font-mono text-xs uppercase">{p}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="space-y-1 mt-3">
          <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Title *</label>
          <Input
            data-testid="np-title-input"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Senior ML Engineer"
            className="bg-black border-white/20 rounded-sm"
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
          <div className="space-y-1">
            <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Project *</label>
            <Select value={form.project_id} onValueChange={(v) => setForm({ ...form, project_id: v })}>
              <SelectTrigger data-testid="np-project-select" className="bg-black border-white/20 rounded-sm">
                <SelectValue placeholder="Select project" />
              </SelectTrigger>
              <SelectContent className="bg-[#0D0D0D] border-white/20 text-white">
                {projects.map((p) => (
                  <SelectItem key={p.id} value={p.id}>{p.name}{p.client ? ` — ${p.client}` : ""}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/50">Skills (comma-separated)</label>
            <Input
              data-testid="np-skills-input"
              value={form.skills}
              onChange={(e) => setForm({ ...form, skills: e.target.value })}
              placeholder="Python, FastAPI, PostgreSQL"
              className="bg-black border-white/20 rounded-sm font-mono text-xs"
            />
          </div>
        </div>

        <div className="mt-4 border border-white/10 bg-[#080808] p-4 space-y-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <FileText size={14} className="text-[#007AFF]" />
              <span className="font-mono text-[10px] tracking-[0.2em] uppercase text-white/60">Job description</span>
            </div>
            <label
              data-testid="np-jd-file-label"
              className={`inline-flex items-center gap-2 border border-white/20 px-3 py-1.5 cursor-pointer hover:bg-white/5 font-mono text-[10px] uppercase tracking-[0.15em] ${parsing ? "opacity-60 pointer-events-none" : ""}`}
            >
              {parsing ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
              {parsing ? "parsing…" : "upload PDF / DOCX / TXT"}
              <input
                type="file"
                data-testid="np-jd-file-input"
                accept=".pdf,.docx,.txt,.md"
                onChange={onJdFile}
                className="hidden"
              />
            </label>
          </div>
          {jdFilename && !parsing && (
            <p className="font-mono text-[10px] text-[#32D74B]">parsed: {jdFilename}</p>
          )}
          <Textarea
            data-testid="np-jd-textarea"
            rows={8}
            value={form.jd_text}
            onChange={(e) => setForm({ ...form, jd_text: e.target.value })}
            placeholder="Paste the JD here — or upload a file above and edit if needed."
            className="bg-black border-white/20 rounded-sm font-mono text-xs leading-relaxed"
          />
          <p className="font-mono text-[10px] text-white/30">
            {form.jd_text.length.toLocaleString()} chars · used by the Evaluation Agent to rank CVs
          </p>
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <Button
            variant="outline"
            onClick={() => setOpen(false)}
            className="border-white/20 text-white/70 hover:bg-white/5 rounded-sm"
          >
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={saving || !form.ticket_number || !form.title || !form.project_id}
            data-testid="np-submit-button"
            className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm"
          >
            {saving ? <Loader2 size={14} className="animate-spin mr-2" /> : <Plus size={14} className="mr-2" />}
            {saving ? "Creating…" : "Create position"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
