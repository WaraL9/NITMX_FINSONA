import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

/** The five pitch moments from docs/BACKLOG.md §3, on the canonical Kitti case. */

const PASSWORD = "finsona-demo";
const CASE = "/cases/1";
// Slow enough to watch in the recording, fast in CI.
const beat = (page: Page) => page.waitForTimeout(process.env.E2E_SLOW ? 1200 : 150);

async function resetDemo(request: import("@playwright/test").APIRequestContext) {
  const login = await request.post("/api/auth/login", { data: { username: "ca", password: PASSWORD } });
  expect(login.ok()).toBeTruthy();
  const { token } = await login.json();
  const reset = await request.post("/api/demo/reset", { headers: { Authorization: `Bearer ${token}` } });
  expect(reset.ok()).toBeTruthy();
}

test.beforeAll(async ({ request }) => resetDemo(request));

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
    // E8-12: side by side — evidence alone vs after the CA's decision
    await page.getByTestId("scenario-comparison").scrollIntoViewIfNeeded();
    await expect(page.getByTestId("cmp-safe-engine_only")).toContainText("3,500,000");
    await expect(page.getByTestId("cmp-safe-decided")).toContainText("4,140,000");
    await expect(page.getByTestId("cmp-safe-decided")).toContainText("+640,000");
    await expect(page.getByTestId("cmp-dscr-request")).toHaveText("1.18×"); // 5.0M still fails 1.25 on the higher cash flow
    await expect(page.getByTestId("cmp-dscr-request")).toHaveClass(/text-risk/);
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

