import { useEffect, useRef, useState } from "react";
import { api, streamChat } from "../lib/api";
import { usePersona } from "../context/PersonaContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { SendHorizontal, Terminal } from "lucide-react";

export const AgentChatPanel = ({ agentKey, agentName, suggestions = [] }) => {
  const { user } = usePersona();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    setMessages([]);
    api.get(`/agents/${agentKey}/chat/history`).then((r) => setMessages(r.data)).catch(() => {});
  }, [agentKey, user?.id]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = async (text) => {
    const msg = (text || input).trim();
    if (!msg || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: msg }, { role: "agent", content: "" }]);
    try {
      await streamChat(agentKey, msg, (delta) => {
        setMessages((m) => {
          const copy = [...m];
          copy[copy.length - 1] = { ...copy[copy.length - 1], content: copy[copy.length - 1].content + delta };
          return copy;
        });
      });
    } catch (e) {
      setMessages((m) => [...m.slice(0, -1), { role: "agent", content: `[connection error: ${e.message}]` }]);
    }
    setBusy(false);
  };

  return (
    <div className="flex flex-col h-full bg-black border border-white/15" data-testid={`agent-chat-${agentKey}`}>
      <div className="flex items-center gap-2 px-4 py-3 border-b border-white/15 bg-[#0D0D0D]">
        <Terminal size={14} className="text-[#007AFF]" />
        <span className="font-mono text-xs tracking-[0.2em] text-white/70 uppercase">{agentName} / TERMINAL</span>
        <span className={`ml-auto w-2 h-2 rounded-full ${busy ? "bg-[#FF9F0A] animate-pulse" : "bg-[#32D74B]"}`} />
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4 font-mono text-sm min-h-[280px] max-h-[420px]">
        {messages.length === 0 && (
          <div className="space-y-2">
            <p className="text-white/40">// no messages yet — ask {agentName} anything within your scope</p>
            {suggestions.map((s) => (
              <button key={s} onClick={() => send(s)} data-testid="chat-suggestion"
                className="block text-left text-xs text-[#007AFF]/80 hover:text-[#007AFF] border border-[#007AFF]/20 hover:border-[#007AFF]/50 px-3 py-2 w-full transition-colors duration-150">
                → {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i}>
            <span className={`text-[10px] tracking-[0.2em] ${m.role === "user" ? "text-white/50" : "text-[#007AFF]"}`}>
              {m.role === "user" ? `${user?.name?.toUpperCase() || "YOU"} $` : `${agentName.toUpperCase()} >`}
            </span>
            <p className={`whitespace-pre-wrap mt-1 leading-relaxed ${m.role === "user" ? "text-white/90" : "text-[#7cb8ff] drop-shadow-[0_0_6px_rgba(0,122,255,0.25)]"}`}>
              {m.content || (busy && i === messages.length - 1 ? "▋" : "")}
            </p>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      <div className="flex gap-2 p-3 border-t border-white/15 bg-[#0D0D0D]">
        <Input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder={`Message ${agentName}…`} disabled={busy} data-testid="chat-input"
          className="bg-black border-white/20 rounded-sm font-mono text-sm text-white placeholder:text-white/30" />
        <Button onClick={() => send()} disabled={busy || !input.trim()} data-testid="chat-send-button"
          className="bg-[#007AFF] hover:bg-[#0063CC] rounded-sm px-4">
          <SendHorizontal size={16} />
        </Button>
      </div>
    </div>
  );
};
