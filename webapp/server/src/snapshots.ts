/** Adopt complete Python publications between requests; retain the last good one. */
import { DatabaseSync } from "node:sqlite";
import { readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRepository } from "./db.ts";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
export const GOLD_DIR = path.resolve(repoRoot, process.env.CHAMPIONGG_GOLD_DIR ?? "data/gold");
const COLUMNS: Record<string, string[]> = {
  gold_patch_totals: ["source", "patch", "matches"],
  gold_champion_stats: ["source", "patch", "champion_id", "role", "games", "wins", "kills", "deaths", "assists", "gold", "damage", "cs"],
  gold_champion_bans: ["source", "patch", "champion_id", "bans"],
  gold_matchups: ["source", "patch", "champion_id", "role", "opponent_id", "games", "wins"],
  gold_builds: ["source", "patch", "champion_id", "role", "items", "games", "wins"],
  gold_spell_sets: ["source", "patch", "champion_id", "role", "spells", "games", "wins"],
  gold_rune_sets: ["source", "patch", "champion_id", "role", "keystone", "sub_style", "games", "wins"],
  gold_champions: ["champion_id", "key", "name", "title", "tags"],
  gold_source_counts: ["source", "raw_matches"],
  gold_rune_catalog: ["version", "locale", "styles"],
  gold_meta: ["key", "value"],
};

export class GoldUnavailable extends Error {
  status = 503;
  constructor() { super("Gold data is unavailable. Publish it with python -m processor.main aggregate."); }
}

export function openGoldDatabase(filename: string): DatabaseSync {
  const connection = new DatabaseSync(filename, { readOnly: true });
  connection.exec("PRAGMA query_only=ON; PRAGMA trusted_schema=OFF;");
  return connection;
}

export class GoldSnapshots {
  private db: DatabaseSync | null = null;
  private manifestText: string | null = null;
  private lastFailure: string | null = null;
  private directory: string;

  constructor(directory = GOLD_DIR) { this.directory = directory; }

  repository() {
    let candidate: DatabaseSync | null = null;
    try {
      const text = readFileSync(path.join(this.directory, "current.json"), "utf8");
      if (!this.db || text !== this.manifestText) {
        const manifest = JSON.parse(text) as { snapshot: string; schemaVersion: number; runId: string };
        if (manifest.schemaVersion !== 1 || typeof manifest.runId !== "string" ||
            !/^[A-Za-z0-9_-]+$/.test(manifest.runId) || manifest.snapshot !== `gold-${manifest.runId}.sqlite`) {
          throw new Error("Unsupported Gold manifest");
        }
        const root = realpathSync(this.directory);
        const filename = realpathSync(path.join(root, manifest.snapshot));
        if (path.dirname(filename) !== root) throw new Error("Gold snapshot is outside publication directory");
        candidate = openGoldDatabase(filename);
        const objects = candidate.prepare("SELECT name,type FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").all() as { name: string; type: string }[];
        if (objects.length !== Object.keys(COLUMNS).length || objects.some(o => o.type !== "table" || !Object.hasOwn(COLUMNS, o.name))) {
          throw new Error("Unexpected objects in Gold snapshot");
        }
        for (const [table, expected] of Object.entries(COLUMNS)) {
          const columns = candidate.prepare(`PRAGMA table_info(${table})`).all() as { name: string }[];
          if (JSON.stringify(columns.map(c => c.name)) !== JSON.stringify(expected)) throw new Error(`Invalid Gold table: ${table}`);
        }
        if (candidate.prepare("PRAGMA user_version").get()?.user_version !== 1 ||
            candidate.prepare("PRAGMA quick_check").get()?.quick_check !== "ok" ||
            candidate.prepare("PRAGMA journal_mode").get()?.journal_mode !== "delete" ||
            candidate.prepare("SELECT value FROM gold_meta WHERE key='run_id'").get()?.value !== manifest.runId ||
            candidate.prepare("SELECT value FROM gold_meta WHERE key='schema_version'").get()?.value !== "1") {
          throw new Error("Gold snapshot validation failed");
        }
        const old = this.db;
        this.db = candidate;
        candidate = null;
        this.manifestText = text;
        old?.close();
      }
      this.lastFailure = null;
    } catch (error) {
      candidate?.close();
      const message = String(error);
      if (message !== this.lastFailure) console.error("Gold publication unavailable:", message);
      this.lastFailure = message;
    }
    if (!this.db) throw new GoldUnavailable();
    // Route handlers are synchronous and acquire this repository once. No
    // publication switch can happen during the queries for that request.
    return createRepository(this.db);
  }

  close() { this.db?.close(); this.db = null; this.manifestText = null; }
}
