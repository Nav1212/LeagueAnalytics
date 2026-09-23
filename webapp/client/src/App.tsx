import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { fetchMeta, fetchRunes } from "./api";
import type { Meta, Source } from "./api";
import { ErrorBox, Spinner } from "./components";
import { applyRuneStyles, setDdragonVersion } from "./ddragon";
import Champion from "./pages/Champion";
import Home from "./pages/Home";

interface AppContextValue {
  meta: Meta;
  patch: string;
  setPatch: (p: string) => void;
  source: Source | null;
  setSource: (source: Source) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp outside provider");
  return ctx;
}

function Header() {
  const { meta, patch, setPatch, source, setSource } = useApp();
  const demoOnly = source === "demo";
  return (
    <header className="site-header">
      <div className="container header-inner">
        <Link to="/" className="logo">
          <span className="logo-champion">CHAMPION</span>
          <span className="logo-gg">.GG</span>
          <span className="logo-sub">revitalization</span>
        </Link>
        <div className="header-right">
          <label className="patch-select">
            Source
            <select aria-label="Source" value={source ?? ""} disabled={!meta.sources.length}
              onChange={(e) => setSource(e.target.value as Source)}>
              {!meta.sources.length && <option value="">No data</option>}
              {meta.sources.map((s) => <option key={s} value={s}>{s === "riot" ? "Riot" : "Demo"}</option>)}
            </select>
          </label>
          {demoOnly && (
            <span className="demo-chip" title="Synthetic data in exact Riot Match-V5 shape. Run the fetcher with a RIOT_API_KEY for live data.">
              demo data
            </span>
          )}
          <label className="patch-select">
            Patch
            <select aria-label="Patch" value={patch} disabled={!meta.patches.length} onChange={(e) => setPatch(e.target.value)}>
              {meta.patches.map((p) => (
                <option key={p.patch} value={p.patch}>
                  {p.patch}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
    </header>
  );
}

function Footer() {
  const { meta } = useApp();
  return (
    <footer className="site-footer">
      <div className="container">
        <p>
          {meta.totalMatches.toLocaleString()} ranked matches analyzed · Data Dragon{" "}
          {meta.ddragonVersion ?? "?"} · aggregated {meta.aggregatedAt ?? "?"}
        </p>
        <p className="footer-note">
          Not affiliated with Riot Games. A champion.gg-style stats service rebuilt for fun.
        </p>
      </div>
    </footer>
  );
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [patch, setPatch] = useState<string>("");
  const [requestedSource, setSource] = useState<Source | undefined>();

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    setMeta(null);
    fetchMeta(requestedSource, controller.signal)
      .then(async (m) => {
        const runes = await fetchRunes(m.ddragonVersion, controller.signal).catch(() => ({ styles: [] }));
        if (controller.signal.aborted) return;
        setDdragonVersion(m.ddragonVersion);
        try { applyRuneStyles(runes.styles); }
        catch { applyRuneStyles([]); } // Optional catalog errors must not hide statistics.
        setMeta(m);
        setPatch((p) => m.patches.some((entry) => entry.patch === p) ? p : m.latestPatch || "");
      })
      .catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [requestedSource]);

  const ctx = useMemo(
    () => (meta ? { meta, patch, setPatch, source: meta.source, setSource } : null),
    [meta, patch],
  );

  if (error) {
    return (
      <div className="boot-screen">
        <ErrorBox>
          <h2>Can't reach the stats server</h2>
          <p>{error}</p>
          <p>
            Start it with <code>npm run start</code> (or seed the database first:{" "}
            <code>python -m processor.main seed</code>).
          </p>
        </ErrorBox>
      </div>
    );
  }
  if (!ctx) return <div className="boot-screen"><Spinner label="Summoning stats..." /></div>;

  return (
    <AppContext.Provider value={ctx}>
      <BrowserRouter>
        <div className="app-shell">
          <Header />
          <main className="container main-content">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/champion/:champKey" element={<Champion />} />
              <Route path="*" element={<ErrorBox><h2>Page not found</h2></ErrorBox>} />
            </Routes>
          </main>
          <Footer />
        </div>
      </BrowserRouter>
    </AppContext.Provider>
  );
}
