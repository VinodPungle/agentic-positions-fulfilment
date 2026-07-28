import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { AgentChatPanel } from "../components/AgentChatPanel";
import { Brain, CalendarClock, RadioTower, BarChart3, Send, Network } from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "../components/ui/tooltip";

const ICONS = { orchestrator: Network, evaluation: Brain, scheduling: CalendarClock, monitoring: RadioTower, reporting: BarChart3, notifier: Send };
const SUGGESTIONS = {
  orchestrator: ["What's the status of SR-102?", "How many open positions do we have?", "Which positions are blocked on approval?"],
  evaluation: ["Why was the #1 candidate ranked highest?", "Summarize the latest evaluation"],
  scheduling: ["Who can interview a Node.js tech lead?", "What's the current interviewer load?"],
  monitoring: ["Any SLA breaches right now?", "Which interviews are awaiting feedback?"],
  reporting: ["Give me a fulfillment report for my scope", "How many positions are filled vs open?"],
  notifier: ["What notifications went out today?", "Explain how you avoid duplicate sends"],
};

// Sourced from the "A2A, explained" section of the account-staffing briefing document —
// keep these in sync if that section's per-agent copy changes.
const A2A_INFO = {
  orchestrator: {
    role: "The conductor. Owns every position's current status and the PM-approval gate. Also the one you talk to directly — ask it “what's the status of a ticket” or “how many open roles do we have” and it answers from live data, scoped to what you're allowed to see.",
    removes: "Asking around / checking three sheets to find out where a role stands.",
  },
  evaluation: {
    role: "Reads the JD and every candidate CV, ranks the full pool, and writes out its reasoning per candidate — strengths, gaps, why it ranked them where it did. Re-running on an unchanged JD/CV set reuses the prior result instead of re-spending the work.",
    removes: "Manually reading every CV for a first-pass shortlist.",
  },
  scheduling: {
    role: "Matches each approved candidate to the best-available interviewer by skill overlap and current interview load — not just “who's free,” but “who's the right fit and isn't already overloaded” — and sends the invite.",
    removes: "Manually cross-checking interviewer skills and availability.",
  },
  monitoring: {
    role: "Watches every open invite against its SLA and nudges the interviewer automatically if it's breached — no one has to remember to chase. Once feedback lands, it summarizes the interview transcript and routes it straight to the interviewer and the project's PM — the exact input the PM needs to decide Internal Fit or not.",
    removes: "Manually tracking who hasn't responded and chasing them.",
  },
  reporting: {
    role: "Compiles a fulfilment summary scoped to whoever's asking — a PM gets their project, a DM gets the whole account with a per-project breakdown. The Staffing lead uses its chat interface directly to ask which candidates just came out Internal Fit or Rejected, rather than waiting on a PM to say so.",
    removes: "Manually compiling a status deck before a review.",
  },
  notifier: {
    role: "The single door out to Slack and email. Every other agent routes its notifications through here, which is what guarantees no one gets pinged twice for the same event — and gives one place to see everything that's gone out.",
    removes: "“Wait, did I already tell the candidate/interviewer that?”",
  },
};

