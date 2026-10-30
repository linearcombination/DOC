import { test, expect } from '@playwright/test'

test('OT rg1, rg3, and rg4', async ({ page }) => {
  await page.goto('http://localhost:8001/passages')
  await page.getByText('English').click()
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByText('Add OT Survey RG1 Passages').click()
  await expect(page.locator('body')).toContainText('Genesis 1:1-2:3', { timeout: 32_000 })
  await page.locator('.collapse > input').check()
  await expect(page.locator('body')).toContainText('Exodus 1:1-2:10', { timeout: 32_000 })
  await expect(page.locator('body')).toContainText('Exodus 12:1-20', { timeout: 32_000 })
  await expect(page.locator('body')).toContainText('Exodus 12:21-42', { timeout: 32_000 })
  await expect(page.locator('body')).toContainText('Deuteronomy 12:29-13:5', { timeout: 32_000 })
  await page.getByText('Add OT Survey RG3 Passages').click()
  await expect(page.locator('body')).toContainText('Song of songs 1:1-4', { timeout: 32_000 })
  await expect(page.locator('body')).toContainText('Song of songs 4:9-15', { timeout: 32_000 })
  await expect(page.locator('body')).toContainText('Song of songs 5:9-16', { timeout: 32_000 })
  await page.getByText('Add OT Survey RG4 Passages').click()
  await expect(page.locator('body')).toContainText('Isaiah 52:13-53:12', { timeout: 32_000 })
})

test('checkboxes are only shown when language chosen has books in each checkbox group respectively', async ({
  page
}) => {
  await page.goto('http://localhost:8001/passages')
  await page.getByLabel('Bahasa Malaysia zlm').check()
  await page.getByRole('button', { name: 'Next' }).click()
  // await expect(page.locator('body')).not.toContainText('Add OT Survey RG1 Passages')
  // await expect(page.locator('body')).not.toContainText('Add OT Survey RG2 Passages')
  // await expect(page.locator('body')).not.toContainText('Add OT Survey RG3 Passages')
  // await expect(page.locator('body')).not.toContainText('Add OT Survey RG4 Passages')
  await expect(page.locator('body')).toContainText("Add NT Survey Reviewers' Guide (RG) Passages", {
    timeout: 120_000
  })
  // await expect(page.locator('#stet-passages')).toContainText('Add STET Passages')
  await page.getByText("Add NT Survey Reviewers'").click()
  await expect(page.locator('body')).toContainText('Matius 2:1-12', { timeout: 32_000 })
  await expect(page.locator('body')).toContainText('Matius 3:13-17', { timeout: 32_000 })
  // await page.getByLabel('Add STET Passages').check()
  // await expect(page.locator('body')).toContainText('Matius 1:1', { timeout: 32_000 })
  await page.getByRole('link', { name: 'Language' }).click()
  await page.getByText('Français (French)').click()
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.locator('body')).toContainText(
    "Add all OT Survey Reviewers' Guide (RG) Passages",
    {
      timeout: 120_000
    }
  )
  await expect(page.locator('#add-ot-rg1-passages')).toContainText(
    'Add OT Survey RG1 Passages only (Genesis to Deuteronomy)',
    { timeout: 32_000 }
  )
  await expect(page.locator('#add-ot-rg2-passages')).toContainText(
    'Add OT Survey RG2 Passages only (Joshua to Esther)',
    { timeout: 32_000 }
  )
  await expect(page.locator('#add-ot-rg3-passages')).toContainText(
    'Add OT Survey RG3 Passages only (Job to Song of Songs)',
    { timeout: 32_000 }
  )
  await expect(page.locator('#add-ot-rg4-passages')).toContainText(
    'Add OT Survey RG4 Passages only (Isaiah to Malachi)',
    { timeout: 32_000 }
  )
  await expect(page.locator('#add-nt-passages')).toContainText(
    "Add NT Survey Reviewers' Guide (RG) Passages",
    {
      timeout: 32_000
    }
  )
  // await expect(page.locator('#stet-passages')).toContainText('Add STET Passages', {
  //   timeout: 32_000
  // })
})

test('language change changes passages chosen', async ({ page }) => {
  await page.goto('http://localhost:8001/passages')
  await page.getByText('English').click()
  await page.getByRole('button', { name: 'Heart' }).click()
  await page.getByText('Abé').click()
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByText("Add NT Survey Reviewers'").click()
  await page.getByRole('button', { name: 'Edit' }).click()
  await page.locator('.mt-2 > button').first().click()
  await page.getByText('English').click()
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByText("Add NT Survey Reviewers'").click()
  await expect(page.getByTestId('shown-passages')).toContainText('Matthew 2:1-12 (aba)')
  await expect(page.getByTestId('shown-passages')).toContainText('Matthew 2:1-12 (en)')
  await page.getByRole('button', { name: 'Edit' }).click()
  await page.locator('div:nth-child(4) > button').click()
  await expect(page.getByTestId('shown-passages')).not.toContainText('Matthew 2:1-12')
})

test('backtracking to language step without changing languages keeps passages', async ({
  page
}) => {
  await page.goto('http://localhost:8001/passages')
  await page.getByText('English').click()
  await page.getByRole('button', { name: 'Next' }).click()
  await page.getByText("Add NT Survey Reviewers'").click()
  await expect(page.getByTestId('shown-passages')).toContainText('Matthew 2:1-12 (en)')
  await page.getByRole('link', { name: 'Language' }).click()
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByTestId('shown-passages')).toContainText('Matthew 2:1-12 (en)')
})

// We do not provide STET passages checkbox in Passages app currently by request of PO
test.skip('stet passages not available in production', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'location', {
      value: {
        ...window.location,
        hostname: 'bibleineverylanguage.org'
      },
      configurable: true
    })
  })
  await page.goto('http://localhost:8001/passages')
  await page.getByText('Cebuano').click()
  await page.getByRole('button', { name: 'Next' }).click()
  await expect(page.locator('#stet-passages')).not.toBeVisible()
})

// We do not provide STET passages checkbox in Passages app currently by request of PO
test.skip('stet passages available when not in production', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'location', {
      value: {
        ...window.location,
        hostname: 'walink.org'
      },
      configurable: true
    })
  })
  await page.goto('http://localhost:8001/passages')
  await page.getByText('Cebuano').click()
  await page.getByRole('button', { name: 'Next' }).click()
  await page.waitForSelector('#stet-passages', { state: 'visible' })
  await expect(page.locator('#stet-passages')).toBeVisible()
})
