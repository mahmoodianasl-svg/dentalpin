import { test as base, expect, type Page } from '@playwright/test'

/**
 * Credentials for the seeded demo users (`./scripts/seed-demo.sh`).
 * All share the password `demo1234`.
 */
export const ROLES = {
  admin: 'admin@demo.clinic',
  dentist: 'dentist@demo.clinic',
  hygienist: 'hygienist@demo.clinic',
  assistant: 'assistant@demo.clinic',
  receptionist: 'receptionist@demo.clinic'
} as const

export type Role = keyof typeof ROLES

const API_BASE = process.env.E2E_API_BASE || 'http://localhost:8000'
const accessTokens = new WeakMap<Page, string>()

export function accessTokenFor(page: Page): string {
  const token = accessTokens.get(page)
  if (!token) throw new Error('page has no E2E access token')
  return token
}

/**
 * Log in through the direct API while preserving backend session cookies.
 *
 * We bypass the browser form for two reasons:
 * 1. Chromium's preflight interaction with Nuxt's client-side fetch
 *    flakes in Playwright (the form works fine in a real browser).
 * 2. The browser context's API client shares its cookie jar with the page,
 *    so the backend's HttpOnly refresh cookie reaches Nuxt on navigation.
 *
 * After this, a regular ``page.goto(...)`` lets the auth middleware recover
 * an in-memory access token through the protected refresh session.
 */
export async function login(page: Page, role: Role): Promise<void> {
  const ctx = page.context()

  const form = new URLSearchParams({
    username: ROLES[role],
    password: 'demo1234'
  })
  const response = await ctx.request.post(`${API_BASE}/api/v1/auth/login`, {
    data: form.toString(),
    headers: { 'content-type': 'application/x-www-form-urlencoded' }
  })
  if (!response.ok()) {
    throw new Error(`login failed: ${response.status()} ${await response.text()}`)
  }
  const body = (await response.json()) as { access_token: string }
  accessTokens.set(page, body.access_token)

  // Prime the session by landing on the dashboard.
  await page.goto('/')
  await page.waitForURL(url => url.pathname === '/', { timeout: 10_000 })
}

type RoleFixture = {
  role: Role
  loggedIn: Page
}

export const test = base.extend<RoleFixture>({
  role: ['admin', { option: true }],
  loggedIn: async ({ page, role }, use) => {
    await login(page, role)
    await use(page)
  }
})

export { expect }
