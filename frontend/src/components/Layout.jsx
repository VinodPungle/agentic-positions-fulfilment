import { NavLink, useLocation } from "react-router-dom";
import { LayoutGrid, CheckSquare, Users, CalendarClock, Bot, MessageSquare, Upload, BarChart3, CircuitBoard } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { usePersona } from "../context/PersonaContext";

const NAV = [
  { to: "/", label: "DASHBOARD", icon: LayoutGrid },
  { to: "/approvals", label: "APPROVALS", icon: CheckSquare },
  { to: "/interview-panel", label: "INTERVIEW PANEL", icon: Users },
  { to: "/interviews", label: "INTERVIEWS", icon: CalendarClock },
  { to: "/agents", label: "AGENTS", icon: Bot },
  { to: "/comms", label: "COMMS", icon: MessageSquare },
  { to: "/import", label: "IMPORT", icon: Upload },
  { to: "/reports", label: "REPORTS", icon: BarChart3 },
];

const ROLE_LABEL = { pm: "PROJECT MANAGER", service_line_leader: "SERVICE LINE LEADER", staffing: "STAFFING", tech_architect: "TECH ARCHITECT", admin: "ADMIN" };

export const Layout = ({ children }) => {
  const { users, user, setPersona } = usePersona();
  const location = useLocation();
  return (
    <div className="min-h-screen bg-background text-foreground flex">
      <aside className="w-56 shrink-0 border-r border-border flex flex-col fixed inset-y-0 z-20 bg-background">
        <div className="p-5 border-b border-border">
          <div className="flex items-center gap-2">
            <CircuitBoard size={20} className="text-[#007AFF]" />
            <span className="font-heading font-black text-lg tracking-tight">FULFIL·A2A</span>
          </div>
          <p className="font-mono text-[10px] text-muted-foreground mt-1 tracking-[0.2em]">ACCOUNT STAFFING</p>
        </div>
        <nav className="flex-1 py-4">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} data-testid={`nav-${label.toLowerCase().replace(/\s+/g, "-")}`}
              className={({ isActive }) =>
                `flex items-center gap-3 px-5 py-3 font-mono text-xs tracking-[0.15em] border-l-2 transition-colors duration-150 ${
                  isActive ? "border-[#007AFF] text-foreground bg-accent" : "border-transparent text-muted-foreground hover:text-foreground hover:bg-accent/50"}`}>
              <Icon size={15} /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="p-4 border-t border-border">
          <p className="font-mono text-[10px] text-muted-foreground tracking-[0.2em] mb-2">VIEWING AS</p>
          <Select value={user?.id || ""} onValueChange={setPersona}>
            <SelectTrigger data-testid="persona-switcher" className="bg-card border-border rounded-sm h-auto py-2">
              <SelectValue placeholder="Select persona" />
            </SelectTrigger>
            <SelectContent className="bg-card border-border text-foreground">
              {users.map((u) => (
                <SelectItem key={u.id} value={u.id} data-testid={`persona-option-${u.role}-${u.name.split(" ")[0].toLowerCase()}`}>
                  {u.name} — {ROLE_LABEL[u.role]}{u.projects?.length ? ` (${u.projects.join(", ")})` : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {user && (
            <p className="font-mono text-[10px] text-muted-foreground mt-2">
              SCOPE: {user.role === "pm" ? user.projects.join(", ").toUpperCase() : "ALL PROJECTS"}
            </p>
          )}
        </div>
      </aside>
      <main className="flex-1 min-w-0 ml-56 relative">
        <div className="noise-overlay" />
        <div key={`${user?.id}-${location.pathname}`} className="relative z-10">{children}</div>
      </main>
    </div>
  );
};
