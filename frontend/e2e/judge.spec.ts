import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

test("play advances the week", async ({ page }) => {
  await openFarmer(page);
  await runYear(page, "2004");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(page.getByRole("slider", { name: "Week" })).not.toHaveValue("1", { timeout: 5000 });
  await page.getByRole("button", { name: "Pause" }).click();
});

test("the what-if slider asks for a preview and updates the result", async ({ page }) => {
  await openFarmer(page);
  await runYear(page, "2004");
  const slider = page.getByRole("slider", { name: "End-of-season rainfall" });
  await expect(slider).toHaveValue("1243.9");
  await expect(page.getByTestId("what-if")).toContainText("Your next 3 payments are 30% lower.");
  await slider.scrollIntoViewIfNeeded();
  const preview = page.waitForRequest((request) => request.url().includes("/api/schedule/preview"), { timeout: 15000 });
  await dragSlider(page, slider, 1243.9, 1100);
  await expect(slider).not.toHaveValue("1243.9");
  const request = await preview;
  expect(request.url()).toContain("/api/schedule/preview");
  await expect(page.getByTestId("what-if")).toContainText("Relief would apply");
  await expect(page.getByTestId("what-if")).toContainText("4,707.35");
});

test("Filipino changes the farmer copy", async ({ page }) => {
  await openFarmer(page);
  await page.getByRole("button", { name: "Filipino" }).click();
  await expect(page.getByRole("heading", { name: "Pumili ng season" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Magsasaka" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Patakbuhin ang season na ito/ })).toBeVisible();
});

test("the limits panel hides and opens again", async ({ page }) => {
  await openFarmer(page);
  await expect(page.getByText("This is a prototype and a simulation.")).toBeVisible();
  await page.getByRole("button", { name: "Hide how it works" }).click();
  const opener = page.getByRole("button", { name: "How this works and its limits" });
  await expect(opener).toBeVisible();
  await expect(page.getByText("This is a prototype and a simulation.")).toHaveCount(0);
  await opener.click();
  await expect(page.getByText("This is a prototype and a simulation.")).toBeVisible();
});

test("lender copy and verify", async ({ page }) => {
  await openFarmer(page);
  await runYear(page, "2004");
  await page.getByRole("button", { name: "See the public record" }).click();
  await expect(page.getByRole("heading", { name: "Current season status" })).toBeVisible();
  await page.getByRole("button", { name: "Copy" }).first().click();
  await expect(page.getByRole("button", { name: "Copied" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByTestId("verify-result")).toContainText("Match", { timeout: 20000 });
});

test("the farmer flow works from the keyboard", async ({ page }) => {
  await openFarmer(page);
  await focusByText(page, "2004");
  await page.keyboard.press("Enter");
  await focusByText(page, "Run this season");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("replay")).toHaveAttribute("data-year", "2004", { timeout: 90000 });
  await focusByLabel(page, "Week");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("slider", { name: "Week" })).toHaveValue("2");
  await expect(page.getByText("As of week 2")).toBeVisible();
  await focusByText(page, "Play");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("slider", { name: "Week" })).not.toHaveValue("2", { timeout: 5000 });
});

test("axe finds no serious issues at 390 and 1280", async ({ page }) => {
  await openFarmer(page);
  await runYear(page, "2004");
  await page.getByRole("slider", { name: "Week" }).fill("21");
  await expect(page.getByTestId("season-banner")).toContainText("30% lower");
  await page.getByRole("button", { name: "What does this chance mean?" }).click();
  await expect(page.getByTestId("ask-answer")).toBeVisible({ timeout: 20000 });
  const found = [];
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const results = await new AxeBuilder({ page }).analyze();
    for (const violation of results.violations) {
      found.push({
        width,
        view: "farmer-answer",
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        nodes: violation.nodes.slice(0, 3).map((node) => node.target.join(" ")),
      });
    }
  }
  await page.getByRole("button", { name: "See the public record" }).click();
  await page.getByRole("button", { name: "Audit note" }).click();
  await expect(page.getByTestId("audit-note")).toContainText("mm", { timeout: 20000 });
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    const results = await new AxeBuilder({ page }).analyze();
    for (const violation of results.violations) {
      found.push({
        width,
        view: "lender-audit",
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        nodes: violation.nodes.slice(0, 3).map((node) => node.target.join(" ")),
      });
    }
  }
  console.log(`AXE ${JSON.stringify(found)}`);
  expect(found).toEqual([]);
});

test("prefers-reduced-motion leaves no running animation", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openFarmer(page);
  await runYear(page, "2004");
  const running = await page.evaluate(() =>
    document.getAnimations().filter((animation) => {
      const duration = Number(animation.effect?.getComputedTiming().duration ?? 0);
      return duration > 50 && animation.playState === "running";
    }).length,
  );
  expect(running).toBe(0);
  const scroll = await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior);
  expect(scroll === "auto" || scroll === "").toBe(true);
});

async function openFarmer(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /2004/ })).toBeVisible();
}

async function runYear(page: Page, year: string) {
  const replay = page.getByTestId("replay");
  const previousLoan = (await replay.count()) ? await replay.getAttribute("data-loan") : "";
  await page.getByRole("button", { name: new RegExp(year) }).click();
  await page.getByRole("button", { name: "Run this season" }).click();
  await expect(replay).toHaveAttribute("data-year", year, { timeout: 90000 });
  await expect(replay).not.toHaveAttribute("data-loan", previousLoan ?? "");
}

async function focusByText(page: Page, text: string) {
  for (let step = 0; step < 40; step += 1) {
    const name = await page.evaluate(() => {
      const el = document.activeElement;
      if (!(el instanceof HTMLButtonElement)) return "";
      return (el.textContent ?? "").replace(/\s+/g, " ").trim();
    });
    if (name.includes(text)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`Tab did not reach ${text}`);
}

async function focusByLabel(page: Page, label: string) {
  for (let step = 0; step < 40; step += 1) {
    const name = await page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? "");
    if (name === label) return;
    await page.keyboard.press("Tab");
  }
  throw new Error(`Tab did not reach ${label}`);
}

async function dragSlider(page: Page, slider: ReturnType<Page["getByRole"]>, from: number, to: number) {
  await slider.scrollIntoViewIfNeeded();
  const box = await slider.boundingBox();
  if (!box) throw new Error("slider has no box");
  const xFor = (value: number) => box.x + 8 + ((value - 900) / (2200 - 900)) * (box.width - 16);
  const y = box.y + box.height / 2;
  await page.mouse.move(xFor(from), y);
  await page.mouse.down();
  await page.mouse.move(xFor(to), y, { steps: 20 });
  await page.mouse.up();
}
