import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { App } from './App'

describe('foundation route shell', () => {
  it('renders only the technical foundation marker', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: 'Discord Infrastructure Designer' })).toBeVisible()
    expect(screen.getByLabelText('application-status')).toHaveTextContent('foundation-ready')
  })
})
