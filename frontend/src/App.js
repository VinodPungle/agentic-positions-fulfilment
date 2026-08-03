import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "next-themes";
import { Toaster } from "./components/ui/sonner";
import { PersonaProvider } from "./context/PersonaContext";
import { Layout } from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import PositionDetail from "./pages/PositionDetail";
import Approvals from "./pages/Approvals";
import InterviewPanel from "./pages/InterviewPanel";
import Interviews from "./pages/Interviews";
import AgentsPage from "./pages/AgentsPage";
import Comms from "./pages/Comms";
import ImportPage from "./pages/ImportPage";
import Reports from "./pages/Reports";

function App() {
  return (
    // attribute="class" toggles the `.dark` class on <html> (what tailwind.config.js's
    // darkMode: ["class"] and every dark:-prefixed/CSS-variable-based style respond
    // to) — see ThemeToggle.jsx for where the user actually switches this.
    // defaultTheme="dark" preserves the app's original look for anyone who hasn't
    // picked a preference yet; enableSystem is off since this is an internal tool,
    // not something that should silently follow the OS.
    <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} storageKey="theme">
      <div className="App">
        <PersonaProvider>
          <BrowserRouter>
            <Layout>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/positions/:id" element={<PositionDetail />} />
                <Route path="/approvals" element={<Approvals />} />
                <Route path="/interview-panel" element={<InterviewPanel />} />
                <Route path="/interviews" element={<Interviews />} />
                <Route path="/agents" element={<AgentsPage />} />
                <Route path="/comms" element={<Comms />} />
                <Route path="/import" element={<ImportPage />} />
                <Route path="/reports" element={<Reports />} />
              </Routes>
            </Layout>
          </BrowserRouter>
          {/* No explicit theme prop — Toaster (sonner.jsx) reads the live theme via
              next-themes' useTheme() itself now that a ThemeProvider actually exists. */}
          <Toaster position="bottom-right" />
        </PersonaProvider>
      </div>
    </ThemeProvider>
  );
}

export default App;
