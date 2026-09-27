import { expect, test, type Page } from "@playwright/test";

/** The five pitch moments from docs/BACKLOG.md §3, on the canonical Kitti case. */

const PASSWORD = "finsona-demo";
const CASE = "/cases/1";
// Slow enough to watch in the recording, fast in CI.
const beat = (page: Page) => page.waitForTimeout(process.env.E2E_SLOW ? 1200 : 150);

test.beforeAll(async ({ request }) => {
  const login = await request.post("/api/auth/login", { data: { username: "ca", password: PASSWORD } });
  expect(login.ok()).toBeTruthy();
  const { token } = await login.json();
  const reset = await request.post("/api/demo/reset", { headers: { Authorization: `Bearer ${token}` } });
  expect(reset.ok()).toBeTruthy();
});

test("demo run: pipeline → loops → lineage → sizing → judgement → memo → LOS", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  await test.step("login as CA via demo account", async () => {
    await page.goto("/login");
    await page.getByRole("button", { name: "เจ้าหน้าที่วิเคราะห์สินเชื่อ (CA)" }).click();
    await expect(page).toHaveURL("/");
    await page.getByText("บริษัท กิตติ อินทีเรีย ดีไซน์ จำกัด").click();
    await expect(page).toHaveURL(/\/cases\/1/);
  });

  await test.step("1 · pipeline ran on real PDFs", async () => {
    await expect(page.getByTestId("pipeline")).toBeVisible();
    await expect(page.getByTestId("pipeline")).toContainText("1,205");
    await beat(page);
  });

  await test.step("2 · loop graph shows the circular transfers", async () => {
    await page.getByTestId("open-loop-graph").click();
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
    expect(await page.locator(".react-flow__node").count()).toBeGreaterThan(1);
    await beat(page);
    await page.keyboard.press("Escape");
  });

  await test.step("3 · a number traces to a highlighted row on the PDF", async () => {
    await page.getByTestId("tab-tiers").click();
    await page.getByTestId("fig-T1_golden").click();
    await expect(page.getByText("ผลรวมตรงกับตัวเลขบนหน้าจอ")).toBeVisible();
    await page.getByTestId("lineage-row").first().click();
    await expect(page.getByTestId("bbox")).toBeVisible({ timeout: 30_000 });
    await beat(page);
    await page.getByRole("button", { name: "ปิด", exact: true }).click();
  });

  await test.step("4 · requested 5.0M fails DSCR, safe limit 3.5M passes", async () => {
    await page.getByTestId("tab-overview").click();
    await expect(page.getByTestId("sim-amount")).toHaveText("5,000,000");
    await expect(page.getByTestId("sim-dscr")).toHaveText("1.05×");
    await page.getByTestId("use-safe-limit").click();
    await expect(page.getByTestId("sim-amount")).toHaveText("3,500,000");
    await expect(page.getByTestId("sim-dscr")).toHaveText("1.35×");
    await expect(page.getByTestId("structure")).toContainText("3,500,000");
    await beat(page);
  });

  await test.step("5 · CA accepts the 450k watchlist item → safe limit rises to 4.14M", async () => {
    await page.getByTestId("tab-watchlist").click();
    await page.getByTestId("wl-item").filter({ hasText: "450,000" }).click();
    await page.locator("#reason").fill("ยืนยันกับ RM แล้วว่าเป็นลูกค้าประจำ มีใบสั่งซื้อประกอบ");
    await page.getByRole("button", { name: "Accept as Operating" }).click();
    await expect(page.getByTestId("wl-item").filter({ hasText: "450,000" })).toContainText("รับรอง");
    await page.getByTestId("tab-overview").click();
    await expect(page.getByTestId("use-safe-limit")).toContainText("4.14");
    await beat(page);
  });

  await test.step("memo: sign the structured approval and download the PDF", async () => {
    await page.getByTestId("tab-memo").click();
    await page.getByText("อนุมัติตามโครงสร้างวงเงินปลอดภัย").click();
    await page.getByPlaceholder(/เหตุผลประกอบการตัดสินใจ/).fill("กระแสเงินสดยืนยันด้วย PromptBiz เสนอวงเงินตามโครงสร้างปลอดภัย");
    await page.getByTestId("sign-memo").click();
    await expect(page.getByRole("button", { name: /ดาวน์โหลด Credit Memo/ })).toBeVisible();
    const token = await page.evaluate(() => JSON.parse(localStorage.getItem("finsona.session") ?? "{}").token);
    const pdf = await request.get(`/api/cases/1/memo/pdf`, { headers: { Authorization: `Bearer ${token}` } });
    expect(pdf.ok()).toBeTruthy();
    expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
    await page.getByTestId("los-submit").click();
    await expect(page.getByTestId("los-reference")).toContainText(/LOS-\d{4}-\d{6}/);
    await beat(page);
  });

  expect(errors, "uncaught page errors").toEqual([]);
});

test("audit chain intact after the demo run", async ({ request }) => {
  const { token } = await (await request.post("/api/auth/login", { data: { username: "auditor", password: PASSWORD } })).json();
  const v = await request.get("/api/audit/verify", { headers: { Authorization: `Bearer ${token}` } });
  expect((await v.json()).ok).toBe(true);
});

test("OCR review: a scanned statement's uncertain rows are checked against the image", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "เจ้าหน้าที่วิเคราะห์สินเชื่อ (CA)" }).click();
  await expect(page).toHaveURL("/");
  await page.goto("/cases/2");
  const banner = page.getByTestId("ocr-banner");
  await expect(banner).toBeVisible();
  const before = Number((await page.getByTestId("tab-ocr").innerText()).match(/\d+/)![0]);
  await banner.click();
  await expect(page.getByTestId("bbox")).toBeVisible({ timeout: 30_000 });

  // correct the first row (value typed as a CA would after reading the scan)
  const credit = page.getByTestId("ocr-credit");
  const read = await credit.inputValue();
  await credit.fill((Number(read) + 0.6).toFixed(2));
  await page.getByPlaceholder(/เหตุผลการแก้ไข/).fill("ภาพสแกนแสดงตัวเลขชัดเจน OCR อ่านผิดหนึ่งหลัก");
  await page.getByTestId("ocr-correct").click();
  await expect(page.getByTestId("tab-ocr")).toContainText(String(before - 1));

  // confirm the next one as read
  await page.getByTestId("ocr-confirm").click();
  await expect(page.getByTestId("tab-ocr")).toContainText(String(before - 2));
  await page.getByTestId("tab-audit").click();
  await expect(page.getByText("ตรวจทาน OCR").first()).toBeVisible();
});
