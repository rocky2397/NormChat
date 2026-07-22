import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AuthGate from './components/AuthGate'
import Login from './pages/Login'
import PDFViewerPage from './pages/PDFViewerPage'
import ProjectList from './pages/ProjectList'
import ProjectView from './pages/ProjectView'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<AuthGate />}>
          <Route path="/" element={<ProjectList />} />
          <Route path="/projects/:projectId" element={<ProjectView />} />
          <Route path="/viewer" element={<PDFViewerPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
