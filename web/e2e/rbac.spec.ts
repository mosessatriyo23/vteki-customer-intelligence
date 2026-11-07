
import { test, expect, Page, APIRequestContext } from '@playwright/test'

const password = process.env.E2E_TEST_PASSWORD

const accounts = {
  admin: 'e2e-admin@example.com',
  analyst: 'e2e-analyst@example.com',
  operator: 'e2e-operator@example.com',
  campaign: 'e2e-campaign@example.com',
}

const baseUrl = 'http://127.0.0.1:4173'

async function login(page: Page, email: string) {
  if (!password) {
    throw new Error('E2E_TEST_PASSWORD belum diatur.')
  }

  await page.goto('/')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Masuk' }).click()

  await expect(
    page.getByRole('button', { name: 'Keluar' }),
  ).toBeVisible({ timeout: 15000 })
}

async function openPage(page: Page, name: string) {
  await page
    .getByRole('navigation', { name: 'Main navigation' })
    .getByText(name, { exact: true })
    .click()
}

async function getToken(
  request: APIRequestContext,
  email: string,
) {
  if (!password) {
    throw new Error('E2E_TEST_PASSWORD belum diatur.')
  }

  const response = await request.post(`${baseUrl}/api/auth/login`, {
    data: { email, password },
  })

  expect(response.ok()).toBeTruthy()

  const result = await response.json()
  return result.access_token as string
}

async function createDecision(request: APIRequestContext) {
  const token = await getToken(request, accounts.admin)

  const customerResponse = await request.get(
    `${baseUrl}/api/customers`,
    {
      headers: { Authorization: `Bearer ${token}` },
    },
  )

  expect(customerResponse.ok()).toBeTruthy()

  const customers = await customerResponse.json()
  const customer = customers[0]

  if (!customer?.id) {
    throw new Error('Database E2E belum memiliki pelanggan.')
  }

  const action = `E2E Override Test ${Date.now()}`

  const response = await request.post(
    `${baseUrl}/api/decisions/next-best-actions`,
    {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        customer_id: customer.id,
        recommended_action: action,
        rationale: {
          reason: 'Pengujian Playwright RBAC',
          source: 'E2E',
        },
      },
    },
  )

  expect(response.status()).toBe(201)

  const result = await response.json()

  return {
    id: result.id as number,
    action,
  }
}

test.describe('Frontend RBAC - empat role', () => {
  test('Admin dapat mengakses fitur pengelolaan utama', async ({ page }) => {
    await login(page, accounts.admin)

    await openPage(page, 'Campaigns & Approval')
    await expect(
      page.getByRole('button', { name: 'Kampanye Baru' }),
    ).toBeVisible()

    await openPage(page, 'Manual Review Identitas')
    await expect(
      page.getByRole('button', { name: 'Tambah kasus' }),
    ).toBeVisible()

    await openPage(page, 'Next-Best-Action & Override')
    await expect(
      page.getByRole('button', { name: 'Buat proposal NBA' }),
    ).toBeVisible()

    await openPage(page, 'Monitoring & Audit Trace')
    await expect(
      page.getByText('Jalankan Penelusuran Trace'),
    ).toBeVisible()
  })

  test('Analyst dapat membuat NBA dan melihat audit trace', async ({ page }) => {
    await login(page, accounts.analyst)

    await openPage(page, 'Campaigns & Approval')
    await expect(
      page.getByRole('button', { name: 'Kampanye Baru' }),
    ).toHaveCount(0)

    await openPage(page, 'Manual Review Identitas')
    await expect(
      page.getByRole('button', { name: 'Tambah kasus' }),
    ).toHaveCount(0)

    await openPage(page, 'Next-Best-Action & Override')
    await expect(
      page.getByRole('button', { name: 'Buat proposal NBA' }),
    ).toBeVisible()

    await expect(
      page.getByRole('button', { name: 'Human Override Manual' }),
    ).toHaveCount(0)

    await openPage(page, 'Monitoring & Audit Trace')
    await expect(
      page.getByText('Jalankan Penelusuran Trace'),
    ).toBeVisible()
  })

  test('Operator hanya mendapat akses review identitas', async ({ page }) => {
    await login(page, accounts.operator)

    await openPage(page, 'Campaigns & Approval')
    await expect(
      page.getByRole('button', { name: 'Kampanye Baru' }),
    ).toHaveCount(0)

    await openPage(page, 'Manual Review Identitas')
    await expect(
      page.getByRole('button', { name: 'Tambah kasus' }),
    ).toBeVisible()

    await openPage(page, 'Next-Best-Action & Override')
    await expect(
      page.getByRole('button', { name: 'Buat proposal NBA' }),
    ).toHaveCount(0)

    await expect(
      page.getByRole('button', { name: 'Human Override Manual' }),
    ).toHaveCount(0)

    await openPage(page, 'Monitoring & Audit Trace')
    await expect(
      page.getByText('Jalankan Penelusuran Trace'),
    ).toHaveCount(0)
  })

  test('Campaign Manager berhasil melakukan Human Override', async ({
    page,
    request,
  }) => {
    const decision = await createDecision(request)

    await login(page, accounts.campaign)
    await openPage(page, 'Next-Best-Action & Override')

    const card = page.locator('.decision-card').filter({
      has: page.locator('.nba-text', {
        hasText: decision.action,
      }),
    })

    await expect(card).toBeVisible({ timeout: 15000 })

    await card
      .getByRole('button', { name: 'Human Override Manual' })
      .click()

    await page
      .getByLabel('Tindakan Override Baru (Manual Action)')
      .fill('E2E - Berikan penawaran loyalitas khusus')

    await page
      .getByLabel(
        'Alasan & Justifikasi Pengambilalihan (Mandatory Audit Reason)',
      )
      .fill(
        'Penyesuaian strategi berdasarkan hasil evaluasi pengujian.',
      )

    await page
      .getByRole('button', { name: 'Simpan Override' })
      .click()

    await expect(
      page.getByText('E2E - Berikan penawaran loyalitas khusus').first(),
    ).toBeVisible({ timeout: 15000 })

    await expect(
      page.locator('.override-label').filter({
        hasText: 'DITERAPKAN HUMAN OVERRIDE:',
      }).first(),
    ).toBeVisible()
  })

  test('API menolak Analyst dan Operator melakukan override', async ({
    request,
  }) => {
    const decision = await createDecision(request)

    for (const email of [accounts.analyst, accounts.operator]) {
      const token = await getToken(request, email)

      const response = await request.post(
        `${baseUrl}/api/decisions/next-best-actions/${decision.id}/override`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
          data: {
            selected_action: 'Aksi yang tidak diizinkan',
            reason: 'Pengujian pembatasan akses role.',
          },
        },
      )

      expect(
        response.status(),
        `${email} seharusnya ditolak oleh API`,
      ).toBe(403)
    }
  })
})
