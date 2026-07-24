import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "./components/ui/sonner";
import { PersonaProvider } from "./context/PersonaContext";
import { Layout } from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import PositionDetail from "./pages/PositionDetail";
import Approvals from "./pages/Approvals";
import Interviews from "./pages/Interviews";
import AgentsPage from "./pages/AgentsPage";
import Comms from "./pages/Comms";
import ImportPage from "./pages/ImportPage";
import Reports from "./pages/Reports";

function App() {
  return (
    <div className="App dark">
      <PersonaProvider>
        <BrowserRouter>
          <Layout>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/positions/:id" element={<PositionDetail />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/interviews" element={<Interviews />} />
              <Route path="/agents" element={<AgentsPage />} />
              <Route path="/comms" element={<Comms />} />
              <Route path="/import" element={<ImportPage />} />
              <Route path="/reports" element={<Reports />} />
            </Routes>
          </Layout>
        </BrowserRouter>
        <Toaster theme="dark" position="bottom-right" />
      </PersonaProvider>
    </div>
  );
}

export default App;
