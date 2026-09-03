/**
 * Read-only access to the SQLite database produced by the Python processor.
 * Uses node:sqlite (built into Node 22.13+/24) — no native dependencies.
 */
import { DatabaseSync } from "node:sqlite";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
export const DB_PATH = process.env.CHAMPIONGG_DB ?? path.join(REPO_ROOT, "data", "champions.db");

export interface ChampionInfo {
  id: number;
  key: string; // ddragon id, e.g. "MonkeyKing"
  name: string; // display name, e.g. "Wukong"
  title: string;
  tags: string[];
}

export interface ChampionRoleRow {
  id: number;
  key: string;
  name: string;
  role: string;
  games: number;
  wins: number;
  winRate: number;
  pickRate: number;
  banRate: number;
  kda: { kills: number; deaths: number; assists: number };
  avgGold: number;
  avgDamage: number;
  avgCs: number;
}

let db: DatabaseSync | null = null;

export function getDb(): DatabaseSync {
  if (!db) {
    if (!existsSync(DB_PATH)) {
      throw new Error(
        `Database not found at ${DB_PATH}. Run the processor first: python -m processor.main seed`,
      );
    }
    db = new DatabaseSync(DB_PATH, { readOnly: true });
  }
  return db;
}

// ---------------------------------------------------------------- helpers
const r1 = (n: number) => Math.round(n * 10) / 10;
const r2 = (n: number) => Math.round(n * 100) / 100;
const pct = (n: number) => Math.round(n * 1000) / 10; // 0.5321 -> 53.2

function rowToChampionInfo(row: Record<string, unknown>): ChampionInfo {
  return {
    id: Number(row.champion_id),
    key: String(row.key),
    name: String(row.name),
    title: String(row.title),
    tags: JSON.parse(String(row.tags)) as string[],
  };
}

// ------------------------------------------------------------------ queries
export function getMeta() {
  const d = getDb();
  const patches = d
    .prepare("SELECT patch, matches FROM patch_totals ORDER BY patch DESC")
    .all() as { patch: string; matches: number }[];
  const meta = Object.fromEntries(
    (d.prepare("SELECT key, value FROM meta").all() as { key: string; value: string }[]).map(
      (m) => [m.key, m.value],
    ),
  );
  const championCount = (
    d.prepare("SELECT COUNT(*) AS n FROM champions").get() as { n: number }
  ).n;
  const rawCounts = d
    .prepare("SELECT source, COUNT(*) AS n FROM raw_matches GROUP BY source")
    .all() as { source: string; n: number }[];
  return {
    patches,
    latestPatch: patches[0]?.patch ?? null,
    totalMatches: patches.reduce((s, p) => s + p.matches, 0),
    championCount,
    rawMatches: Object.fromEntries(rawCounts.map((r) => [r.source, r.n])),
    ddragonVersion: meta.ddragon_version ?? null,
    aggregatedAt: meta.aggregated_at ?? null,
  };
}

export function getPatchTotal(patch: string): number {
  const row = getDb()
    .prepare("SELECT matches FROM patch_totals WHERE patch = ?")
    .get(patch) as { matches: number } | undefined;
  return row?.matches ?? 0;
}

export function getChampionRows(patch: string): ChampionRoleRow[] {
  const d = getDb();
  const patchMatches = getPatchTotal(patch);
  if (patchMatches === 0) return [];
  // Require ~0.8% pick rate before a champion/role qualifies for the table,
  // so tiny samples don't produce absurd win rates.
  const MIN_GAMES = Math.max(10, Math.round(patchMatches * 0.008));
  const rows = d
    .prepare(
      `SELECT s.*, c.key, c.name, COALESCE(b.bans, 0) AS bans
       FROM champion_stats s
       JOIN champions c ON c.champion_id = s.champion_id
       LEFT JOIN champion_bans b ON b.patch = s.patch AND b.champion_id = s.champion_id
       WHERE s.patch = ? AND s.games >= ?
       ORDER BY c.name, s.games DESC`,
    )
    .all(patch, MIN_GAMES) as Record<string, number & string>[];
  return rows.map((r) => ({
    id: Number(r.champion_id),
    key: String(r.key),
    name: String(r.name),
    role: String(r.role),
    games: Number(r.games),
    wins: Number(r.wins),
    winRate: pct(Number(r.wins) / Number(r.games)),
    pickRate: pct(Number(r.games) / patchMatches),
    banRate: pct(Number(r.bans) / patchMatches),
    kda: {
      kills: r1(Number(r.kills) / Number(r.games)),
      deaths: r1(Number(r.deaths) / Number(r.games)),
      assists: r1(Number(r.assists) / Number(r.games)),
    },
    avgGold: Math.round(Number(r.gold) / Number(r.games)),
    avgDamage: Math.round(Number(r.damage) / Number(r.games)),
    avgCs: r1(Number(r.cs) / Number(r.games)),
  }));
}

