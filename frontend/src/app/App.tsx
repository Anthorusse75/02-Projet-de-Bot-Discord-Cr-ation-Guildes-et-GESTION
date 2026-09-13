import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { AppProviders } from './providers/AppProviders'
import { AppShell } from './AppShell'
import { AuthGate, LoginPage } from '../features/auth/AuthGate'
import { GuildSelectPage } from '../features/guilds/GuildSelectPage'
import { OnboardingPage } from '../features/guilds/OnboardingPage'
import { useInteractionStore } from '../shared/state/interaction'
import { Skeleton } from '../shared/components/ui'

const OverviewScreen = lazy(async () => ({
  default: (await import('../features/overview/OverviewScreen')).OverviewScreen,
}))
const StructureScreen = lazy(async () => ({
  default: (await import('../features/structure/StructureScreen')).StructureScreen,
}))
const RolesScreen = lazy(async () => ({
  default: (await import('../features/roles/RolesScreen')).RolesScreen,
}))
const PermissionsScreen = lazy(async () => ({
  default: (await import('../features/permissions/PermissionsScreen')).PermissionsScreen,
}))
const PlansScreen = lazy(async () => ({
  default: (await import('../features/plans/PlansScreen')).PlansScreen,
}))
const DiagnosticsScreen = lazy(async () => ({
  default: (await import('../features/diagnostics/DiagnosticsScreen')).DiagnosticsScreen,
}))
const AuditScreen = lazy(async () => ({
  default: (await import('../features/audit/AuditScreen')).AuditScreen,
}))
const TemplatesScreen = lazy(async () => ({
  default: (await import('../features/templates/TemplatesScreen')).TemplatesScreen,
}))
const LibraryScreen = lazy(async () => ({
  default: (await import('../features/library/LibraryScreen')).LibraryScreen,
}))
const CloneScreen = lazy(async () => ({
  default: (await import('../features/cloning/CloneScreen')).CloneScreen,
}))
const TranslationWorkspace = lazy(async () => ({
  default: (await import('../features/translations/TranslationWorkspace')).TranslationWorkspace,
}))
const CampaignCenter = lazy(async () => ({
  default: (await import('../features/campaigns/CampaignCenter')).CampaignCenter,
}))

function deferred(element: ReactNode) {
  return <Suspense fallback={<Skeleton />}>{element}</Suspense>
}

export function App() {
  const announcement = useInteractionStore((state) => state.announcement)
  return (
    <AppProviders>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<AuthGate />}>
          <Route path="/guilds" element={<GuildSelectPage />} />
          <Route path="/guild/:guildId/setup" element={<OnboardingPage />} />
          <Route path="/guild/:guildId" element={<AppShell />}>
            <Route index element={<Navigate to="overview" replace />} />
            <Route path="overview" element={deferred(<OverviewScreen />)} />
            <Route path="structure" element={deferred(<StructureScreen />)} />
            <Route path="roles" element={deferred(<RolesScreen />)} />
            <Route path="permissions" element={deferred(<PermissionsScreen />)} />
            <Route path="plans" element={deferred(<PlansScreen />)} />
            <Route path="diagnostics" element={deferred(<DiagnosticsScreen />)} />
            <Route path="audit" element={deferred(<AuditScreen />)} />
            <Route path="templates" element={deferred(<TemplatesScreen />)} />
            <Route path="library" element={deferred(<LibraryScreen />)} />
            <Route path="clone" element={deferred(<CloneScreen />)} />
            <Route path="translations" element={deferred(<TranslationWorkspace />)} />
            <Route path="campaigns" element={deferred(<CampaignCenter />)} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
      <div className="sr-only" aria-live="polite">{announcement}</div>
    </AppProviders>
  )
}
