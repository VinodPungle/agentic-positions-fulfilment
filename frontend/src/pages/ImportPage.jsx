import { useState } from "react";
import { api } from "../lib/api";
import { Button } from "../components/ui/button";
import { toast } from "sonner";
import { Upload, FileSpreadsheet } from "lucide-react";

const ImportCard = ({ title, endpoint, columns, testId }) => {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.post(endpoint, fd, { headers: { "Content-Type": "multipart/form-data" } });
      setResult(r.data);
      toast.success(`${r.data.created} created, ${r.data.updated} updated (re-import is idempotent)`);
    } catch (e) { toast.error(e.response?.data?.detail || e.message); }
    setBusy(false);
  };

  return (
    <div className="border border-white/15 bg-[#121212] p-6 space-y-4">
      <div className="flex items-center gap-3">
        <FileSpreadsheet size={18} className="text-[#007AFF]" />
        <h3 className="font-heading font-bold text-xl tracking-tight">{title}</h3>
      </div>
      <p className="font-mono text-[11px] text-white/40 leading-relaxed">Expected CSV columns: {columns}</p>
      <input type="file" accept=".csv" data-testid={`${testId}-file-input`} onChange={(e) => setFile(e.target.files[0])}
        className="block w-full font-mono text-xs text-white/60 file:mr-4 file:border file:border-white/20 file:bg-black file:text-white file:px-4 file:py-2 file:font-mono file:text-xs file:cursor-pointer file:rounded-none" />
      <Button onClick={upload} disabled={!file || busy} data-testid={`${testId}-upload-button`} className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm">
        <Upload size={14} className="mr-2" /> {busy ? "Importing…" : "Import (upsert)"}
      </Button>
      {result && (
        <div className="border border-white/10 bg-black p-4 font-mono text-xs space-y-1" data-testid={`${testId}-result`}>
          <p className="text-[#32D74B]">created: {result.created} · updated: {result.updated}</p>
          {result.errors.map((e, i) => <p key={i} className="text-[#FF3B30]">{e}</p>)}
        </div>
      )}
    </div>
  );
};

export default function ImportPage() {
  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="font-heading font-black text-4xl sm:text-5xl tracking-tight leading-none">Sheets Migration</h1>
        <p className="font-mono text-xs text-white/40 mt-2 tracking-[0.15em]">EXPORT YOUR GOOGLE SHEETS AS CSV · UPSERTS BY NATURAL KEY · SAFE TO RE-RUN</p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ImportCard title="Open Positions tracker" endpoint="/import/positions" testId="import-positions"
          columns="ticket_number, title, project, priority, status, skills (semicolon-separated), jd_text" />
        <ImportCard title="Interviewer panel roster" endpoint="/import/interviewers" testId="import-interviewers"
          columns="name, email, role, skills (semicolon-separated), seniority" />
      </div>
      <div className="border border-white/15 bg-[#121212] p-6">
        <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase mb-3">Migration protocol</p>
        <ol className="text-sm text-white/70 space-y-2 list-decimal list-inside leading-relaxed">
          <li>Export each Google Sheet tab as CSV (File → Download → CSV).</li>
          <li>Upload here — rows are upserted by ticket_number / email, so re-syncing daily during dual-run is safe.</li>
          <li>Keep working in Sheets during transition; this database is the system of record for new positions.</li>
          <li>After cutover, freeze the Sheet read-only.</li>
        </ol>
      </div>
    </div>
  );
}
