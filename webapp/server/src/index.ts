/**
 * Champion.GG-Revitalization API + static server.
 *
 * Read-only layer over Gold snapshots published by the Python
 * processor. Serves the built client from
 * webapp/client/dist when it exists.
 */
import express from "express";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import type { Source } from "./db.ts";
import { GOLD_DIR, GoldSnapshots, GoldUnavailable } from "./snapshots.ts";

const PORT = Number(process.env.PORT ?? 8000);
const app = express();
const snapshots = new GoldSnapshots();
app.disable("x-powered-by");

class BadRequest extends Error {}
function requestedSource(value: unknown): Source | undefined {
  if (value === undefined) return undefined;
  if (value === "riot" || value === "demo") return value;
  throw new BadRequest("source must be riot or demo");
}

// ------------------------------------------------------------------- API
app.get("/api/meta", (req, res) => {
  const source = requestedSource(req.query.source);
  res.json(snapshots.repository().getMeta(source));
});

app.get("/api/champions", (req, res) => {
  const requested = requestedSource(req.query.source);
  const repository = snapshots.repository();
  const meta = repository.getMeta(requested);
  const patch = String(req.query.patch ?? "") || (meta.latestPatch ?? "");
  res.json({ source: meta.source, patch, rows: repository.getChampionRows(patch, meta.source) });
});

app.get("/api/champion/:key", (req, res) => {
  const requested = requestedSource(req.query.source);
  const repository = snapshots.repository();
  const meta = repository.getMeta(requested);
  const patch = String(req.query.patch ?? "") || (meta.latestPatch ?? "");
  const detail = repository.getChampionDetail(req.params.key, patch, meta.source);
  if (!detail) {
    res.status(404).json({ error: `unknown champion: ${req.params.key}` });
    return;
  }
  res.json(detail);
});

app.get("/api/search", (req, res) => {
  const q = String(req.query.q ?? "").trim();
  const repository = snapshots.repository();
  res.json(q ? repository.searchChampions(q) : []);
});

app.get("/api/static/runes", (req, res) => {
  res.json(snapshots.repository().getRunes(String(req.query.version ?? "") || undefined));
});

// Friendly JSON errors (e.g. database missing)
app.use(((err, _req, res, _next) => {
  console.error(err);
  const status = err instanceof GoldUnavailable ? 503 : err instanceof BadRequest ? 400 : 500;
  res.status(status).json({ error: status === 500 ? "internal error" : err.message });
}) as express.ErrorRequestHandler);

// -------------------------------------------------------------- frontend
const here = path.dirname(fileURLToPath(import.meta.url));
const clientDist = path.resolve(here, "..", "..", "client", "dist");
if (existsSync(clientDist)) {
  app.use(express.static(clientDist));
  // SPA fallback: any non-API GET serves the app shell
  app.use((req, res, next) => {
    if (req.method === "GET" && !req.path.startsWith("/api/")) {
      res.sendFile(path.join(clientDist, "index.html"));
    } else {
      next();
    }
  });
} else {
  app.get("/", (_req, res) => {
    res
      .type("text/plain")
      .send("API is running. Build the frontend (npm run build in webapp/client) or use the Vite dev server.");
  });
}

const server = app.listen(PORT, () => {
  const address = server.address();
  const port = address && typeof address !== "string" ? address.port : PORT;
  console.log(`champion.gg-revitalization server on http://localhost:${port}`);
  console.log(`Gold directory: ${GOLD_DIR}`);
});
function shutdown() { server.close(() => { snapshots.close(); process.exit(0); }); }
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
