import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const out = path.resolve("..", "docs", "screenshots");

test("capture the farmer and lender screens", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(page.getByRole("button", { name: /2004/ })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await shot(page, "limits-390.png");
  await runYear(page, "2004");
  await scrub(page, "8");
  await shot(page, "farmer-mid-390.png");
  await scrub(page, "21");
  await expect(page.getByTestId("season-banner")).toContainText("30% lower");
  await expect(page.getByText("4,707.35")).toBeVisible();
  await shot(page, "farmer-2004-390.png");
  await page.getByRole("button", { name: "What does this chance mean?" }).click();
  await expect(page.getByTestId("ask-answer")).toBeVisible({ timeout: 20000 });
  await shot(page, "farmer-answer-390.png");
  await page.getByRole("button", { name: "See the public record" }).click();
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByTestId("verify-result")).toContainText("Match");
  await shot(page, "lender-verify-390.png");
  await page.getByRole("button", { name: "Audit note" }).click();
  await expect(page.getByTestId("audit-note")).toContainText("mm", { timeout: 20000 });
  await shot(page, "lender-audit-390.png");
  expect(await pageOverflow(page)).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("heading", { name: "26-season check" }).scrollIntoViewIfNeeded();
  await shot(page, "backtest-390.png");
  await page.getByRole("button", { name: "Farmer" }).click();
  await runYear(page, "2020");
  await scrub(page, "21");
  await expect(page.getByTestId("season-banner")).toContainText("No relief this season");
  await shot(page, "farmer-2020-390.png");
  expect(await pageOverflow(page)).toEqual([]);

  await page.setViewportSize({ width: 1280, height: 900 });
  await runYear(page, "2004");
  await scrub(page, "8");
  await expect(page.getByText("As of week 8")).toBeVisible();
  await shot(page, "farmer-mid-1280.png");
  await scrub(page, "21");
  await expect(page.getByTestId("season-banner")).toContainText("30% lower");
  await shot(page, "farmer-2004-1280.png");
  await page.getByRole("button", { name: "What does this chance mean?" }).click();
  await expect(page.getByTestId("ask-answer")).toBeVisible({ timeout: 20000 });
  await shot(page, "farmer-answer-1280.png");
  await page.getByRole("button", { name: "See the public record" }).click();
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByTestId("verify-result")).toContainText("Match");
  await shot(page, "lender-verify-1280.png");
  await page.getByRole("button", { name: "Audit note" }).click();
  await expect(page.getByTestId("audit-note")).toContainText("mm", { timeout: 20000 });
  await shot(page, "lender-audit-1280.png");
  await page.getByRole("heading", { name: "26-season check" }).scrollIntoViewIfNeeded();
  await shot(page, "backtest-1280.png");
  await shot(page, "limits-1280.png");
  await page.getByRole("button", { name: "Farmer" }).click();
  await runYear(page, "2020");
  await scrub(page, "21");
  await expect(page.getByTestId("season-banner")).toContainText("No relief this season");
  await shot(page, "farmer-2020-1280.png");
});

async function runYear(page: Page, year: string) {
  const replay = page.getByTestId("replay");
  const previousLoan = (await replay.count()) ? await replay.getAttribute("data-loan") : "";
  await page.getByRole("button", { name: new RegExp(year) }).click();
  await page.getByRole("button", { name: "Run this season" }).click();
  await expect(replay).toHaveAttribute("data-year", year, { timeout: 90000 });
  await expect(replay).not.toHaveAttribute("data-loan", previousLoan ?? "");
  await expect(page.getByRole("button", { name: "Run this season" })).toBeVisible();
  await expect(page.getByRole("slider", { name: "Week" })).toHaveValue("1");
}

async function scrub(page: Page, week: string) {
  const slider = page.getByRole("slider", { name: "Week" });
  await slider.fill(week);
  await expect(slider).toHaveValue(week);
  await expect(page.getByText(`As of week ${week}`)).toBeVisible();
}

async function pageOverflow(page: Page): Promise<string[]> {
  await page.setViewportSize({ width: 375, height: 812 });
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const found: string[] = [];
    for (const el of document.querySelectorAll("body *")) {
      let parent = el.parentElement;
      let insideScroll = false;
      while (parent) {
        const overflow = getComputedStyle(parent).overflowX;
        if (overflow === "auto" || overflow === "scroll") {
          insideScroll = true;
          break;
        }
        parent = parent.parentElement;
      }
      if (insideScroll) continue;
      const box = el.getBoundingClientRect();
      if (box.right > width + 2 && box.width > 8) found.push(`${el.tagName} ${(el.textContent || "").slice(0, 48)}`);
      if (found.length >= 6) break;
    }
    return found;
  });
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: path.join(out, name), fullPage: true });
}
