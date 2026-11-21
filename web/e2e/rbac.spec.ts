
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
  await page.getByRole('textbox', { name: 'Kata sandi' }).fill(password)
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

async function createCustomer(request: APIRequestContext) {
  const token = await getToken(request, accounts.admin)
  const suffix = `${Date.now()}-${Math.floor(Math.random() * 100000)}`
  const customerResponse = await request.post(`${baseUrl}/api/customers`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      customer_code: `E2E-${suffix}`,
      full_name: 'Pelanggan Acceptance Test',
      email: `e2e-${suffix}@example.com`,
      segment: 'E2E',
    },
  })
  expect(customerResponse.status()).toBe(201)
  return customerResponse.json() as Promise<{ id: number }>
}

async function createDecision(request: APIRequestContext) {
  const token = await getToken(request, accounts.admin)
  const customer = await createCustomer(request)

  const response = await request.post(
    `${baseUrl}/api/decisions/next-best-actions/evaluate`,
    {
      headers: { Authorization: `Bearer ${token}` },
      data: { customer_id: customer.id },
    },
  )

  expect(response.status()).toBe(201)

  const result = await response.json()
  expect(result.selected_action).toBe('NO_ACTION')

  return {
    id: result.id as number,
    action: result.selected_action as string,
  }
}

