import { Route, Routes } from 'react-router-dom'

import { AuthTenantShell } from '../pages/AuthTenantShell'

export function App() {
  return (
    <Routes>
      <Route path="*" element={<AuthTenantShell />} />
    </Routes>
  )
}
