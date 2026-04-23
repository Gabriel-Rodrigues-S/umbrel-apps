import fs from 'node:fs'
import path from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const scriptPath = path.resolve(process.cwd(), 'static/js/scripts.js')
const source = fs.readFileSync(scriptPath, 'utf8')

function carregarThemeManager() {
  const executar = new Function(`${source}\nreturn ThemeManager;`)
  return executar()
}

function prepararBootstrapFake() {
  globalThis.bootstrap = {
    Alert: class {
      close() {}
    },
    Tooltip: class {},
    Popover: class {},
  }
}

describe('ThemeManager', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('data-theme')
    document.head.innerHTML = ''
    document.body.innerHTML = ''
    localStorage.clear()
    vi.restoreAllMocks()

    prepararBootstrapFake()
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ theme: 'dark' }),
    })
  })

  it('getInitialTheme prioriza valor da meta tag', () => {
    document.head.innerHTML = '<meta name="theme-preference" content="dark">'

    const manager = carregarThemeManager()

    expect(manager.getInitialTheme()).toBe('dark')
  })

  it('getInitialTheme usa localStorage quando nao existe meta tag', () => {
    localStorage.setItem('theme-preference', 'dark')

    const manager = carregarThemeManager()

    expect(manager.getInitialTheme()).toBe('dark')
  })

  it('applyTheme define data-theme e alterna icone', () => {
    document.body.innerHTML = `
      <button id="theme-toggle" type="button" aria-label="Alternar tema claro/escuro" aria-pressed="false"></button>
      <i id="theme-icon" class="fas fa-sun"></i>
    `
    const manager = carregarThemeManager()

    manager.applyTheme('dark')

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(document.getElementById('theme-icon').classList.contains('fa-moon')).toBe(true)
    expect(document.getElementById('theme-icon').classList.contains('fa-sun')).toBe(false)
    expect(document.getElementById('theme-toggle').getAttribute('aria-pressed')).toBe('true')
    expect(document.getElementById('theme-toggle').getAttribute('aria-label')).toBe('Alternar para tema claro')
  })

  it('persistTheme salva em localStorage e nao sincroniza backend para anonimo', () => {
    const manager = carregarThemeManager()
    manager.syncWithBackend = vi.fn()

    manager.persistTheme('dark')

    expect(localStorage.getItem('theme-preference')).toBe('dark')
    expect(manager.syncWithBackend).not.toHaveBeenCalled()
  })

  it('persistTheme sincroniza backend para usuario autenticado', () => {
    document.body.innerHTML = '<div data-user-id="42"></div>'
    const manager = carregarThemeManager()
    manager.syncWithBackend = vi.fn()

    manager.persistTheme('dark')

    expect(localStorage.getItem('theme-preference')).toBe('dark')
    expect(manager.syncWithBackend).toHaveBeenCalledWith('dark')
  })

  it('bindThemeToggle alterna tema por click e Enter', () => {
    document.body.innerHTML = `
      <button id="theme-toggle" type="button">Tema</button>
      <i id="theme-icon" class="fas fa-sun"></i>
    `

    carregarThemeManager()

    const botao = document.getElementById('theme-toggle')
    document.documentElement.setAttribute('data-theme', 'light')

    botao.click()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')

    botao.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })
})