export default function AgentsPage() {
  const [agents, setAgents] = useState([]);
  const [active, setActive] = useState("orchestrator");
  const [tasks, setTasks] = useState([]);

  useEffect(() => { api.get("/agents").then((r) => setAgents(r.data)); }, []);
  useEffect(() => { api.get(`/agents/${active}/tasks`).then((r) => setTasks(r.data)); }, [active]);

  const activeAgent = agents.find((a) => a.id === active);

  return (
    <div className="p-8 space-y-8">
      <div>
        <h1 className="font-heading font-black text-4xl sm:text-5xl tracking-tight leading-none">Staffing Agents</h1>
        <p className="font-mono text-xs text-white/40 mt-2 tracking-[0.15em]">A2A PROTOCOL · {agents.length} AGENTS · VERSIONED TASK ENVELOPES</p>
      </div>
      <TooltipProvider delayDuration={200}>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {agents.map((a, i) => {
            const Icon = ICONS[a.id] || Network;
            const info = A2A_INFO[a.id];
            return (
              <Tooltip key={a.id}>
                <TooltipTrigger asChild>
                  <button onClick={() => setActive(a.id)} data-testid={`agent-card-${a.id}`}
                    style={{ animationDelay: `${i * 60}ms` }}
                    className={`agent-card-enter text-left border p-5 transition-[border-color,transform] duration-150 hover:-translate-y-[1px] ${active === a.id ? "border-[#007AFF] bg-[#007AFF]/5" : "border-white/15 bg-[#121212] hover:border-white/40"}`}>
                    <Icon size={18} className={active === a.id ? "text-[#007AFF]" : "text-white/40"} />
                    <p className="font-semibold text-sm mt-3">{a.name}</p>
                    <p className="font-mono text-[10px] text-white/40 mt-1 leading-relaxed">{a.tagline}</p>
                    <p className="font-mono text-[10px] text-[#007AFF]/70 mt-3">v{a.version} · {a.task_count} tasks</p>
                  </button>
                </TooltipTrigger>
                {info && (
                  <TooltipContent side="bottom" data-testid={`agent-tooltip-${a.id}`}
                    className="max-w-xs rounded-none border border-white/15 bg-[#0D0D0D] text-white px-4 py-3 shadow-xl">
                    <p className="text-xs leading-relaxed text-white/80">{info.role}</p>
                    <p className="font-mono text-[10px] text-[#32D74B] mt-2"><b className="text-white/50">REMOVES · </b>{info.removes}</p>
                  </TooltipContent>
                )}
              </Tooltip>
            );
          })}
        </div>
      </TooltipProvider>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="h-full">
          <AgentChatPanel agentKey={active} agentName={activeAgent?.name || active} suggestions={SUGGESTIONS[active] || []} />
        </div>
        <div className="space-y-4">
          {activeAgent && (
            <div className="border border-white/15 bg-[#121212] p-5" data-testid="agent-detail-panel">
              <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase">a2a.agent-card.v1</p>
              <div className="flex flex-wrap gap-2 mt-3">
                {activeAgent.skills.map((s) => <span key={s} className="font-mono text-[10px] border border-[#007AFF]/40 text-[#007AFF] px-2 py-1">{s}</span>)}
              </div>
              <p className="font-mono text-[10px] text-white/40 mt-3">tasks: {activeAgent.endpoints.tasks} · chat: {activeAgent.endpoints.chat}</p>
            </div>
          )}
          <div className="border border-white/15 bg-[#121212]" data-testid="agent-task-log">
            <p className="font-mono text-[10px] tracking-[0.2em] text-white/40 uppercase p-4 border-b border-white/15">Task log ({tasks.length})</p>
            <div className="divide-y divide-white/10 max-h-[340px] overflow-y-auto">
              {!tasks.length && <p className="font-mono text-xs text-white/40 p-4">// no A2A tasks yet for this agent</p>}
              {tasks.map((t) => (
                <div key={t.id} className="p-4">
                  <div className="flex items-center gap-3 font-mono text-xs">
                    <span className="text-white/80">{t.skill}</span>
                    <span className={`uppercase text-[10px] ${t.status === "completed" ? "text-[#32D74B]" : t.status === "failed" ? "text-[#FF3B30]" : "text-[#FF9F0A]"}`}>{t.status}</span>
                    <span className="text-white/30 ml-auto text-[10px]">{new Date(t.created_at).toLocaleString()}</span>
                  </div>
                  <p className="font-mono text-[10px] text-white/40 mt-1 break-all">key: {t.idempotency_key}</p>
                  {t.error && <p className="font-mono text-[10px] text-[#FF3B30] mt-1">{t.error}</p>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
