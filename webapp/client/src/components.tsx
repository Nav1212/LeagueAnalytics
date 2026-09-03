import { useState } from "react";
import type { ReactNode } from "react";

/** <img> that hides itself if the asset 404s (e.g. offline / stale item id). */
export function SafeImg(props: {
  src: string;
  alt: string;
  className?: string;
  title?: string;
}) {
  const [ok, setOk] = useState(true);
  if (!props.src || !ok) {
    return <span className={`img-fallback ${props.className ?? ""}`} title={props.title ?? props.alt} />;
  }
  return (
    <img
      src={props.src}
      alt={props.alt}
      title={props.title}
      className={props.className}
      loading="lazy"
      onError={() => setOk(false)}
    />
  );
}

/** Win-rate figure, colored green/red around 50%. */
export function WinRate({ value, bar }: { value: number; bar?: boolean }) {
  const cls = value >= 51.5 ? "wr-high" : value <= 48.5 ? "wr-low" : "wr-mid";
  return (
    <span className={`wr ${cls}`}>
      {value.toFixed(1)}%
      {bar && (
        <span className="wr-bar">
          <span
            className="wr-bar-fill"
            style={{ width: `${Math.min(100, Math.max(4, (value - 35) * (100 / 30)))}%` }}
          />
        </span>
      )}
    </span>
  );
}

/** champion.gg-style tier badge from win rate. */
export function TierBadge({ winRate }: { winRate: number }) {
  const tier =
    winRate >= 54 ? "S+" : winRate >= 52.5 ? "S" : winRate >= 51 ? "A" : winRate >= 49.5 ? "B" : winRate >= 48 ? "C" : "D";
  return <span className={`tier tier-${tier.replace("+", "plus")}`}>{tier}</span>;
}

/** Simplified lane/role glyphs (inline SVG, colored via currentColor). */
export function RoleIcon({ role }: { role: string }) {
  const path = {
    TOP: (
      <>
        <path d="M1 1h9L7.4 3.6H3.6v3.8L1 10z" fill="currentColor" />
        <path d="M13 13H6l2.4-2.4h2.2V8.4L13 6z" fill="currentColor" opacity=".38" />
      </>
    ),
    JUNGLE: (
      <>
        <path
          d="M7 .5C5.2 3.2 4.3 6 7 13.5 9.7 6 8.8 3.2 7 .5z"
          fill="currentColor"
        />
        <path
          d="M2.5 4c1.5 2 2.5 3.6 3 6.5C3.5 9 2.6 7 2.5 4zM11.5 4c-1.5 2-2.5 3.6-3 6.5 2-1.5 2.9-3.5 3-6.5z"
          fill="currentColor"
          opacity=".55"
        />
      </>
    ),
    MIDDLE: (
      <>
        <path d="M9.8 1H13L1 13V9.8z" fill="currentColor" />
        <path d="M1 1h5.5L4.4 3.1H3.1v1.3L1 6.5z" fill="currentColor" opacity=".38" />
        <path d="M13 13H7.5l2.1-2.1h1.3V9.6L13 7.5z" fill="currentColor" opacity=".38" />
      </>
    ),
    BOTTOM: (
      <>
        <path d="M13 13H4l2.6-2.6h3.8V6.6L13 4z" fill="currentColor" />
        <path d="M1 1h7L5.6 3.4H3.4v2.2L1 8z" fill="currentColor" opacity=".38" />
      </>
    ),
    UTILITY: (
      <path
        d="M7 1l4.8 1.9v3.4c0 3-1.9 5-4.8 6.2C4.1 11.3 2.2 9.3 2.2 6.3V2.9z"
        fill="currentColor"
      />
    ),
  }[role];
  return (
    <svg viewBox="0 0 14 14" width="16" height="16" aria-hidden="true" className="role-icon">
      {path ?? <circle cx="7" cy="7" r="5" fill="currentColor" />}
    </svg>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="spinner-wrap">
      <div className="spinner" />
      {label && <p>{label}</p>}
    </div>
  );
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return <div className="error-box">{children}</div>;
}