test.describe('Frontend RBAC - empat role', () => {
  test('Admin dapat mengakses fitur pengelolaan utama', async ({ page }) => {
    await login(page, accounts.admin)

    await openPage(page, 'Kampanye & Persetujuan')
    await expect(
      page.getByRole('button', { name: 'Kampanye Baru' }),
    ).toBeVisible()

    await openPage(page, 'Manual Review Identitas')
    await expect(
      page.getByRole('button', { name: 'Tambah kasus' }),
    ).toBeVisible()

    await openPage(page, 'Proposal Tindakan')
    await expect(
      page.getByRole('button', { name: 'Jalankan evaluasi NBA' }),
    ).toBeVisible()

    await openPage(page, 'Pemantauan & Audit')
    await expect(
      page.getByText('Jalankan Penelusuran Trace'),
    ).toBeVisible()
  })

  test('Analyst dapat membuat NBA dan melihat audit trace', async ({ page }) => {
    await login(page, accounts.analyst)

    await openPage(page, 'Kampanye & Persetujuan')
    await expect(
      page.getByRole('button', { name: 'Kampanye Baru' }),
    ).toHaveCount(0)

    await openPage(page, 'Manual Review Identitas')
    await expect(
      page.getByRole('button', { name: 'Tambah kasus' }),
    ).toHaveCount(0)

    await openPage(page, 'Proposal Tindakan')
    await expect(
      page.getByRole('button', { name: 'Jalankan evaluasi NBA' }),
    ).toBeVisible()

    await expect(
      page.getByRole('button', { name: 'Human Override Manual' }),
    ).toHaveCount(0)

    await openPage(page, 'Pemantauan & Audit')
    await expect(
      page.getByText('Jalankan Penelusuran Trace'),
    ).toBeVisible()
  })

  test('Operator hanya mendapat akses review identitas', async ({ page }) => {
    await login(page, accounts.operator)

    await openPage(page, 'Kampanye & Persetujuan')
    await expect(
      page.getByRole('button', { name: 'Kampanye Baru' }),
    ).toHaveCount(0)

    await openPage(page, 'Manual Review Identitas')
    await expect(
      page.getByRole('button', { name: 'Tambah kasus' }),
    ).toBeVisible()

    await openPage(page, 'Proposal Tindakan')
    await expect(
      page.getByRole('button', { name: 'Jalankan evaluasi NBA' }),
    ).toHaveCount(0)

    await expect(
      page.getByRole('button', { name: 'Human Override Manual' }),
    ).toHaveCount(0)

    await openPage(page, 'Pemantauan & Audit')
    await expect(
      page.getByText('Jalankan Penelusuran Trace'),
    ).toHaveCount(0)
  })

  test('Campaign Manager tidak dapat override hasil NO_ACTION', async ({
    page,
    request,
  }) => {
    const decision = await createDecision(request)

    await login(page, accounts.campaign)
    await openPage(page, 'Proposal Tindakan')

    const card = page.locator('.decision-card').filter({
      has: page.locator('.nba-text', {
        hasText: decision.action,
      }),
    })

    await expect(card).toBeVisible({ timeout: 15000 })
    await expect(
      card.getByRole('button', { name: 'Human Override Manual' }),
    ).toHaveCount(0)

    const token = await getToken(request, accounts.campaign)
    const response = await request.post(
      `${baseUrl}/api/governance/nba-decisions/${decision.id}/override`,
      {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          selected_action: 'E2E - Berikan penawaran loyalitas khusus',
          override_reason: 'Hasil NO_ACTION tidak dapat diubah menjadi tindakan promosi.',
        },
      },
    )
    expect(response.status()).toBe(409)
  })

  test('API menolak Analyst dan Operator melakukan override', async ({
    request,
  }) => {
    for (const email of [accounts.analyst, accounts.operator]) {
      const token = await getToken(request, email)

      const response = await request.post(
        `${baseUrl}/api/governance/nba-decisions/2147483647/override`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
          data: {
            selected_action: 'Aksi yang tidak diizinkan',
            override_reason: 'Pengujian pembatasan akses role.',
          },
        },
      )

      expect(
        response.status(),
        `${email} seharusnya ditolak oleh API`,
      ).toBe(403)
    }
  })

  test('Campaign Manager menyelesaikan approval dan audit trace dapat direkonstruksi', async ({
    page,
    request,
  }) => {
    const campaignName = `E2E Approval ${Date.now()}`
    await createCustomer(request)
    await login(page, accounts.campaign)
    await openPage(page, 'Kampanye & Persetujuan')
    await page.getByRole('button', { name: 'Kampanye Baru' }).click()
    await page.getByLabel('Nama Kampanye').fill(campaignName)
    await page
      .getByLabel('Target Segmen Pelanggan')
      .selectOption({ index: 1 })
    await page
      .getByLabel('Draf Pesan Kampanye (Persetujuan Draf)')
      .fill('Pesan approval E2E untuk channel simulator.')

    const createdResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/campaigns') &&
        response.request().method() === 'POST',
    )
    await page
      .getByRole('button', { name: 'Simpan Draf Kampanye' })
      .click()
    const campaign = await (await createdResponse).json()
    const correlationId = campaign.correlation_id as string
    if (!correlationId) {
      throw new Error('Campaign response tidak memiliki correlation_id.')
    }

    const campaignRow = page
      .getByRole('row')
      .filter({ hasText: campaignName })
    await campaignRow
      .getByRole('button', { name: 'Ajukan Approval' })
      .click()
    await campaignRow.getByRole('button', { name: 'Setujui' }).click()
    await expect(campaignRow.getByText('Approved')).toBeVisible()

    await page.getByRole('button', { name: 'Keluar' }).click()
    await login(page, accounts.admin)
    await openPage(page, 'Pemantauan & Audit')
    await page
      .getByPlaceholder('Masukkan correlation_id workflow...')
      .fill(correlationId)
    await page
      .getByRole('button', { name: 'Jalankan Penelusuran Trace' })
      .click()
    await expect(page.getByText('campaign.approved', { exact: true })).toBeVisible()
  })

  test('Operator membuat dan menyelesaikan identity review', async ({ page }) => {
    const subject = `E2E Identity ${Date.now()}`
    await login(page, accounts.operator)
    await openPage(page, 'Manual Review Identitas')
    await page.getByRole('button', { name: 'Tambah kasus' }).click()
    await page.getByLabel('Referensi utama').fill(subject)
    await page
      .getByLabel('Kandidat, pisahkan dengan koma')
      .fill(`candidate-${Date.now()}`)
    await page.getByLabel('Confidence (0–1)').fill('0.52')
    await page
      .getByLabel('Alasan flagging')
      .fill('Acceptance test identity review workflow.')
    await page.getByRole('button', { name: 'Masukkan ke antrean' }).click()

    const reviewCard = page
      .locator('.review-card')
      .filter({ hasText: subject })
    await expect(reviewCard).toBeVisible()
    await expect(
      reviewCard.getByRole('button', { name: 'Tolak Gabung Identitas' }),
    ).toBeVisible()
    await reviewCard
      .getByRole('button', { name: 'Tolak Gabung Identitas' })
      .click()
    await expect(reviewCard.getByText('Rejected')).toBeVisible()
    await expect(
      reviewCard.getByText('Resolusi Identitas Telah Diselesaikan'),
    ).toBeVisible()
  })

})
