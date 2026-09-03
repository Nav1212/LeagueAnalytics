import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchChampionDetail } from "../api";
import type { Build, ChampionDetail, RoleDetail } from "../api";
import { useApp } from "../App";
import { ErrorBox, RoleIcon, SafeImg, Spinner, WinRate } from "../components";
import {
  champIcon,
  champSplash,
  itemIcon,
  KEYSTONE_NAMES,
  ROLE_LABELS,
  runeIcon,
  spellIcon,
  SPELL_NAMES,
  STYLE_NAMES,
} from "../ddragon";

function StatCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="stat-card">
      <div className="stat-value">{children}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function BuildRow({ build }: { build: Build }) {
  return (
    <div className="build-row">
      <div className="build-items">
        {build.items.map((id, i) => (
          <SafeImg key={i} src={itemIcon(id)} alt={`item ${id}`} title={`Item ${id}`} className="item-icon" />
        ))}
      </div>
      <div className="build-meta">
        <WinRate value={build.winRate} />
        <span className="muted">{build.games.toLocaleString()} games</span>
      </div>
    </div>
  );
}

function MatchupList({ title, items, tone }: {
  title: string;
  items: RoleDetail["matchups"];
  tone: "good" | "bad";
}) {
  return (
    <div className="panel">
      <h3 className={`panel-title ${tone === "good" ? "title-good" : "title-bad"}`}>{title}</h3>
      {items.length === 0 && <p className="muted">Not enough games this patch.</p>}
      <ul className="matchup-list">
        {items.map((m) => (
          <li key={m.id}>
            <Link to={`/champion/${m.key}`} className="matchup-champ">
              <SafeImg src={champIcon(m.key)} alt={m.name} className="champ-icon" />
              <span>{m.name}</span>
            </Link>
            <span className="muted">{m.games} g</span>
            <WinRate value={m.winRate} />
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Champion() {
  const { champKey } = useParams();
  const { patch } = useApp();
  const [detail, setDetail] = useState<ChampionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [roleIdx, setRoleIdx] = useState(0);

  useEffect(() => {
    if (!champKey || !patch) return;
    setDetail(null);
    setError(null);
    setRoleIdx(0);
    fetchChampionDetail(champKey, patch)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }, [champKey, patch]);

  const role = detail?.roles[roleIdx];

  // Matchups: champion.gg-style "best/worst against", sorted by our win rate
  const { best, worst } = useMemo(() => {
    const ms = [...(role?.matchups ?? [])].sort((a, b) => b.winRate - a.winRate);
    return { best: ms.slice(0, 6), worst: ms.slice(-6).reverse() };
  }, [role]);

  if (error) {
    return (
      <ErrorBox>
        <h2>Champion unavailable</h2>
        <p>{error}</p>
        <Link to="/">← Back to champion list</Link>
      </ErrorBox>
    );
  }
  if (!detail) return <Spinner label="Loading champion..." />;

  return (
    <div className="champ-page">
      <section
        className="champ-hero"
        style={{ backgroundImage: `url(${champSplash(detail.key)})` }}
      >
        <div className="champ-hero-overlay">
          <SafeImg src={champIcon(detail.key)} alt={detail.name} className="champ-portrait" />
          <div className="champ-headline">
            <h1>{detail.name}</h1>
            <p className="champ-title">{detail.title}</p>
            <div className="champ-tags">
              {detail.tags.map((t) => (
                <span key={t} className="tag-chip">{t}</span>
              ))}
              <span className="tag-chip ban-chip">Ban rate {detail.banRate.toFixed(1)}%</span>
              <span className="tag-chip patch-chip">Patch {detail.patch}</span>
            </div>
          </div>
          <Link to="/" className="back-link">← All champions</Link>
        </div>
      </section>

      {detail.roles.length === 0 ? (
        <ErrorBox>
          <p>No ranked games recorded for {detail.name} on patch {detail.patch}.</p>
        </ErrorBox>
      ) : (
        <>
          <nav className="role-tabs champ-role-tabs">
            {detail.roles.map((r, i) => (
              <button
                key={r.role}
                className={i === roleIdx ? "role-tab active" : "role-tab"}
                onClick={() => setRoleIdx(i)}
              >
                <RoleIcon role={r.role} />
                <span>{ROLE_LABELS[r.role] ?? r.role}</span>
                <span className="tab-sub">{r.pickRate.toFixed(1)}%</span>
              </button>
            ))}
          </nav>

          {role && (
            <>
              <div className="stat-cards">
                <StatCard label="Win rate"><WinRate value={role.winRate} /></StatCard>
                <StatCard label="Pick rate">{role.pickRate.toFixed(1)}%</StatCard>
                <StatCard label="KDA">
                  <span className="kda-ratio">{role.kdaRatio.toFixed(2)}</span>{" "}
                  <span className="kda-detail">
                    {role.kda.kills} / {role.kda.deaths} / {role.kda.assists}
                  </span>
                </StatCard>
                <StatCard label="CS / game">{role.avgCs.toFixed(0)}</StatCard>
                <StatCard label="Gold / game">{role.avgGold.toLocaleString()}</StatCard>
                <StatCard label="Damage / game">{role.avgDamage.toLocaleString()}</StatCard>
                <StatCard label="Games">{role.games.toLocaleString()}</StatCard>
              </div>

              <div className="detail-grid">
                <MatchupList title={`${detail.name} beats`} items={best} tone="good" />
                <MatchupList title={`${detail.name} struggles vs`} items={worst} tone="bad" />

                <div className="panel">
                  <h3 className="panel-title">Most popular core build</h3>
                  {role.builds.mostPopular.length === 0 && (
                    <p className="muted">Not enough games this patch.</p>
                  )}
                  {role.builds.mostPopular.map((b, i) => (
                    <BuildRow key={i} build={b} />
                  ))}
                </div>

                <div className="panel">
                  <h3 className="panel-title">Highest win core build</h3>
                  {role.builds.highestWin.map((b, i) => (
                    <BuildRow key={i} build={b} />
                  ))}
                </div>

                <div className="panel">
                  <h3 className="panel-title">Summoner spells</h3>
                  {role.spells.map((s, i) => (
                    <div className="build-row" key={i}>
                      <div className="build-items">
                        {s.spells.map((id) => (
                          <SafeImg
                            key={id}
                            src={spellIcon(id)}
                            alt={SPELL_NAMES[id] ?? `spell ${id}`}
                            title={SPELL_NAMES[id]}
                            className="item-icon"
                          />
                        ))}
                        <span className="spell-names">
                          {s.spells.map((id) => SPELL_NAMES[id] ?? id).join(" + ")}
                        </span>
                      </div>
                      <div className="build-meta">
                        <WinRate value={s.winRate} />
                        <span className="muted">{s.games.toLocaleString()} games</span>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="panel">
                  <h3 className="panel-title">Runes</h3>
                  {role.runes.map((r, i) => (
                    <div className="build-row" key={i}>
                      <div className="build-items">
                        <SafeImg
                          src={runeIcon(r.keystone)}
                          alt={KEYSTONE_NAMES[r.keystone] ?? `rune ${r.keystone}`}
                          className="rune-icon"
                        />
                        <span className="rune-names">
                          <strong>{KEYSTONE_NAMES[r.keystone] ?? r.keystone}</strong>
                          <span className="muted">
                            {" + "}
                            {STYLE_NAMES[r.subStyle] ?? r.subStyle}
                          </span>
                        </span>
                      </div>
                      <div className="build-meta">
                        <WinRate value={r.winRate} />
                        <span className="muted">{r.games.toLocaleString()} games</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
