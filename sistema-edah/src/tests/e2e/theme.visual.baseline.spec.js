const { test, expect } = require('@playwright/test')
const fs = require('node:fs')
const path = require('node:path')

const BASELINE_VERSION = 'v1'
const BASELINE_ROOT = path.resolve(process.cwd(), 'artifacts', 'baseline', 'theme', BASELINE_VERSION)

async function loginAsAdmin(page) {
  const adminPassword = process.env.BOOTSTRAP_ADMIN_PASSWORD || 'admin123'

  await page.goto('/login/')
  await page.getByLabel('E-mail').fill('admin@igreja.com')
  await page.getByLabel('Senha').fill(adminPassword)
  await page.getByRole('button', { name: 'Entrar' }).click()

  await expect(page).toHaveURL((url) => url.pathname === '/')
  const themeToggle = await ensureThemeToggleVisible(page)
  await expect(themeToggle).toBeVisible()
}

async function ensureThemeToggleVisible(page) {
  const themeToggle = page.locator('#theme-toggle')
  if (await themeToggle.isVisible()) {
    return themeToggle
  }

  const navbarToggler = page.locator('.navbar-toggler')
  if (await navbarToggler.isVisible()) {
    await navbarToggler.click()
  }

  await expect(themeToggle).toBeVisible()
  return themeToggle
}

async function setTheme(page, theme) {
  const current = await page.locator('html').getAttribute('data-theme')
  if (current !== theme) {
    const themeToggle = await ensureThemeToggleVisible(page)
    await themeToggle.click()
  }
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
}

async function captureRoute(page, profileName, themeName, routeName, routePath) {
  await page.goto(routePath)
  await page.waitForLoadState('networkidle')

  const outputDir = path.join(BASELINE_ROOT, profileName, themeName)
  fs.mkdirSync(outputDir, { recursive: true })

  const outputPath = path.join(outputDir, `${routeName}.png`)
  await page.screenshot({ path: outputPath, fullPage: true })
  expect(fs.existsSync(outputPath)).toBeTruthy()
}

test.describe('Baseline visual versionado - tema claro/escuro', () => {
  const viewports = [
    { name: 'desktop', width: 1366, height: 768 },
    { name: 'mobile', width: 390, height: 844 },
  ]

  for (const viewport of viewports) {
    test(`gera baseline ${viewport.name} para dashboard e configuracoes em light/dark`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await loginAsAdmin(page)

      await setTheme(page, 'light')
      await captureRoute(page, viewport.name, 'light', 'dashboard', '/')
      await captureRoute(page, viewport.name, 'light', 'configuracoes', '/configuracoes/')

      await setTheme(page, 'dark')
      await captureRoute(page, viewport.name, 'dark', 'dashboard', '/')
      await captureRoute(page, viewport.name, 'dark', 'configuracoes', '/configuracoes/')
    })
  }
})
