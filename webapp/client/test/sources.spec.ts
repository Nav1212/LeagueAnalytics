import { test, expect } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import type { Meta, Source, ChampionRow, ChampionDetail } from "../src/api";

function metadata(source: Source = "riot", overlap = false): Meta {
  const patches = source === "riot" ? [{ patch: "16.10", matches: 100 }, { patch: "16.9", matches: 20 }] : [{ patch: overlap ? "16.10" : "16.8", matches: 50 }];
  return { source, sources: ["riot", "demo"], patches, latestPatch: patches[0]!.patch,
    totalMatches: patches.reduce((sum, p) => sum + p.matches, 0), championCount: 1,
    rawMatches: { riot: 120, demo: 50 }, ddragonVersion: "16.10.1", aggregatedAt: "2026-09-22",
    runId: "fixture", schemaVersion: 1 };
}
function championRow(source: Source, name = "Ahri"): ChampionRow {
  return { id: 1, key: "Ahri", name, role: "MIDDLE", games: 50, wins: source === "riot" ? 30 : 5,
    winRate: source === "riot" ? 60 : 10, pickRate: 50, banRate: 10, kda: { kills: 5, deaths: 2, assists: 8 }, avgGold: 10000, avgDamage: 20000, avgCs: 200 };
}
function detail(source: Source, patch: string, name = "Ahri"): ChampionDetail {
  return { source, patch, id: 1, key: "Ahri", name, title: "the Nine-Tailed Fox", tags: ["Mage"], banRate: 10,
    roles: [{ ...championRow(source), kdaRatio: 6.5, matchups: [], builds: { mostPopular: [], highestWin: [] }, spells: [], runes: [{ keystone: 9001, subStyle: 8000, games: 50, winRate: 60 }] }] };
}

async function mockApi(page: Page, options: { empty?: boolean; overlap?: boolean; runeFailure?: boolean; intercept?: (route: Route, url: URL) => Promise<boolean> } = {}) {
  const externalJson: string[] = [];
  page.on("request", request => {
    if (!request.url().startsWith("http://127.0.0.1:5174") && ["fetch", "xhr"].includes(request.resourceType())) externalJson.push(request.url());
  });
  await page.route("https://ddragon.leagueoflegends.com/**", route => route.abort());
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    if (await options.intercept?.(route, url)) return;
    const source = (url.searchParams.get("source") ?? "riot") as Source;
    const patch = url.searchParams.get("patch") ?? "16.10";
    if (url.pathname === "/api/meta") {
      const meta = metadata(source, options.overlap);
      if (options.empty) Object.assign(meta, { source: null, sources: [], patches: [], latestPatch: null, totalMatches: 0 });
      await route.fulfill({ json: meta });
    } else if (url.pathname === "/api/champions") {
      await route.fulfill({ json: { source, patch, rows: [championRow(source)] } });
    } else if (url.pathname.startsWith("/api/champion/")) {
      await route.fulfill({ json: detail(source, patch) });
    } else if (url.pathname === "/api/static/runes") {
      if (options.runeFailure) await route.fulfill({ status: 503, json: { error: "optional catalog unavailable" } });
      else await route.fulfill({ json: { version: "16.10.1", styles: [{ id: 8000, name: "Precision", icon: "style.png", slots: [{ runes: [{ id: 9001, name: "Published Rune", icon: "rune.png" }] }] }] } });
    } else await route.fulfill({ status: 404, json: { error: "unexpected test request" } });
  });
  return externalJson;
}

test("source selection changes statistics and resets an unavailable patch", async ({ page }) => {
  const externalJson = await mockApi(page);
  await page.goto("/");
  await expect(page.getByLabel("Source", { exact: true })).toHaveValue("riot");
  await expect(page.getByLabel("Patch", { exact: true })).toHaveValue("16.10");
  await expect(page.getByText("60.0%", { exact: true })).toBeVisible();
  const request = page.waitForRequest(r => r.url().includes("/api/champions?") && r.url().includes("source=demo"));
  await page.getByLabel("Source", { exact: true }).selectOption("demo");
  await request;
  await expect(page.getByLabel("Patch", { exact: true })).toHaveValue("16.8");
  await expect(page.getByText("10.0%", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("demo data", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /^Ahri(?: Ahri)?$/ }).click();
  await expect(page.getByText("Published Rune", { exact: true })).toBeVisible();
  expect(externalJson).toEqual([]);
});

test("source selection retains a patch that exists in the new source", async ({ page }) => {
  await mockApi(page, { overlap: true });
  await page.goto("/");
  await page.getByLabel("Source", { exact: true }).selectOption("demo");
  await expect(page.getByLabel("Source", { exact: true })).toHaveValue("demo");
  await expect(page.getByLabel("Patch", { exact: true })).toHaveValue("16.10");
});

test("an empty publication displays an empty state instead of an endless spinner", async ({ page }) => {
  await mockApi(page, { empty: true });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "No matches available" })).toBeVisible();
  await expect(page.getByLabel("Source", { exact: true })).toBeDisabled();
  await expect(page.getByLabel("Patch", { exact: true })).toBeDisabled();
});

test("an optional rune failure leaves statistics usable", async ({ page }) => {
  const externalJson = await mockApi(page, { runeFailure: true });
  await page.goto("/");
  await expect(page.getByRole("link", { name: /^Ahri(?: Ahri)?$/ })).toBeVisible();
  expect(externalJson).toEqual([]);
});

test("an incompatible optional rune catalog falls back without hiding statistics", async ({ page }) => {
  await mockApi(page, { intercept: async (route, url) => {
    if (url.pathname !== "/api/static/runes") return false;
    await route.fulfill({ json: { version: "16.10.1", styles: [{ id: 8000, slots: null }] } });
    return true;
  } });
  await page.goto("/");
  await expect(page.getByRole("link", { name: /^Ahri(?: Ahri)?$/ })).toBeVisible();
});

for (const pathname of ["/", "/champion/Ahri"]) {
  test(`late patch responses cannot replace current data on ${pathname}`, async ({ page }) => {
    let release!: () => void;
    let finished!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const fulfilled = new Promise<void>(resolve => { finished = resolve; });
    const endpoint = pathname === "/" ? "/api/champions" : "/api/champion/Ahri";
    await mockApi(page, { intercept: async (route, url) => {
      if (url.pathname !== endpoint || url.searchParams.get("patch") !== "16.9") return false;
      await gate;
      const json = pathname === "/" ? { source: "riot", patch: "16.9", rows: [championRow("riot", "Stale champion")] } : detail("riot", "16.9", "Stale champion");
      await route.fulfill({ json }).catch(() => {}); // The browser may already have cancelled it.
      finished();
      return true;
    } });
    await page.goto(pathname);
    const old = page.waitForRequest(r => new URL(r.url()).pathname === endpoint && r.url().includes("patch=16.9"));
    await page.getByLabel("Patch", { exact: true }).selectOption("16.9");
    await old;
    await page.getByLabel("Patch", { exact: true }).selectOption("16.10");
    const current = pathname === "/" ? page.getByRole("link", { name: /^Ahri(?: Ahri)?$/ }) : page.getByRole("heading", { name: "Ahri", exact: true });
    await expect(current).toBeVisible();
    release();
    await fulfilled;
    await page.waitForTimeout(100);
    await expect(page.getByText("Stale champion", { exact: true })).toHaveCount(0);
    await expect(current).toBeVisible();
  });
}
