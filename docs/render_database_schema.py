"""Render the schema as offline HTML and SVG: python docs/render_database_schema.py."""
from __future__ import annotations

import ast
import csv
import html
import json
import re
import sqlite3
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from processor import db, gold
from processor.silver_models import models

OUT = Path(__file__).resolve().parent
WIDTH = 1840
CARD_WIDTH = 310
CARD_HEIGHT = 112
PALETTE = {
    "bronze": "#c08038", "silver": "#3a83af", "gold": "#b18b20",
    "control": "#7771b6", "view": "#b26385", "legacy": "#68846b",
}


def esc(value):
    return html.escape(str(value), quote=True)


def write_gold_imports():
    """Export the actual public schema independently of private legacy tables."""
    connection = sqlite3.connect(":memory:")
    gold.init_schema(connection)
    lines = ["%% Implemented public Gold-only SQLite snapshot; edges are logical joins.", "erDiagram"]
    with (OUT / "gold-data-model-lucidchart.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["dbms", "TABLE_CATALOG", "TABLE_SCHEMA", "TABLE_NAME", "COLUMN_NAME", "ORDINAL_POSITION", "DATA_TYPE", "CHARACTER_MAXIMUM_LENGTH", "CONSTRAINT_TYPE", "TABLE_SCHEMA", "TABLE_NAME", "COLUMN_NAME"])
        for name in gold.TABLES:
            table = "gold_" + name
            lines.append(f"    {table} {{")
            for ordinal, column, kind, _, _, primary in connection.execute(f"PRAGMA table_info({table})"):
                lines.append(f"        {kind} {column}" + (" PK" if primary else ""))
                writer.writerow(["sqlserver", "championgg_gold", "dbo", table, column, ordinal + 1,
                                 "bigint" if kind == "INTEGER" else "text", "",
                                 "PRIMARY KEY" if primary else "", "", "", ""])
            lines.append("    }")
    for name in ("champion_stats", "champion_bans", "matchups", "builds", "spell_sets", "rune_sets"):
        lines.append(f'    gold_champions ||--o{{ gold_{name} : "champion_id"')
        lines.append(f'    gold_patch_totals ||--o{{ gold_{name} : "source and patch"')
    (OUT / "gold-physical-data-model.mmd").write_text("\n".join(lines) + "\n", encoding="utf-8")
    connection.close()


def catalog():
    result = {}
    connection = sqlite3.connect(":memory:")
    db.init_schema(connection)
    for name, sql in connection.execute(
        "SELECT name,sql FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ):
        columns = connection.execute(f'PRAGMA table_info("{name}")').fetchall()
        key = [c[1] for c in sorted(columns, key=lambda c: c[5]) if c[5]]
        layer = "bronze" if name.startswith("bronze_") or name == "raw_matches" else (
            "control" if name in ("meta", "schema_migrations", "rebuild_runs") else "legacy")
        result[name] = dict(name=name, key=key, columns=[c[1] for c in columns],
                            layer=layer, store="Private SQLite (Python only)", kind="TABLE", sql=sql,
                            key_note="Physical primary key", references=[])
    for model in models():
        name = "silver_" + model.name
        result[name] = dict(name=name, key=list(model.key),
                            columns=[c.name for c in model.columns], layer="silver",
                            store="DuckDB snapshot", kind="TABLE", sql=model.sql,
                            key_note="Registry key checked during rebuild; no SQL PK constraint",
                            references=[f"({', '.join(child)}) → silver_{parent} ({', '.join(target)})"
                                        for child, parent, target in model.references])
    extra = {
        "silver_transform_inputs": (["input_id"], ["input_id", "source_table", "source", "dataset", "natural_key", "routing_value", "payload_id", "content_sha256", "observed_at"]),
        "silver_transform_runs": (["run_id"], ["run_id", "transform_version", "status"]),
        "silver_quality_issues": ([], ["severity", "input_id", "source_path", "rule", "detail"]),
    }
    for name, (key, columns) in extra.items():
        result[name] = dict(name=name, key=key, columns=columns, layer="control",
                            store="DuckDB snapshot", kind="TABLE", sql="Defined in processor/staging.py or processor/rebuild.py",
                            key_note="Logical grain; no SQL PK/FK constraints", references=[])
    gold_sql = (ROOT / "processor/sql/v1/gold.sql").read_text(encoding="utf-8")
    public = sqlite3.connect(":memory:")
    gold.init_schema(public)
    for name, key in gold.SERVING_KEYS.items():
        full_name = "gold_" + name
        statement = re.search(rf"CREATE TABLE {full_name} AS.*?;", gold_sql, re.S).group()
        definition = public.execute("SELECT sql FROM sqlite_schema WHERE name=?", (full_name,)).fetchone()[0]
        result[full_name] = dict(name=full_name, key=list(key),
                                 columns=[r[1] for r in public.execute(f'PRAGMA table_info({full_name})')],
                                 layer="gold", store="Gold-only SQLite snapshot (API read-only)", kind="TABLE", sql=statement + "\n\n" + definition,
                                 key_note="Validated in DuckDB; physical primary key in a separate public SQLite snapshot", references=[])
    public.close()
    staging = ast.parse((ROOT / "processor/staging.py").read_text(encoding="utf-8"))
    sql = next(n.value for n in ast.walk(staging) if isinstance(n, ast.Constant)
               and isinstance(n.value, str) and "CREATE TEMP VIEW _payloads AS" in n.value)
    result["_payloads"] = dict(name="_payloads", key=["payload_id"],
        columns=result["bronze_payloads"]["columns"] + ["input_id", "body", "observed_at", "locale", "version"],
        layer="view", store="DuckDB rebuild connection only", kind="TEMP VIEW",
        sql=re.search(r"CREATE TEMP VIEW _payloads AS.*?;", sql, re.S).group(),
        key_note="One row per payload; disappears when the connection closes",
        references=["bronze_payloads", "bronze_payload_observations (latest valid observed_at per payload)"])
    connection.close()
    return result


def panels():
    result = []

    def panel(title, subtitle, height=1060, notes=()):
        item = dict(title=title, subtitle=subtitle, height=height, nodes={}, edges=[], notes=notes)
        result.append(item)
        return item

    def node(p, name, x, y):
        p["nodes"][name] = (x, y)

    def edge(p, child, parent, label, kind="join"):
        p["edges"].append((child, parent, label, kind))

    def silver(p, name, x, y):
        node(p, "silver_" + name, x, y)

    def join(p, child, parent, label):
        edge(p, "silver_" + child, "silver_" + parent, label)

    p = panel("Match snowflake", "Participant facts at the center · normalized dimensions branch into versioned definitions")
    for name, x, y in [
        ("queues", 260, 45), ("matches", 750, 45), ("maps", 1240, 45),
        ("team_bans", 260, 235), ("match_teams", 750, 235), ("team_objectives", 1240, 235),
        ("players", 260, 425), ("match_participants", 750, 425), ("champions", 1240, 425),
    ]:
        silver(p, name, x, y)
    for i, (child, parent) in enumerate([
        ("participant_items", "items"), ("participant_spells", "summoner_spells"),
        ("participant_rune_styles", "rune_styles"), ("participant_runes", "runes"),
        ("participant_stat_shards", "stat_shards"),
    ]):
        silver(p, child, 30 + i * 365, 670)
        silver(p, parent, 30 + i * 365, 900)
        join(p, child, parent, {"items": "item_id", "summoner_spells": "spell_id", "rune_styles": "style_id", "runes": "rune_id", "stat_shards": "shard_id"}[parent])
        join(p, child, "participant_rune_styles" if child == "participant_runes" else "match_participants",
             "P + style_slot" if child == "participant_runes" else "P")
    for child, parent, label in [
        ("matches", "queues", "queue_id"), ("matches", "maps", "map_id"),
        ("match_teams", "matches", "M"), ("match_participants", "match_teams", "T"),
        ("match_participants", "players", "source + puuid"), ("match_participants", "champions", "champion_id"),
        ("team_bans", "match_teams", "T"), ("team_bans", "champions", "champion_id"),
        ("team_objectives", "match_teams", "T"),
    ]:
        join(p, child, parent, label)

    p = panel("Static dimensions", "Identity → version → localized text · resolve V through game version + platform", 1450)
    for name, x in [("static_versions", 35), ("game_version_static_mappings", 480), ("matches", 925)]:
        silver(p, name, x, 40)
    join(p, "matches", "game_version_static_mappings", "game_version + platform")
    join(p, "game_version_static_mappings", "static_versions", "static_version (V)")
    families = [
        ("champions", "champion", "champion_id", 270),
        ("items", "item", "item_id", 460),
        ("summoner_spells", "spell", "spell_id", 860),
        ("rune_styles", "rune_style", "style_id", 1060),
        ("runes", "rune", "rune_id", 1260),
    ]
    for identity, prefix, key, y in families:
        for name, x in [(identity, 35), (prefix + "_versions", 480), (prefix + "_localizations", 925)]:
            silver(p, name, x, y)
        join(p, prefix + "_versions", identity, key)
        join(p, prefix + "_localizations", prefix + "_versions", "V + " + key)
    silver(p, "champion_tags", 1370, 270)
    join(p, "champion_tags", "champion_versions", "V + champion_id")
    for name, x in [("item_recipe_components", 35), ("item_stats", 480), ("item_map_availability", 925)]:
        silver(p, name, x, 660)
        join(p, name, "item_versions", "V + item_id")
    join(p, "item_recipe_components", "items", "component_id")
    join(p, "rune_versions", "rune_style_versions", "V + style_id")

    p = panel("Player history", "Observation time preserves repeated fetches · an observed rank is not a historical match rank")
    silver(p, "players", 750, 65)
    for i, name in enumerate(["player_identity_snapshots", "summoner_snapshots", "rank_snapshots", "mastery_snapshots", "player_challenge_snapshots"]):
        silver(p, name, 30 + i * 365, 390)
        join(p, name, "players", "source + puuid")
        edge(p, "silver_" + name, "bronze_payload_observations", "observation_id", "lineage")
    node(p, "bronze_payload_observations", 750, 800)
    node(p, "bronze_payloads", 1240, 800)
    edge(p, "bronze_payload_observations", "bronze_payloads", "payload_id")

    p = panel("Timeline facts", "Frame and event array positions define identity · multiple events can share a timestamp")
    for name, x, y in [
        ("matches", 100, 70), ("timeline_frames", 650, 70), ("timeline_events", 1200, 70),
        ("match_participants", 100, 415), ("participant_frames", 650, 415), ("event_participants", 1200, 415),
        ("item_events", 300, 800), ("skill_events", 850, 800), ("objective_events", 1400, 800),
    ]:
        silver(p, name, x, y)
    for child, parent, label in [
        ("timeline_frames", "matches", "M"), ("timeline_events", "timeline_frames", "F"),
        ("match_participants", "matches", "M (logical match join)"),
        ("participant_frames", "match_participants", "P"), ("participant_frames", "timeline_frames", "F"),
        ("event_participants", "match_participants", "P"), ("event_participants", "timeline_events", "E"),
        ("item_events", "timeline_events", "E"), ("skill_events", "timeline_events", "E"), ("objective_events", "timeline_events", "E"),
    ]:
        join(p, child, parent, label)

    p = panel("Bronze & views", "Exact payloads and provenance · the pink card is the temporary view, with its full SQL available on click")
    for name, x, y in [
        ("bronze_fetch_runs", 35, 40), ("bronze_payloads", 500, 40),
        ("bronze_payload_observations", 965, 40), ("bronze_fetch_errors", 1430, 40),
        ("raw_matches", 35, 295), ("_payloads", 730, 295),
        ("bronze_matches", 35, 560), ("bronze_match_timelines", 395, 560),
        ("silver_transform_inputs", 755, 560), ("silver_transform_runs", 1115, 560),
        ("silver_quality_issues", 1475, 560),
        ("schema_migrations", 35, 850), ("rebuild_runs", 500, 850), ("meta", 965, 850),
    ]:
        node(p, name, x, y)
    for child, parent, label in [
        ("bronze_payloads", "bronze_fetch_runs", "fetch_run_id"),
        ("bronze_fetch_errors", "bronze_fetch_runs", "fetch_run_id"),
        ("bronze_payload_observations", "bronze_payloads", "payload_id"),
        ("bronze_payload_observations", "bronze_fetch_runs", "fetch_run_id"),
    ]:
        edge(p, child, parent, label)
    for child, parent, label in [
        ("_payloads", "bronze_payloads", "all payload versions"),
        ("_payloads", "bronze_payload_observations", "latest observed_at per payload"),
        ("bronze_matches", "raw_matches", "initialization copies missing rows"),
        ("silver_transform_inputs", "_payloads", "payload manifest"),
        ("silver_transform_inputs", "bronze_matches", "match manifest"),
        ("silver_transform_inputs", "bronze_match_timelines", "timeline manifest"),
        ("silver_quality_issues", "silver_transform_inputs", "input_id (nullable)"),
        ("silver_transform_runs", "rebuild_runs", "run_id"),
        ("meta", "rebuild_runs", "private processing metadata"),
    ]:
        edge(p, child, parent, label, "lineage")

    p = panel("Gold & API", "Python publishes complete Gold snapshots; TypeScript reads only the public snapshot", 1540,
              notes=[(32, 30, "PUBLIC GOLD - Python writes a dedicated volume; API mount is read-only"),
                     (32, 875, "PRIVATE LEGACY TABLES - retained for compatibility; not read or refreshed by the API")])
    for i, name in enumerate(gold.SERVING_KEYS):
        node(p, "gold_" + name, 35 + (i % 4) * 465, 65 + (i // 4) * 265)
    for i, name in enumerate(["patch_totals", "champions", "champion_stats", "champion_bans", "matchups", "builds", "spell_sets", "rune_sets"]):
        node(p, name, 35 + (i % 4) * 465, 910 + (i // 4) * 265)
    for prefix in ("gold_", ""):
        for name in ["champion_stats", "champion_bans", "matchups", "builds", "spell_sets", "rune_sets"]:
            edge(p, prefix + name, prefix + "champions", "champion_id; opponent_id also joins for matchups")
            edge(p, prefix + name, prefix + "patch_totals", "source + patch" if prefix else "patch")
    return result


def short_key(keys):
    parts = list(keys)
    for prefix, abbreviation in [
        (["source", "match_id", "participant_id"], "P"),
        (["source", "match_id", "team_id"], "T"),
        (["source", "match_id", "frame_index", "event_index"], "E"),
        (["source", "match_id", "frame_index"], "F"),
        (["source", "match_id"], "M"),
        (["source", "puuid", "observation_id"], "O"),
        (["source", "puuid"], "U"),
        (["source", "patch", "champion_id", "role"], "G"),
        (["static_version"], "V"),
    ]:
        if parts[:len(prefix)] == prefix:
            return ", ".join([abbreviation] + parts[len(prefix):])
    return ", ".join(parts) or "No declared key"


def route(start, end):
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    if abs(dx) > abs(dy) * 1.7:
        a = (x1 + (CARD_WIDTH if dx > 0 else 0), y1 + CARD_HEIGHT / 2)
        b = (x2 + (0 if dx > 0 else CARD_WIDTH), y2 + CARD_HEIGHT / 2)
        mid = (a[0] + b[0]) / 2
        return f"M {a[0]} {a[1]} C {mid} {a[1]}, {mid} {b[1]}, {b[0]} {b[1]}"
    a = (x1 + CARD_WIDTH / 2, y1 + (CARD_HEIGHT if dy > 0 else 0))
    b = (x2 + CARD_WIDTH / 2, y2 + (0 if dy > 0 else CARD_HEIGHT))
    mid = (a[1] + b[1]) / 2
    return f"M {a[0]} {a[1]} C {a[0]} {mid}, {b[0]} {mid}, {b[0]} {b[1]}"


SVG_STYLE = """
text { font-family: 'Segoe UI', Arial, sans-serif; }
.edge { fill:none; stroke:#bdcbd3; stroke-width:2; }
.edge.lineage { stroke:#b999aa; stroke-dasharray:7 6; }
.node { cursor:pointer; outline:none; }
.node:hover .card, .node:focus .card { stroke:#243f54; stroke-width:3; }
.node.dim { opacity:.18; }
.node.selected .card { stroke:#143a52; stroke-width:4; }
.edge.dim { opacity:.1; }
.edge.active { stroke:#277eaa; stroke-width:3; }
"""


def drawing(panel, tables):
    output = []
    for child, parent, label, kind in panel["edges"]:
        output.append(f'<path class="edge {kind}" data-child="{child}" data-parent="{parent}" '
                      f'd="{route(panel["nodes"][child], panel["nodes"][parent])}"><title>{esc(child)} → {esc(parent)}: {esc(label)}</title></path>')
    for x, y, label in panel["notes"]:
        output.append(f'<text x="{x}" y="{y}" font-size="18" font-weight="650" fill="#607381">{esc(label)}</text>')
    for name, (x, y) in panel["nodes"].items():
        item = tables[name]
        color = PALETTE[item["layer"]]
        key = short_key(item["key"])
        lines = textwrap.wrap(key, width=37)[:2]
        title = f'{name}\n{item["store"]}\n{item["key_note"]}: {", ".join(item["key"])}\nColumns: {", ".join(item["columns"])}'
        output.append(f'<g class="node" data-table="{name}" transform="translate({x},{y})" tabindex="0" role="button" aria-label="{name}">'
                      f'<title>{esc(title)}</title><rect class="card" width="{CARD_WIDTH}" height="{CARD_HEIGHT}" rx="10" fill="white" stroke="#d1dce2"/>'
                      f'<path d="M10 0 H300 Q310 0 310 10 V6 H0 V10 Q0 0 10 0" fill="{color}"/>'
                      f'<text x="15" y="26" font-size="10" font-weight="700" letter-spacing="1.2" fill="{color}">{item["kind"]} · {item["store"].split(" →")[0].upper()}</text>'
                      f'<text x="15" y="50" font-size="{13 if len(name) > 30 else 14}" font-weight="650" fill="#1b3446">{name}</text>')
        for i, line in enumerate(lines):
            output.append(f'<text x="15" y="{74 + 18 * i}" font-size="12" fill="#526c7c">{esc(("KEY  " if i == 0 else "        ") + line)}</text>')
        output.append('</g>')
    return "".join(output)


def main():
    tables, sections = catalog(), panels()
    shown = {name for section in sections for name in section["nodes"]}
    assert shown == set(tables), f"Update diagram layout: missing={set(tables)-shown}, unknown={shown-set(tables)}"
    for section in sections:
        for child, parent, _, _ in section["edges"]:
            assert child in section["nodes"] and parent in section["nodes"]
        for x, y in section["nodes"].values():
            assert 0 <= x <= WIDTH - CARD_WIDTH and 0 <= y <= section["height"] - CARD_HEIGHT

    key_legend = "M = source + match_id   ·   P = M + participant_id   ·   T = M + team_id   ·   F = M + frame_index   ·   E = F + event_index"
    other_keys = "U = source + puuid   ·   O = U + observation_id   ·   V = static_version   ·   G = source + patch + champion_id + role"
    total_height = 340 + sum(p["height"] + 180 for p in sections)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH + 80}" height="{total_height}" viewBox="0 0 {WIDTH + 80} {total_height}" role="img" aria-labelledby="title description">',
           '<title id="title">Champion.GG database snowflake schema</title>',
           '<desc id="description">Six schema diagrams covering match facts, static dimensions, player history, timelines, Bronze provenance including the temporary _payloads view, and public Gold snapshots and private legacy tables. Keys are listed on every card; lines show logical joins or dependencies, not necessarily enforced foreign keys.</desc>',
           f'<style>{SVG_STYLE}</style><rect width="100%" height="100%" fill="#f3f6f8"/>',
           '<text x="55" y="70" fill="#607381" font-size="17" letter-spacing="3">CHAMPION.GG / DATABASE ATLAS</text>',
           '<text x="55" y="125" fill="#17354a" font-size="42" font-weight="700">The snowflake schema</text>',
           f'<text x="55" y="165" fill="#607381" font-size="18">{len(tables)-1} tables · 1 temporary view · SQLite + DuckDB · generated from repository definitions</text>',
           f'<text x="55" y="211" fill="#607381" font-size="16">{esc(key_legend)}</text>',
           f'<text x="55" y="240" fill="#607381" font-size="16">{esc(other_keys)}</text>',
           '<text x="55" y="277" fill="#607381" font-size="16">Solid lines: logical joins. Dashed lines: lineage / dependencies. Lines do not imply enforced foreign keys.</text>']
    offset = 315
    for index, section in enumerate(sections):
        svg.append(f'<g transform="translate(40,{offset})"><text x="10" y="35" font-size="30" font-weight="700" fill="#17354a">{index+1:02d} / {esc(section["title"])}</text>'
                   f'<text x="10" y="73" font-size="18" fill="#607381">{esc(section["subtitle"])}</text>'
                   f'<g transform="translate(0,100)">{drawing(section,tables)}</g></g>')
        offset += section["height"] + 180
    svg.append('</svg>')
    (OUT / "database-snowflake-schema.svg").write_text("\n".join(svg), encoding="utf-8")

    drawings = []
    for i, section in enumerate(sections):
        drawings.append(f'<svg class="diagram" data-panel="{i}" viewBox="0 0 {WIDTH} {section["height"]}" xmlns="http://www.w3.org/2000/svg" aria-label="{esc(section["title"])}" {"hidden" if i else ""}><style>{SVG_STYLE}</style>{drawing(section,tables)}</svg>')
    template = (OUT / "schema-viewer.template.html").read_text(encoding="utf-8")
    replacements = {
        "__DIAGRAMS__": "".join(drawings),
        "__TABS__": "".join(f'<button class="tab {"active" if i == 0 else ""}" data-panel="{i}" role="tab" aria-selected="{"true" if i == 0 else "false"}">{esc(p["title"])}</button>' for i,p in enumerate(sections)),
        "__CATALOG__": json.dumps(tables, ensure_ascii=False).replace("<", "\\u003c"),
        "__PANELS__": json.dumps([{k: p[k] for k in ("title", "subtitle", "height")} for p in sections], ensure_ascii=False),
        "__TABLE_COUNT__": str(len(tables)-1),
        "__KEY_LEGEND__": esc(key_legend), "__OTHER_KEYS__": esc(other_keys),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    (OUT / "database-snowflake-schema.html").write_text(template, encoding="utf-8")
    write_gold_imports()
    print(f"Rendered {len(tables)-1} tables + 1 view across {len(sections)} diagrams to HTML and SVG, plus Gold imports.")


if __name__ == "__main__":
    main()
