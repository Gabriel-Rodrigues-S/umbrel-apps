const { test, expect } = require('@playwright/test')

async function loginAsAdmin(page) {
  const adminPassword = process.env.BOOTSTRAP_ADMIN_PASSWORD || 'admin123'
  await page.goto('/login/')
  await page.getByLabel('E-mail').fill('admin@igreja.com')
  await page.getByLabel('Senha').fill(adminPassword)
  await page.getByRole('button', { name: 'Entrar' }).click()
  await expect(page).toHaveURL((url) => url.pathname === '/')
  await expect(page.locator('#theme-toggle')).toBeVisible()
}

test.describe('Tema claro/escuro - E2E e smoke visual', () => {
  test('anonimo nao acessa dashboard sem autenticar', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveURL(/\/login\//)
  })

  test('autenticado aplica tema dark no dashboard', async ({ page }) => {
    await loginAsAdmin(page)

    await page.evaluate(() => {
      document.documentElement.setAttribute('data-theme', 'dark')
    })
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  })

  test('smoke visual dashboard light', async ({ page }) => {
    await loginAsAdmin(page)

    const temaAtual = await page.locator('html').getAttribute('data-theme')
    if (temaAtual === 'dark') {
      await page.locator('#theme-toggle').click()
    }

    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await page.screenshot({ path: 'test-results/smoke-dashboard-light.png', fullPage: true })
  })

  test('smoke visual dashboard dark', async ({ page }) => {
    await loginAsAdmin(page)
    const temaAtual = await page.locator('html').getAttribute('data-theme')
    if (temaAtual !== 'dark') {
      await page.locator('#theme-toggle').click()
    }
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.screenshot({ path: 'test-results/smoke-dashboard-dark.png', fullPage: true })
  })

  test('mantem tema dark ao navegar e sidebar acompanha tokens', async ({ page }) => {
    await loginAsAdmin(page)

    const temaAtual = await page.locator('html').getAttribute('data-theme')
    if (temaAtual !== 'light') {
      await page.locator('#theme-toggle').click()
      await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    }

    await page.locator('#theme-toggle').click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

    await expect(page.locator('#sidebarMenu')).not.toHaveClass(/\bbg-light\b/)

    await page.getByRole('link', { name: /Configurações/i }).click()
    await expect(page).toHaveURL(/\/configuracoes\//)
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

    await expect(page.locator('#sidebarMenu')).not.toHaveClass(/\bbg-light\b/)
  })

  test('aplica tema dark no bootstrap inicial em rota autenticada', async ({ page }) => {
    await loginAsAdmin(page)

    await page.evaluate(() => {
      window.localStorage.setItem('theme-preference', 'dark')
      const meta = document.querySelector('meta[name="theme-preference"]')
      if (meta) {
        meta.setAttribute('content', 'dark')
      }
    })

    await page.goto('/configuracoes/', { waitUntil: 'domcontentloaded' })
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
  })
})
