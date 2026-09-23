/** Queries over one immutable Gold snapshot. Every statistic is source-scoped. */
import type { DatabaseSync } from "node:sqlite";
export type Source = "riot" | "demo";

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

export function createRepository(d: DatabaseSync) {
  // ------------------------------------------------------------------ queries
  function getMeta(requestedSource?: Source) {
    const sources = (d.prepare("SELECT DISTINCT source FROM gold_patch_totals WHERE matches > 0 AND source IN ('riot','demo') ORDER BY CASE source WHEN 'riot' THEN 0 ELSE 1 END").all() as { source: Source }[]).map(r => r.source);
    const source = requestedSource ?? sources[0] ?? null;
    const patches = d.prepare("SELECT patch, matches FROM gold_patch_totals WHERE source = ?").all(source ?? "") as { patch: string; matches: number }[];
    patches.sort((a, b) => b.patch.localeCompare(a.patch, "en", { numeric: true }));
    const meta = Object.fromEntries((d.prepare("SELECT key, value FROM gold_meta").all() as { key: string; value: string }[]).map(m => [m.key, m.value]));
    const championCount = (d.prepare("SELECT COUNT(*) AS n FROM gold_champions").get() as { n: number }).n;
    const rawCounts = d.prepare("SELECT source, raw_matches AS n FROM gold_source_counts").all() as { source: string; n: number }[];
    return {
      source, sources, patches, latestPatch: patches[0]?.patch ?? null,
      totalMatches: patches.reduce((sum, p) => sum + p.matches, 0), championCount,
      rawMatches: Object.fromEntries(rawCounts.map(r => [r.source, r.n])),
      ddragonVersion: meta.ddragon_version ?? null, aggregatedAt: meta.aggregated_at ?? null,
      runId: meta.run_id, schemaVersion: Number(meta.schema_version),
    };
  }

  function getPatchTotal(patch: string, source: Source | null): number {
    const row = d
      .prepare("SELECT matches FROM gold_patch_totals WHERE source = ? AND patch = ?")
      .get(source ?? "", patch) as { matches: number } | undefined;
    return row?.matches ?? 0;
  }

  function getChampionRows(patch: string, source: Source | null): ChampionRoleRow[] {
    const patchMatches = getPatchTotal(patch, source);
    if (patchMatches === 0) return [];
    // Require ~0.8% pick rate before a champion/role qualifies for the table,
    // so tiny samples don't produce absurd win rates.
    const MIN_GAMES = Math.max(10, Math.round(patchMatches * 0.008));
    const rows = d
      .prepare(
        `SELECT s.*, c.key, c.name, COALESCE(b.bans, 0) AS bans
         FROM gold_champion_stats s
         JOIN gold_champions c ON c.champion_id = s.champion_id
         LEFT JOIN gold_champion_bans b ON b.source = s.source AND b.patch = s.patch AND b.champion_id = s.champion_id
         WHERE s.source = ? AND s.patch = ? AND s.games >= ?
         ORDER BY c.name, s.games DESC`,
      )
      .all(source ?? "", patch, MIN_GAMES) as Record<string, number & string>[];
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

  function findChampion(key: string): ChampionInfo | null {
    const row = d
      .prepare("SELECT * FROM gold_champions WHERE key = ? COLLATE NOCASE OR name = ? COLLATE NOCASE")
      .get(key, key) as Record<string, unknown> | undefined;
    return row ? rowToChampionInfo(row) : null;
  }

  function getChampionDetail(key: string, patch: string, source: Source | null) {
    const champ = findChampion(key);
    if (!champ) return null;
    const patchMatches = getPatchTotal(patch, source);
    const bans = (
      d
        .prepare("SELECT bans FROM gold_champion_bans WHERE source = ? AND patch = ? AND champion_id = ?")
        .get(source ?? "", patch, champ.id) as { bans: number } | undefined
    )?.bans ?? 0;

    const statRows = d
      .prepare("SELECT * FROM gold_champion_stats WHERE source = ? AND patch = ? AND champion_id = ? ORDER BY games DESC")
      .all(source ?? "", patch, champ.id) as Record<string, number>[];

    const roles = statRows.map((s) => {
      const role = String(s.role);
      const games = Number(s.games);
      const matchups = (
        d
          .prepare(
            `SELECT m.opponent_id, m.games, m.wins, c.key, c.name
             FROM gold_matchups m JOIN gold_champions c ON c.champion_id = m.opponent_id
             WHERE m.source = ? AND m.patch = ? AND m.champion_id = ? AND m.role = ? AND m.games >= 3
             ORDER BY m.games DESC`,
          )
          .all(source ?? "", patch, champ.id, role) as Record<string, number & string>[]
      ).map((m) => ({
        id: Number(m.opponent_id),
        key: String(m.key),
        name: String(m.name),
        games: Number(m.games),
        winRate: pct(Number(m.wins) / Number(m.games)),
      }));

      const buildRows = d
        .prepare(
          `SELECT items, games, wins FROM gold_builds
           WHERE source = ? AND patch = ? AND champion_id = ? AND role = ? AND games >= 3
           ORDER BY games DESC LIMIT 40`,
        )
        .all(source ?? "", patch, champ.id, role) as { items: string; games: number; wins: number }[];
      const builds = buildRows.map((b) => ({
        items: JSON.parse(b.items) as number[],
        games: b.games,
        winRate: pct(b.wins / b.games),
      }));

      const spells = (
        d
          .prepare(
            `SELECT spells, games, wins FROM gold_spell_sets
             WHERE source = ? AND patch = ? AND champion_id = ? AND role = ?
             ORDER BY games DESC LIMIT 3`,
          )
          .all(source ?? "", patch, champ.id, role) as { spells: string; games: number; wins: number }[]
      ).map((s2) => ({
        spells: JSON.parse(s2.spells) as number[],
        games: s2.games,
        winRate: pct(s2.wins / s2.games),
      }));

      const runes = (
        d
          .prepare(
            `SELECT keystone, sub_style, games, wins FROM gold_rune_sets
             WHERE source = ? AND patch = ? AND champion_id = ? AND role = ?
             ORDER BY games DESC LIMIT 3`,
          )
          .all(source ?? "", patch, champ.id, role) as Record<string, number>[]
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
      source,
      patch,
      banRate: patchMatches ? pct(bans / patchMatches) : 0,
      roles,
    };
  }

  function searchChampions(q: string): ChampionInfo[] {
    const rows = d
      .prepare(
        "SELECT * FROM gold_champions WHERE name LIKE ? COLLATE NOCASE OR key LIKE ? COLLATE NOCASE ORDER BY name LIMIT 10",
      )
      .all(`%${q}%`, `%${q}%`) as Record<string, unknown>[];
    return rows.map(rowToChampionInfo);
  }

  function getRunes(version?: string) {
    const selectedVersion = version || getMeta().ddragonVersion;
    const row = selectedVersion ? d.prepare("SELECT styles FROM gold_rune_catalog WHERE version = ? AND locale = 'en_US'").get(selectedVersion) as { styles: string } | undefined : undefined;
    return { version: selectedVersion, styles: row ? JSON.parse(row.styles) : [] };
  }

  return { getMeta, getChampionRows, getChampionDetail, searchChampions, getRunes };
}
