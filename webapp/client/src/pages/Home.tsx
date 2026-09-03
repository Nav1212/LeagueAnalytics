import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchChampions } from "../api";
import type { ChampionRow } from "../api";
import { useApp } from "../App";
import { ErrorBox, RoleIcon, SafeImg, Spinner, TierBadge, WinRate } from "../components";
import { champIcon, ROLE_LABELS, ROLE_ORDER } from "../ddragon";

type SortKey = "winRate" | "pickRate" | "banRate" | "games" | "kda" | "avgCs" | "name";

const kdaRatio = (r: ChampionRow) =>
  (r.kda.kills + r.kda.assists) / Math.max(0.75, r.kda.deaths);

const SORTERS: Record<SortKey, (a: ChampionRow, b: ChampionRow) => number> = {
  winRate: (a, b) => b.winRate - a.winRate,
  pickRate: (a, b) => b.pickRate - a.pickRate,
  banRate: (a, b) => b.banRate - a.banRate,
  games: (a, b) => b.games - a.games,
  kda: (a, b) => kdaRatio(b) - kdaRatio(a),
  avgCs: (a, b) => b.avgCs - a.avgCs,
  name: (a, b) => a.name.localeCompare(b.name),
};

export default function Home() {
  const { meta, patch } = useApp();
  const [rows, setRows] = useState<ChampionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [role, setRole] = useState<string>("ALL");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("winRate");
  const [asc, setAsc] = useState(false);

  useEffect(() => {
    if (!patch) return;
    setRows(null);
    setError(null);
    fetchChampions(patch)
      .then((d) => setRows(d.rows))
      .catch((e: Error) => setError(e.message));
  }, [patch]);

  const patchMatches = meta.patches.find((p) => p.patch === patch)?.matches ?? 0;

  const view = useMemo(() => {
    if (!rows) return [];
    let out = rows;
    if (role !== "ALL") out = out.filter((r) => r.role === role);
    const q = query.trim().toLowerCase();
    if (q) out = out.filter((r) => r.name.toLowerCase().includes(q));
    out = [...out].sort(SORTERS[sortKey]);
    if (asc) out.reverse();
    return out;
  }, [rows, role, query, sortKey, asc]);

  const roleCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of rows ?? []) counts[r.role] = (counts[r.role] ?? 0) + 1;
    return counts;
  }, [rows]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setAsc(!asc);
    } else {
      setSortKey(key);
      setAsc(key === "name");
    }
  };

  const arrow = (key: SortKey) =>
    sortKey === key ? <span className="sort-arrow">{asc ? "▲" : "▼"}</span> : null;

  if (error) return <ErrorBox><h2>Failed to load champions</h2><p>{error}</p></ErrorBox>;

  return (
    <div className="home-page">
      <section className="hero">
        <h1>Champion Statistics</h1>
        <p className="hero-sub">
          Win, pick and ban rates from{" "}
          <strong>{patchMatches.toLocaleString()}</strong> ranked solo queue matches on patch{" "}
          <strong>{patch}</strong>
        </p>
      </section>

      <div className="toolbar">
        <nav className="role-tabs" aria-label="Filter by role">
          <button
            className={role === "ALL" ? "role-tab active" : "role-tab"}
            onClick={() => setRole("ALL")}
          >
            All
          </button>
          {ROLE_ORDER.map((r) => (
            <button
              key={r}
              className={role === r ? "role-tab active" : "role-tab"}
              onClick={() => setRole(r)}
              title={`${ROLE_LABELS[r]} (${roleCounts[r] ?? 0} champions)`}
            >
              <RoleIcon role={r} />
              <span>{ROLE_LABELS[r]}</span>
            </button>
          ))}
        </nav>
        <input
          type="search"
          className="search-input"
          placeholder="Search champion..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {!rows ? (
        <Spinner label="Loading champion stats..." />
      ) : (
        <div className="table-wrap">
          <table className="champ-table">
            <thead>
              <tr>
                <th className="col-rank">#</th>
                <th className="col-champ sortable" onClick={() => onSort("name")}>
                  Champion {arrow("name")}
                </th>
                <th>Role</th>
                <th>Tier</th>
                <th className="sortable" onClick={() => onSort("winRate")}>
                  Win rate {arrow("winRate")}
                </th>
                <th className="sortable" onClick={() => onSort("pickRate")}>
                  Pick rate {arrow("pickRate")}
                </th>
                <th className="sortable" onClick={() => onSort("banRate")}>
                  Ban rate {arrow("banRate")}
                </th>
                <th className="sortable" onClick={() => onSort("kda")}>
                  KDA {arrow("kda")}
                </th>
                <th className="sortable hide-sm" onClick={() => onSort("avgCs")}>
                  CS {arrow("avgCs")}
                </th>
                <th className="sortable hide-sm" onClick={() => onSort("games")}>
                  Games {arrow("games")}
                </th>
              </tr>
            </thead>
            <tbody>
              {view.map((r, i) => (
                <tr key={`${r.id}-${r.role}`}>
                  <td className="col-rank">{i + 1}</td>
                  <td className="col-champ">
                    <Link to={`/champion/${r.key}`} className="champ-cell">
                      <SafeImg src={champIcon(r.key)} alt={r.name} className="champ-icon" />
                      <span>{r.name}</span>
                    </Link>
                  </td>
                  <td>
                    <span className="role-cell">
                      <RoleIcon role={r.role} />
                      {ROLE_LABELS[r.role] ?? r.role}
                    </span>
                  </td>
                  <td><TierBadge winRate={r.winRate} /></td>
                  <td><WinRate value={r.winRate} bar /></td>
                  <td className="num">{r.pickRate.toFixed(1)}%</td>
                  <td className="num">{r.banRate.toFixed(1)}%</td>
                  <td className="num">
                    <span className="kda-ratio">{kdaRatio(r).toFixed(2)}</span>
                    <span className="kda-detail hide-sm">
                      {r.kda.kills} / {r.kda.deaths} / {r.kda.assists}
                    </span>
                  </td>
                  <td className="num hide-sm">{r.avgCs.toFixed(0)}</td>
                  <td className="num hide-sm">{r.games.toLocaleString()}</td>
                </tr>
              ))}
              {view.length === 0 && (
                <tr>
                  <td colSpan={10} className="empty-row">
                    No champions match — try another role or search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
