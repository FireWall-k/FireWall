import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppProvider } from "./store/AppStore";
import { AdminLayout } from "./components/AdminLayout";
import { AdminTasksPage } from "./pages/AdminTasksPage";
import { DashboardPage } from "./pages/DashboardPage";
import { WorkerCardPage } from "./pages/WorkerCardPage";

function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/admin/tasks" replace />} />
          <Route element={<AdminLayout />}>
            <Route path="/admin/tasks" element={<AdminTasksPage />} />
            <Route path="/admin/dashboard" element={<DashboardPage />} />
          </Route>
          <Route path="/worker" element={<WorkerCardPage />} />
          <Route path="/worker/:taskId" element={<WorkerCardPage />} />
        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}

export default App;
