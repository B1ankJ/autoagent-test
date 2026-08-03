import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/test-utils'
import { DiffText } from './DiffText'

describe('DiffText', () => {
  it('renders unchanged, removed (strikethrough) and added words', () => {
    renderWithProviders(<DiffText before="hello world" after="hello there" />)

    // Unchanged text stays present.
    expect(screen.getByText(/hello/)).toBeInTheDocument()

    // The word only in `before` is marked removed with a line-through.
    const removed = screen.getByText('world')
    expect(removed).toHaveStyle({ textDecoration: 'line-through' })

    // The word only in `after` is present (added).
    expect(screen.getByText('there')).toBeInTheDocument()
  })

  it('renders identical strings with no removed/added marks', () => {
    const { container } = renderWithProviders(
      <DiffText before="same text" after="same text" />,
    )
    expect(container.textContent).toContain('same text')
    expect(
      container.querySelector('[style*="line-through"]'),
    ).toBeNull()
  })
})
