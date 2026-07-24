import { useEffect, useState, useCallback } from "react";
import { api } from "../lib/api";
import { usePersona } from "../context/PersonaContext";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import { Hash, Mail } from "lucide-react";

export default function Comms() {
  const { user } = usePersona();
  const [slack, setSlack] = useState([]);
  const [email, setEmail] = useState([]);

  const load = useCallback(() => {
    api.get("/comms", { params: { channel: "slack" } }).then((r) => setSlack(r.data));
    api.get("/comms", { params: { channel: "email" } }).then((r) => setEmail(r.data));
  }, []);
  useEffect(() => { load(); }, [load, user?.id]);

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="font-heading font-black text-4xl sm:text-5xl tracking-tight leading-none">Comms</h1>
        <p className="font-mono text-xs text-white/40 mt-2 tracking-[0.15em]">NOTIFICATION AGENT OUTBOX · MOCK SLACK + MOCK EMAIL · IDEMPOTENT DELIVERY</p>
      </div>
      <Tabs defaultValue="slack">
        <TabsList className="bg-[#121212] border border-white/15 rounded-none h-auto p-0">
          <TabsTrigger value="slack" data-testid="tab-slack" className="rounded-none font-mono text-xs tracking-[0.15em] uppercase px-5 py-3 data-[state=active]:bg-[#007AFF]/10 data-[state=active]:text-[#007AFF] data-[state=active]:shadow-none">
            <Hash size={13} className="mr-2" /> Slack feed ({slack.length})
          </TabsTrigger>
          <TabsTrigger value="email" data-testid="tab-email" className="rounded-none font-mono text-xs tracking-[0.15em] uppercase px-5 py-3 data-[state=active]:bg-[#007AFF]/10 data-[state=active]:text-[#007AFF] data-[state=active]:shadow-none">
            <Mail size={13} className="mr-2" /> Email inbox ({email.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="slack" className="mt-4">
          <div className="border border-white/15 bg-[#121212] divide-y divide-white/10" data-testid="slack-feed">
            {slack.map((m) => (
              <div key={m.id} className="p-4 flex gap-4">
                <div className="w-9 h-9 shrink-0 bg-[#007AFF]/15 border border-[#007AFF]/40 flex items-center justify-center font-mono text-[10px] text-[#007AFF]">A2A</div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-semibold text-sm">Notification Agent</span>
                    <span className="font-mono text-[10px] text-[#32D74B]">{m.recipient}</span>
                    <span className="font-mono text-[10px] text-white/30">{new Date(m.created_at).toLocaleString()}</span>
                  </div>
                  <p className="text-sm text-white/80 mt-1 leading-relaxed whitespace-pre-wrap">{m.body}</p>
                  <p className="font-mono text-[9px] text-white/25 mt-1 break-all">idempotency: {m.idempotency_key}</p>
                </div>
              </div>
            ))}
            {!slack.length && <p className="font-mono text-sm text-white/40 p-6">// no slack messages yet</p>}
          </div>
        </TabsContent>

        <TabsContent value="email" className="mt-4">
          <div className="border border-white/15 bg-[#121212] divide-y divide-white/10" data-testid="email-inbox">
            {email.map((m) => (
              <div key={m.id} className="p-4">
                <div className="flex flex-wrap items-baseline gap-3">
                  <span className="font-semibold text-sm">{m.subject}</span>
                  <span className="font-mono text-[10px] text-white/40">to: {m.recipient}</span>
                  <span className="font-mono text-[10px] text-white/30 ml-auto">{new Date(m.created_at).toLocaleString()}</span>
                </div>
                <p className="text-sm text-white/70 mt-2 whitespace-pre-wrap leading-relaxed">{m.body}</p>
              </div>
            ))}
            {!email.length && <p className="font-mono text-sm text-white/40 p-6">// inbox empty</p>}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
