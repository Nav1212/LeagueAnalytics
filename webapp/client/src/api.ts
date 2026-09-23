/** Typed client for the server's JSON API. */
export type Source = "riot" | "demo";

export interface PatchInfo {
  patch: string;
  matches: number;
}

export interface Meta {
  source: Source | null;
  sources: Source[];
  runId: string;
  schemaVersion: number;
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
  source: Source | null;
  id: number;
  key: string;
  name: string;
  title: string;
  tags: string[];
  patch: string;
  banRate: number;
  roles: RoleDetail[];
}

async function get<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { error?: string } | null;
    throw new Error(body?.error ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export interface RuneStyle {
  id: number;
  name: string;
  icon: string | null;
  slots: { runes: { id: number; icon: string | null; name: string }[] }[];
}
export interface RuneCatalog { version: string | null; styles: RuneStyle[] }

export const fetchMeta = (source?: Source, signal?: AbortSignal) =>
  get<Meta>(`/api/meta${source ? `?source=${source}` : ""}`, signal);

export const fetchChampions = (patch: string, source: Source, signal?: AbortSignal) =>
  get<{ source: Source; patch: string; rows: ChampionRow[] }>(
    `/api/champions?patch=${encodeURIComponent(patch)}&source=${source}`, signal,
  );

export const fetchChampionDetail = (key: string, patch: string, source: Source | null, signal?: AbortSignal) =>
  get<ChampionDetail>(
    `/api/champion/${encodeURIComponent(key)}?patch=${encodeURIComponent(patch)}${source ? `&source=${source}` : ""}`, signal,
  );

export const fetchRunes = (version: string | null, signal?: AbortSignal) =>
  get<RuneCatalog>(`/api/static/runes${version ? `?version=${encodeURIComponent(version)}` : ""}`, signal);
