/** Typed client for the server's JSON API. */

export interface PatchInfo {
  patch: string;
  matches: number;
}

export interface Meta {
  patches: PatchInfo[];
  latestPatch: string | null;
  totalMatches: number;
  championCount: number;
  rawMatches: Record<string, number>;
  ddragonVersion: string | null;
  aggregatedAt: string | null;
}

export interface Kda {
  kills: number;
  deaths: number;
  assists: number;
}

export interface ChampionRow {
  id: number;
  key: string;
  name: string;
  role: string;
  games: number;
  wins: number;
  winRate: number;
  pickRate: number;
  banRate: number;
  kda: Kda;
  avgGold: number;
  avgDamage: number;
  avgCs: number;
}

export interface Matchup {
  id: number;
  key: string;
  name: string;
  games: number;
  winRate: number;
}

export interface Build {
  items: number[];
  games: number;
  winRate: number;
}

export interface SpellSet {
  spells: number[];
  games: number;
  winRate: number;
}

export interface RuneSet {
  keystone: number;
  subStyle: number;
  games: number;
  winRate: number;
}

export interface RoleDetail {
  role: string;
  games: number;
  winRate: number;
  pickRate: number;
  kda: Kda;
  kdaRatio: number;
  avgGold: number;
  avgDamage: number;
  avgCs: number;
  matchups: Matchup[];
  builds: { mostPopular: Build[]; highestWin: Build[] };
  spells: SpellSet[];
  runes: RuneSet[];
}

export interface ChampionDetail {
  id: number;
  key: string;
  name: string;
  title: string;
  tags: string[];
  patch: string;
  banRate: number;
  roles: RoleDetail[];
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: string } | null;
    throw new Error(body?.error ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const fetchMeta = () => get<Meta>("/api/meta");

export const fetchChampions = (patch: string) =>
  get<{ patch: string; rows: ChampionRow[] }>(
    `/api/champions?patch=${encodeURIComponent(patch)}`,
  );

export const fetchChampionDetail = (key: string, patch: string) =>
  get<ChampionDetail>(
    `/api/champion/${encodeURIComponent(key)}?patch=${encodeURIComponent(patch)}`,
  );
