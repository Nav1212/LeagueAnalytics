import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { fetchMeta } from "./api";
import type { Meta } from "./api";
import { ErrorBox, Spinner } from "./components";
import { loadRuneIcons, setDdragonVersion } from "./ddragon";
import Champion from "./pages/Champion";
import Home from "./pages/Home";

interface AppContextValue {
  meta: Meta;
  patch: string;
  setPatch: (p: string) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp outside provider");
  return ctx;
}

function Header() {
  const { meta, patch, setPatch } = useApp();
  const demoOnly = !meta.rawMatches.riot && !!meta.rawMatches.demo;
  return (
    <header className="site-header">
      <div className="container header-inner">
        <Link to="/" className="logo">
          <span className="logo-champion">CHAMPION</span>
          <span className="logo-gg">.GG</span>
          <span className="logo-sub">revitalization</span>
        </Link>
        <div className="header-right">
          {demoOnly && (
            <span className="demo-chip" title="Synthetic data in exact Riot Match-V5 shape. Run the fetcher with a RIOT_API_KEY for live data.">
              demo data
            </span>
          )}
          <label className="patch-select">
            Patch
            <select value={patch} onChange={(e) => setPatch(e.target.value)}>
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

  useEffect(() => {
    fetchMeta()
      .then((m) => {
        setDdragonVersion(m.ddragonVersion);
        void loadRuneIcons();
        setMeta(m);
        setPatch((p) => p || m.latestPatch || "");
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const ctx = useMemo(
    () => (meta ? { meta, patch, setPatch } : null),
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