export function findChampion(key: string): ChampionInfo | null {
  const row = getDb()
    .prepare("SELECT * FROM champions WHERE key = ? COLLATE NOCASE OR name = ? COLLATE NOCASE")
    .get(key, key) as Record<string, unknown> | undefined;
  return row ? rowToChampionInfo(row) : null;
}

export function getChampionDetail(key: string, patch: string) {
  const d = getDb();
  const champ = findChampion(key);
  if (!champ) return null;
  const patchMatches = getPatchTotal(patch);
  const bans = (
    d
      .prepare("SELECT bans FROM champion_bans WHERE patch = ? AND champion_id = ?")
      .get(patch, champ.id) as { bans: number } | undefined
  )?.bans ?? 0;

  const statRows = d
    .prepare("SELECT * FROM champion_stats WHERE patch = ? AND champion_id = ? ORDER BY games DESC")
    .all(patch, champ.id) as Record<string, number>[];

  const roles = statRows.map((s) => {
    const role = String(s.role);
    const games = Number(s.games);
    const matchups = (
      d
        .prepare(
          `SELECT m.opponent_id, m.games, m.wins, c.key, c.name
           FROM matchups m JOIN champions c ON c.champion_id = m.opponent_id
           WHERE m.patch = ? AND m.champion_id = ? AND m.role = ? AND m.games >= 3
           ORDER BY m.games DESC`,
        )
        .all(patch, champ.id, role) as Record<string, number & string>[]
    ).map((m) => ({
      id: Number(m.opponent_id),
      key: String(m.key),
      name: String(m.name),
      games: Number(m.games),
      winRate: pct(Number(m.wins) / Number(m.games)),
    }));

    const buildRows = d
      .prepare(
        `SELECT items, games, wins FROM builds
         WHERE patch = ? AND champion_id = ? AND role = ? AND games >= 3
         ORDER BY games DESC LIMIT 40`,
      )
      .all(patch, champ.id, role) as { items: string; games: number; wins: number }[];
    const builds = buildRows.map((b) => ({
      items: JSON.parse(b.items) as number[],
      games: b.games,
      winRate: pct(b.wins / b.games),
    }));

    const spells = (
      d
        .prepare(
          `SELECT spells, games, wins FROM spell_sets
           WHERE patch = ? AND champion_id = ? AND role = ?
           ORDER BY games DESC LIMIT 3`,
        )
        .all(patch, champ.id, role) as { spells: string; games: number; wins: number }[]
    ).map((s2) => ({
      spells: JSON.parse(s2.spells) as number[],
      games: s2.games,
      winRate: pct(s2.wins / s2.games),
    }));

    const runes = (
      d
        .prepare(
          `SELECT keystone, sub_style, games, wins FROM rune_sets
           WHERE patch = ? AND champion_id = ? AND role = ?
           ORDER BY games DESC LIMIT 3`,
        )
        .all(patch, champ.id, role) as Record<string, number>[]
    ).map((r) => ({
      keystone: Number(r.keystone),
      subStyle: Number(r.sub_style),
      games: Number(r.games),
      winRate: pct(Number(r.wins) / Number(r.games)),
    }));

    return {
      role,
      games,
      winRate: pct(Number(s.wins) / games),
      pickRate: patchMatches ? pct(games / patchMatches) : 0,
      kda: {
        kills: r1(Number(s.kills) / games),
        deaths: r1(Number(s.deaths) / games),
        assists: r1(Number(s.assists) / games),
      },
      kdaRatio: r2((Number(s.kills) + Number(s.assists)) / Math.max(1, Number(s.deaths))),
      avgGold: Math.round(Number(s.gold) / games),
      avgDamage: Math.round(Number(s.damage) / games),
      avgCs: r1(Number(s.cs) / games),
      matchups,
      builds: {
        mostPopular: builds.slice(0, 5),
        highestWin: [...builds].sort((a, b) => b.winRate - a.winRate).slice(0, 5),
      },
      spells,
      runes,
    };
  });

  return {
    ...champ,
    patch,
    banRate: patchMatches ? pct(bans / patchMatches) : 0,
    roles,
  };
}

export function searchChampions(q: string): ChampionInfo[] {
  const rows = getDb()
    .prepare(
      "SELECT * FROM champions WHERE name LIKE ? COLLATE NOCASE OR key LIKE ? COLLATE NOCASE ORDER BY name LIMIT 10",
    )
    .all(`%${q}%`, `%${q}%`) as Record<string, unknown>[];
  return rows.map(rowToChampionInfo);
}
