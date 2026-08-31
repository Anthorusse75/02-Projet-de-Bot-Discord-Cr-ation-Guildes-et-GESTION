import { Navigate, Route, Routes } from 'react-router-dom'
import { AppProviders } from './providers/AppProviders'
import { AppShell } from './AppShell'
import { AuthGate, LoginPage } from '../features/auth/AuthGate'
import { GuildSelectPage } from '../features/guilds/GuildSelectPage'
import { StructureScreen } from '../features/structure/StructureScreen'
import { RolesScreen } from '../features/roles/RolesScreen'
import { PermissionsScreen } from '../features/permissions/PermissionsScreen'
import { PlansScreen } from '../features/plans/PlansScreen'
import { DiagnosticsScreen } from '../features/diagnostics/DiagnosticsScreen'
import { AuditScreen } from '../features/audit/AuditScreen'
import { TemplatesScreen } from '../features/templates/TemplatesScreen'
import { LibraryScreen } from '../features/library/LibraryScreen'
import { CloneScreen } from '../features/cloning/CloneScreen'
import { useInteractionStore } from '../shared/state/interaction'
import { TranslationWorkspace } from '../features/translations/TranslationWorkspace'

export function App() {
  const announcement = useInteractionStore((state) => state.announcement)
  return (
    <AppProviders>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AuthGate />}>
          <Route path="/guilds" element={<GuildSelectPage />} />
          <Route path="/guild/:guildId" element={<AppShell />}>
            <Route index element={<Navigate to="structure" replace />} />
            <Route path="structure" element={<StructureScreen />} />
            <Route path="roles" element={<RolesScreen />} />
            <Route path="permissions" element={<PermissionsScreen />} />
            <Route path="plans" element={<PlansScreen />} />
            <Route path="diagnostics" element={<DiagnosticsScreen />} />
            <Route path="audit" element={<AuditScreen />} />
            <Route path="templates" element={<TemplatesScreen />} />
            <Route path="library" element={<LibraryScreen />} />
            <Route path="clone" element={<CloneScreen />} />
            <Route path="translations" element={<TranslationWorkspace />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
      <div className="sr-only" aria-live="polite">{announcement}</div>
    </AppProviders>
  )
}
