/**
 * Champion.GG-Revitalization API + static server.
 *
 * Read-only layer between the SQLite database (written by the Python
 * processor) and the React frontend. Serves the built client from
 * webapp/client/dist when it exists.
 */
import express from "express";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  DB_PATH,
  getChampionDetail,
  getChampionRows,
  getMeta,
  searchChampions,
} from "./db.ts";

const PORT = Number(process.env.PORT ?? 8000);
const app = express();
app.disable("x-powered-by");

// ------------------------------------------------------------------- API
app.get("/api/meta", (_req, res) => {
  res.json(getMeta());
});

app.get("/api/champions", (req, res) => {
  const patch = String(req.query.patch ?? "") || (getMeta().latestPatch ?? "");
  res.json({ patch, rows: getChampionRows(patch) });
});

app.get("/api/champion/:key", (req, res) => {
  const patch = String(req.query.patch ?? "") || (getMeta().latestPatch ?? "");
  const detail = getChampionDetail(req.params.key, patch);
  if (!detail) {
    res.status(404).json({ error: `unknown champion: ${req.params.key}` });
    return;
  }
  res.json(detail);
});

app.get("/api/search", (req, res) => {
  const q = String(req.query.q ?? "").trim();
  res.json(q ? searchChampions(q) : []);
});

// Friendly JSON errors (e.g. database missing)
app.use(((err, _req, res, _next) => {
  console.error(err);
  res.status(500).json({ error: err instanceof Error ? err.message : "internal error" });
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

app.listen(PORT, () => {
  console.log(`champion.gg-revitalization server on http://localhost:${PORT}`);
  console.log(`database: ${DB_PATH}`);
});
