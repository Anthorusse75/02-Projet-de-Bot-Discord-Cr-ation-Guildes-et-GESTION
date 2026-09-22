import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './app/App'
import '@mantine/core/styles.css'
import '@mantine/dates/styles.css'
import '@mantine/notifications/styles.css'
import '@mantine/nprogress/styles.css'
import '@mantine/spotlight/styles.css'
import './shared/styles.css'
import './shared/redesign.css'
import './shared/login-redesign.css'
import './shared/phase3-structure.css'
import './shared/phase4-access.css'
import './features/policies/policies.css'
import './features/matrix/matrix.css'
import './features/wizards/wizards.css'
import './shared/bunny-theme.css'
import './shared/bunny-shell.css'
import './shared/bunny-roles.css'
import './shared/bunny-access.css'

const root = document.getElementById('root')

if (root === null) {
  throw new Error('Missing application root')
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
