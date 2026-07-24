import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });
api.interceptors.request.use((cfg) => {
  const id = localStorage.getItem("personaId");
  if (id) cfg.headers["X-User-Id"] = id;
  return cfg;
});

export async function streamChat(agentKey, message, onDelta) {
  const personaId = localStorage.getItem("personaId");
  const res = await fetch(`${API}/agents/${agentKey}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(personaId ? { "X-User-Id": personaId } : {}) },
    body: JSON.stringify({ message }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop();
    for (const part of parts) {
      if (part.startsWith("data: ")) {
        try {
          const evt = JSON.parse(part.slice(6));
          if (evt.delta) onDelta(evt.delta);
          if (evt.error) onDelta(`\n[error: ${evt.error}]`);
        } catch (e) { /* partial */ }
      }
    }
  }
}

export const STATUS_META = {
  OPEN: { label: "Open", color: "text-white/70 border-white/20" },
  EVALUATING: { label: "Evaluating", color: "text-[#007AFF] border-[#007AFF]/40" },
  PENDING_PM_APPROVAL: { label: "Awaiting PM Approval", color: "text-[#FFD60A] border-[#FFD60A]/40" },
  APPROVED: { label: "Approved", color: "text-[#32D74B] border-[#32D74B]/40" },
  INTERVIEW_INVITE_SENT: { label: "Invite Sent", color: "text-[#FF9F0A] border-[#FF9F0A]/40" },
  INTERVIEW_ACCEPTED: { label: "Interview Accepted", color: "text-[#64D2FF] border-[#64D2FF]/40" },
  FEEDBACK_RECEIVED: { label: "Feedback Received", color: "text-[#BF5AF2] border-[#BF5AF2]/40" },
  FILLED: { label: "Filled", color: "text-[#32D74B] border-[#32D74B]/60" },
  CLOSED: { label: "Closed", color: "text-white/40 border-white/15" },
};

export const BOARD_COLUMNS = [
  { key: "OPEN", statuses: ["OPEN"] },
  { key: "EVALUATING", statuses: ["EVALUATING"] },
  { key: "PENDING_PM_APPROVAL", statuses: ["PENDING_PM_APPROVAL"] },
  { key: "APPROVED", statuses: ["APPROVED"] },
  { key: "INTERVIEWING", statuses: ["INTERVIEW_INVITE_SENT", "INTERVIEW_ACCEPTED"], label: "Interviewing" },
  { key: "FEEDBACK_RECEIVED", statuses: ["FEEDBACK_RECEIVED"] },
  { key: "FILLED", statuses: ["FILLED", "CLOSED"], label: "Filled / Closed" },
];
