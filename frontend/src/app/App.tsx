import { Route, Routes } from 'react-router-dom'

import { FoundationShell } from '../pages/FoundationShell'

export function App() {
  return (
    <Routes>
      <Route path="*" element={<FoundationShell />} />
    </Routes>
  )
}
