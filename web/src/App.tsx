import { Navigate, Route, Routes } from 'react-router-dom'
import { AppLayout } from './components/AppLayout'
import { ErrorBoundary } from './components/ErrorBoundary'
import { RequireAuth } from './components/RequireAuth'
import { BatchDetail } from './pages/Batches/Detail'
import { BatchList } from './pages/Batches/List'
import { BatchNew } from './pages/Batches/New'
import { SampleDetail } from './pages/Batches/SampleDetail'
import { ConfigPage } from './pages/Config'
import { Dashboard } from './pages/Dashboard'
import { DevicesPage } from './pages/Devices/Index'
import { Login } from './pages/Login'
import BuilderHub from './pages/Profiles/BuilderHub'
import { ProfileEdit } from './pages/Profiles/Edit'
import { ProfileList } from './pages/Profiles/List'
import { LogsPage } from './pages/System/Logs'
import { TestsQuick } from './pages/Tests/Quick'

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="devices" element={<DevicesPage />} />
          <Route path="profiles" element={<ProfileList />} />
          <Route path="profiles/builder" element={<BuilderHub />} />
          <Route path="profiles/web-builder" element={<BuilderHub />} />
          <Route path="profiles/new" element={<ProfileEdit />} />
          <Route path="profiles/:name" element={<ProfileEdit />} />
          <Route path="tests/quick" element={<TestsQuick />} />
          <Route path="batches" element={<BatchList />} />
          <Route path="batches/new" element={<BatchNew />} />
          <Route path="batches/:id" element={<BatchDetail />} />
          <Route path="batches/:id/samples/:sid" element={<SampleDetail />} />
          <Route path="config" element={<ConfigPage />} />
          <Route path="system/logs" element={<LogsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ErrorBoundary>
  )
}
