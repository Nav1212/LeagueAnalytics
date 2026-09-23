import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { openGoldDatabase } from "../src/snapshots.ts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const venvPython = path.join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const python = process.env.PYTHON ?? (existsSync(venvPython) ? venvPython : "python");

function publish(directory: string, runId: string, mode = "normal", revision = 1) {
  const result = spawnSync(python, ["-m", "processor.test_fixtures", directory, runId, "--mode", mode, "--revision", String(revision)], { cwd: root, encoding: "utf8", timeout: 30000, windowsHide: true });
  assert.equal(result.status, 0, result.stderr || String(result.error));
}

async function fixture(mode: string, run: (f: { directory: string; get: (url: string, status?: number) => Promise<any> }) => Promise<void>) {
  const directory = mkdtempSync(path.join(os.tmpdir(), "championgg-api-"));
  if (mode !== "missing") publish(directory, "initial", mode);
  const child = spawn(process.execPath, [path.join(root, "webapp/server/src/index.ts")], {
    cwd: root, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PORT: "0", CHAMPIONGG_GOLD_DIR: directory, CHAMPIONGG_DB: path.join(directory, "must-never-be-opened.db") },
  });
  let logs = "";
  child.stderr.on("data", chunk => { logs += chunk; });
  try {
    const origin = await new Promise<string>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Server startup timed out: ${logs}`)), 10000);
      child.on("error", error => { clearTimeout(timer); reject(error); });
      child.on("exit", () => { clearTimeout(timer); reject(new Error(`Server exited: ${logs}`)); });
      child.stdout.on("data", chunk => {
        logs += chunk;
        const match = logs.match(/server on (http:\/\/localhost:\d+)/);
        if (match) { clearTimeout(timer); resolve(match[1]!); }
      });
    });
    const get = async (url: string, status = 200) => {
      const response = await fetch(origin + url, { signal: AbortSignal.timeout(5000) });
      assert.equal(response.status, status, `${url}: ${logs}`);
      if (url === "/") return response.text();
      assert.match(response.headers.get("content-type") ?? "", /application\/json/);
      return response.json();
    };
    await run({ directory, get });
    assert.equal(existsSync(path.join(directory, "must-never-be-opened.db")), false);
  } finally {
    if (child.exitCode === null && child.signalCode === null) {
      const exited = once(child, "exit");
      child.kill("SIGTERM");
      const timer = setTimeout(() => child.kill("SIGKILL"), 3000);
      try { await exited; } finally { clearTimeout(timer); }
    }
    rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}

test("GET /api/meta exposes only public metadata and separates source totals", async () => {
  await fixture("normal", async ({ get }) => {
    const meta = await get("/api/meta");
    assert.equal(meta.source, "riot");
    assert.deepEqual(meta.sources, ["riot", "demo"]);
    assert.deepEqual(meta.patches, [{ patch: "16.10", matches: 2000 }, { patch: "16.9", matches: 100 }]);
    assert.equal(meta.latestPatch, "16.10");
    assert.equal(meta.totalMatches, 2100);
    assert.equal(meta.championCount, 17);
    assert.deepEqual(meta.rawMatches, { demo: 500, riot: 2500 });
    assert.equal(meta.ddragonVersion, "16.10.1");
    assert.equal(meta.runId, "initial");
    assert.equal(meta.schemaVersion, 1);
    assert.ok(Number.isFinite(Date.parse(meta.aggregatedAt)));
    assert.ok(!JSON.stringify(meta).includes("PRIVATE_PATH"));
    const demo = await get("/api/meta?source=demo");
    assert.equal(demo.totalMatches, 150);
    assert.deepEqual(demo.patches.map((p: any) => p.patch), ["16.10", "16.8"]);
  });
});

test("GET /api/champions applies patch, source, sample thresholds and formulas", async () => {
  await fixture("normal", async ({ get }) => {
    const { source, patch, rows } = await get("/api/champions");
    assert.equal(source, "riot"); assert.equal(patch, "16.10");
    assert.deepEqual(rows.map((r: any) => r.name), ["Ahri", "Wukong"]);
    assert.deepEqual(rows[0], { id: 1, key: "Ahri", name: "Ahri", role: "MIDDLE", games: 100, wins: 60,
      winRate: 60, pickRate: 5, banRate: 10, kda: { kills: 10, deaths: 2, assists: 8 },
      avgGold: 12345, avgDamage: 23457, avgCs: 220.5 });
    const older = await get("/api/champions?patch=16.9");
    assert.deepEqual(older.rows.map((r: any) => r.name), ["Annie"]);
    const demo = await get("/api/champions?source=demo&patch=16.10");
    assert.equal(demo.rows[0].winRate, 10);
    assert.equal(demo.rows[0].pickRate, 50);
    assert.equal(demo.rows[0].banRate, 90);
    assert.deepEqual((await get("/api/champions?patch=unknown")).rows, []);
  });
});

test("GET /api/champion/:key scopes nested data, limits results and handles missing champions", async () => {
  await fixture("normal", async ({ get }) => {
    const champion = await get("/api/champion/aHrI");
    assert.equal(champion.name, "Ahri"); assert.equal(champion.source, "riot");
    assert.deepEqual(champion.tags, ["Mage"]);
    assert.equal(champion.banRate, 10);
    const role = champion.roles[0];
    assert.equal(role.winRate, 60); assert.equal(role.pickRate, 5); assert.equal(role.kdaRatio, 9);
    assert.deepEqual(role.matchups, [{ id: 2, key: "MonkeyKing", name: "Wukong", games: 10, winRate: 80 }]);
    assert.equal(role.builds.mostPopular.length, 5); assert.equal(role.builds.highestWin.length, 5);
    assert.deepEqual(role.builds.mostPopular[0].items, [1000]);
    assert.ok(role.builds.highestWin.every((b: any) => !b.items.includes(9999) && !b.items.includes(9998)));
    assert.equal(role.spells.length, 3); assert.equal(role.runes.length, 3);
    assert.deepEqual(role.spells[0].spells, [4, 10]); assert.equal(role.runes[0].subStyle, 8400);
    const demo = (await get("/api/champion/Ahri?source=demo&patch=16.10")).roles[0];
    assert.equal(demo.matchups[0].winRate, 10);
    assert.deepEqual(demo.builds.mostPopular[0].items, [2000]);
    assert.deepEqual(demo.spells[0].spells, [4, 14]); assert.equal(demo.runes[0].keystone, 9001);
    assert.equal((await get("/api/champion/wUKONG")).key, "MonkeyKing");
    assert.deepEqual((await get("/api/champion/Ahri?patch=unknown")).roles, []);
    assert.deepEqual(await get("/api/champion/unknown", 404), { error: "unknown champion: unknown" });
  });
});

test("GET /api/search trims, matches names and keys, orders and limits", async () => {
  await fixture("normal", async ({ get }) => {
    assert.equal((await get("/api/search?q=%20aHr%20"))[0].name, "Ahri");
    assert.equal((await get("/api/search?q=monkey"))[0].name, "Wukong");
    assert.equal((await get("/api/search?q=wuk"))[0].key, "MonkeyKing");
    assert.deepEqual(await get("/api/search?q=%20"), []);
    assert.deepEqual(await get("/api/search"), []);
    assert.deepEqual(await get("/api/search?q=unmatched"), []);
    const rows = await get("/api/search?q=test");
    assert.deepEqual(rows.map((r: any) => r.name), Array.from({ length: 10 }, (_, i) => `Test ${String(i).padStart(2, "0")}`));
  });
});

test("GET /api/static/runes reads the exact English version from Gold", async () => {
  await fixture("normal", async ({ get }) => {
    const catalog = await get("/api/static/runes");
    assert.equal(catalog.version, "16.10.1");
    assert.equal(catalog.styles[0].name, "Precision");
    assert.equal(catalog.styles[0].slots[0].runes[0].name, "Published Rune");
    assert.equal(catalog.styles[0].slots[0].runes[0].icon, "perk-images/Styles/Test.png");
    const old = await get("/api/static/runes?version=16.9.1");
    assert.equal(old.styles[0].slots[0].runes[0].name, "Older Rune");
    assert.deepEqual(await get("/api/static/runes?version=unknown"), { version: "unknown", styles: [] });
  });
});

test("GET / serves the frontend or API landing response", async () => {
  await fixture("normal", async ({ get }) => assert.match(await get("/"), /<!doctype html>|API is running/i));
});

test("valid empty publication and demo-only defaults", async () => {
  await fixture("empty", async ({ get, directory }) => {
    const meta = await get("/api/meta");
    assert.equal(meta.source, null); assert.deepEqual(meta.sources, []);
    assert.equal(meta.totalMatches, 0); assert.equal(meta.latestPatch, null);
    assert.deepEqual((await get("/api/champions")).rows, []);
    assert.deepEqual(await get("/api/static/runes"), { version: null, styles: [] });
    publish(directory, "demo-only", "demo");
    assert.equal((await get("/api/meta")).source, "demo");
    assert.deepEqual((await get("/api/meta?source=riot")).patches, []);
    assert.deepEqual((await get("/api/champions?source=riot")).rows, []);
    assert.deepEqual((await get("/api/champion/Ahri?source=riot")).roles, []);
  });
});

test("invalid sources are JSON 400; unavailable Gold is JSON 503 and recovers", async () => {
  await fixture("missing", async ({ get, directory }) => {
    for (const endpoint of ["/api/meta", "/api/champions", "/api/champion/Ahri"]) {
      assert.match((await get(`${endpoint}?source=bad`, 400)).error, /source/);
      await get(`${endpoint}?source=riot&source=demo`, 400);
    }
    for (const endpoint of ["/api/meta", "/api/champions", "/api/champion/Ahri", "/api/search", "/api/static/runes"]) {
      assert.match((await get(endpoint, 503)).error, /Gold/);
    }
    publish(directory, "recovered");
    assert.equal((await get("/api/meta")).runId, "recovered");
  });
});

test("unexpected errors are JSON 500", async () => {
  await fixture("bad-json", async ({ get }) => assert.deepEqual(await get("/api/search?q=ahri", 500), { error: "internal error" }));
});

test("publication failures retain current data; new snapshots are adopted without restart", async () => {
  await fixture("normal", async ({ get, directory }) => {
    assert.equal((await get("/api/champion/Ahri")).roles[0].winRate, 60);
    const failed = spawnSync(python, ["-m", "processor.test_fixtures", directory, "failed", "--mode", "broken"], { cwd: root, encoding: "utf8", windowsHide: true });
    assert.notEqual(failed.status, 0);
    assert.equal((await get("/api/meta")).runId, "initial");
    const manifest = readFileSync(path.join(directory, "current.json"), "utf8");
    writeFileSync(path.join(directory, "current.json"), '{"schemaVersion":99}');
    assert.equal((await get("/api/meta")).runId, "initial");
    writeFileSync(path.join(directory, "current.json"), manifest);
    publish(directory, "updated", "normal", 2);
    assert.equal((await get("/api/champion/Ahri")).roles[0].winRate, 70);
    assert.equal((await get("/api/meta")).runId, "updated");
  });
});

test("the production database connection rejects DML and DDL", async () => {
  await fixture("normal", async ({ directory }) => {
    const { snapshot } = JSON.parse(readFileSync(path.join(directory, "current.json"), "utf8"));
    const connection = openGoldDatabase(path.join(directory, snapshot));
    try {
      assert.throws(() => connection.exec("DELETE FROM gold_champions"), /readonly/i);
      assert.throws(() => connection.exec("CREATE TABLE forbidden(id INTEGER)"), /readonly/i);
      assert.throws(() => connection.prepare("SELECT * FROM bronze_matches").all(), /no such table/i);
    } finally { connection.close(); }
  });
});