test("e-Tax invoice: an uploaded ETDA XML verifies a receipt as Tier 1", async ({ page, request }) => {
  await resetDemo(request); // the demo run above signed case 1
  const xml = path.join(__dirname, "..", "data", "generated", "kitti", "etax", "etax_ETX-2512-0001.xml");
  await page.goto("/login");
  await page.getByRole("button", { name: "เจ้าหน้าที่วิเคราะห์สินเชื่อ (CA)" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`${CASE}?tab=documents`);
  await page.locator('input[type="file"]').setInputFiles(xml);
  await expect(page.getByText("ใบกำกับภาษีเลขที่ ETX-2512-0001")).toBeVisible();
  const row = page.getByTestId("etax-row");
  await expect(row).toContainText("รอวิเคราะห์ใหม่");
  await page.getByTestId("run-analysis").click();
  // E0-07: the analysis runs as a job; every stage reports in the live strip.
  await expect(page.getByTestId("job-count")).toHaveText("8/8", { timeout: 30_000 });
  await expect(row).toContainText("→ ระดับ 1", { timeout: 30_000 });
  await expect(row).toContainText("XML (ETDA)");
});

test("utility bill photo: OCR-uncertain amount is held until a CA confirms it", async ({ page, request }) => {
  await resetDemo(request);
  const photo = path.join(__dirname, "..", "data", "generated", "kitti", "bills", "bill_water_2026-04.jpg");
  await page.goto("/login");
  await page.getByRole("button", { name: "เจ้าหน้าที่วิเคราะห์สินเชื่อ (CA)" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`${CASE}?tab=documents`);
  await page.locator('input[type="file"]').setInputFiles(photo);
  await expect(page.getByText(/บิลงวด 2026-04 .*รอเจ้าหน้าที่ตรวจทาน/)).toBeVisible();
  const row = page.getByTestId("bill-row");
  await page.getByTestId("run-analysis").click();
  await expect(row).toContainText("รอตรวจทาน OCR", { timeout: 30_000 });
  await page.getByTestId("bill-review").click();
  await page.getByPlaceholder(/เหตุผล \(อย่างน้อย 10 ตัวอักษร\)/).fill("ตรวจภาพถ่ายแล้ว ยอดเงินชัดเจนตรงกับที่อ่านได้");
  await page.getByTestId("bill-review-submit").click();
  await expect(row).toContainText("ตรงกับข้อมูลผู้ให้บริการ", { timeout: 30_000 });
  await expect(row).toContainText("CA ยืนยันแล้ว");
  await page.getByTestId("tab-audit").click();
  await expect(page.getByText("ตรวจทานบิล (OCR)").first()).toBeVisible();
});

test("dStatement: the bank's own record confirms an uploaded statement PDF", async ({ page, request }) => {
  await resetDemo(request);
  await page.goto("/login");
  await page.getByRole("button", { name: "เจ้าหน้าที่วิเคราะห์สินเชื่อ (CA)" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`${CASE}?tab=documents`);
  await page.getByTestId("dstatement-open").click();
  await page.getByTestId("dstatement-submit").click();
  await expect(page.getByText(/ตรงกับธนาคารทั้ง 581 รายการ/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("bank-source")).toContainText("ไฟล์ที่อัปโหลดตรงกับธนาคาร 581/581");
  await page.getByTestId("tab-audit").click();
  await expect(page.getByText("ดึงสเตทเมนต์จากธนาคาร (dStatement)").first()).toBeVisible();
});

test("Thai / English toggle: the whole UI switches and the choice persists", async ({ page, request }) => {
  await resetDemo(request);
  await page.goto("/login");
  await page.getByTestId("lang-en").click();
  await expect(page.getByText("Sign in to Finsona AI")).toBeVisible();
  await page.getByRole("button", { name: "Credit analyst (CA)" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("link", { name: "Loan cases" })).toBeVisible();
  await page.goto(CASE);
  await expect(page.getByTestId("tab-overview")).toHaveText(/Overview & cash flow/);
  await expect(page.getByTestId("use-safe-limit")).toContainText("Use safe limit");
  await expect(page.getByText("Scenario comparison")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("tab-tiers")).toHaveText(/3-way reconciliation/);
  expect(await page.evaluate(() => document.documentElement.lang)).toBe("en");
  // Figures are identical in both languages — only the words change.
  await expect(page.getByTestId("sim-dscr")).toHaveText("1.05×");
  await page.getByTestId("lang-th").click();
  await expect(page.getByTestId("tab-overview")).toHaveText(/ภาพรวม & กระแสเงินสด/);
});

test("Watchlist evidence hint: the suggested question goes to the RM in one click", async ({ page, request }) => {
  await resetDemo(request);
  await page.goto("/login");
  await page.getByRole("button", { name: "เจ้าหน้าที่วิเคราะห์สินเชื่อ (CA)" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`${CASE}?tab=watchlist`);
  await page.getByTestId("wl-item").filter({ hasText: "700,000" }).click();
  const hint = page.getByTestId("evidence-hint");
  await expect(hint).toContainText("เงินสด");
  await expect(hint).toContainText("700,000.00 บาท"); // amount filled in by the engine, not written by the AI
  await page.getByTestId("use-hint-question").click();
  await expect(page.locator("#reason")).toHaveValue(/700,000\.00 บาท/);
  await page.getByRole("button", { name: "Query RM" }).click();
  await expect(page.getByTestId("wl-item").filter({ hasText: "700,000" })).toContainText("ส่งคำถามให้ RM แล้ว");
});

test("Lease ending before the loan caps the tenor (E6-06)", async ({ page, request }) => {
  await resetDemo(request);
  const receipt = path.join(__dirname, "..", "data", "generated", "kitti", "bills", "receipt_rent_2026-05.pdf");
  await page.goto("/login");
  await page.getByRole("button", { name: "เจ้าหน้าที่วิเคราะห์สินเชื่อ (CA)" }).click();
  await expect(page).toHaveURL("/");
  await page.goto(`${CASE}?tab=documents`);
  await page.locator('input[type="file"]').setInputFiles(receipt);
  await expect(page.getByTestId("bill-row")).toBeVisible();
  await page.getByTestId("run-analysis").click();
  await expect(page.getByTestId("job-count")).toHaveText("8/8", { timeout: 30_000 });
  await page.getByTestId("tab-overview").click();
  await expect(page.getByTestId("tenor-cap")).toContainText("8");
  await page.getByTestId("use-safe-limit").click();
  await expect(page.getByTestId("sim-amount")).not.toHaveText("3,500,000"); // a shorter term carries less
});
