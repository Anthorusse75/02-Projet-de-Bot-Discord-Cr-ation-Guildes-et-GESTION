import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './app/App'
import './shared/styles.css'
import './shared/redesign.css'
import './shared/login-redesign.css'
import './shared/phase3-structure.css'
import './shared/phase4-access.css'
import './features/policies/policies.css'
import './features/wizards/wizards.css'

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
