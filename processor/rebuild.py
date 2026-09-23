"""Full-dataset DuckDB rebuilds with gated, atomic SQLite publication."""
from __future__ import annotations

import argparse
import gzip
import datetime as dt
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

import duckdb
import psutil
import requests

from . import db, staging, gold
from .gold import SERVING_KEYS
from .silver_models import VERSION, models

EXTENSIONS = db.REPO_ROOT / 'data' / 'extensions'
BRONZE_TABLES = ('bronze_fetch_runs','bronze_fetch_errors','bronze_payloads',
                 'bronze_payload_observations','bronze_matches','bronze_match_timelines')
INPUT_TABLES = BRONZE_TABLES + ('champions','meta')
SERVING = tuple(SERVING_KEYS)


def setup() -> None:
    """The only transform-related command allowed to download an extension."""
    EXTENSIONS.mkdir(parents=True,exist_ok=True)
    c = duckdb.connect(config={'extension_directory':str(EXTENSIONS)})
    try:
        platform=c.execute('PRAGMA platform').fetchone()[0]
        target=EXTENSIONS / ('v'+duckdb.__version__) / platform / 'sqlite_scanner.duckdb_extension'
        if not target.exists():
            url=f'https://extensions.duckdb.org/v{duckdb.__version__}/{platform}/sqlite_scanner.duckdb_extension.gz'
            response=requests.get(url,timeout=120)
            response.raise_for_status()
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_suffix('.download')
            temporary.write_bytes(gzip.decompress(response.content))
            temporary.replace(target)
        # DuckDB verifies the official extension signature when loading it.
        c.execute('LOAD sqlite')
        print(f'DuckDB {duckdb.__version__}; sqlite extension provisioned in {EXTENSIONS}')
    finally:
        c.close()


class SQLSession:
    """Retain executable SQL with each run for reproducibility and inspection."""
    def __init__(self, conn, file):
        self.conn,self.file = conn,file

    def execute(self, sql, parameters=None):
        self.file.write(sql.rstrip(';')+';\n\n')
        self.file.flush()
        return self.conn.execute(sql,parameters) if parameters is not None else self.conn.execute(sql)


class Monitor:
    def __init__(self, folder):
        self.folder=folder
        self.peak_rss=0
        self.peak_spill=0
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.sample,daemon=True)

    def sample(self):
        process=psutil.Process()
        while not self.stop.is_set():
            self.peak_rss=max(self.peak_rss,process.memory_info().rss)
            try:
                size=sum(p.stat().st_size for p in self.folder.rglob('*') if p.is_file()) if self.folder.exists() else 0
                self.peak_spill=max(self.peak_spill,size)
            except OSError:
                pass
            self.stop.wait(.05)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self,*args):
        self.stop.set()
        self.thread.join()


def capture(database: Path, snapshot: Path):
    """One SQLite transaction; SQL copies only inputs, never Python row objects."""
    c=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
    try:
        c.execute('ATTACH DATABASE ? AS snapshot',(str(snapshot),))
        c.execute('BEGIN')
        for table in INPUT_TABLES:
            c.execute(f'CREATE TABLE snapshot.{table} AS SELECT * FROM main.{table}')
        c.commit()
    finally:
        c.close()


def issue_count(c):
    return c.execute("SELECT count(*) FROM silver_quality_issues WHERE severity IN ('error','pending')").fetchone()[0]


def validate(c, registry):
    """Bulk constraints on immutable analytical tables; failure gates publication."""
    for model in registry:
        table='silver_'+model.name
        key=','.join('"'+k+'"' for k in model.key)
        nulls=' OR '.join('"'+k+'" IS NULL' for k in model.key)
        # Platform may be absent from incomplete source payloads. It remains data,
        # but cannot silently form a valid static-resolution key.
        n=c.execute(f'SELECT count(*) FROM {table} WHERE {nulls}').fetchone()[0]
        duplicate=c.execute(f'SELECT count(*) FROM (SELECT {key} FROM {table} GROUP BY {key} HAVING count(*)>1)').fetchone()[0]
        for rule,count in [('null_key',n),('duplicate_key',duplicate)]:
            if count:
                c.execute(f"INSERT INTO silver_quality_issues VALUES ('error',NULL,{staging.literal(table)},{staging.literal(rule)},{staging.literal(str(count)+' offending rows/groups')})")
        for child,parent,targets in model.references:
            exists=' AND '.join(f'c."{a}"=p."{b}"' for a,b in zip(child,targets))
            nonnull=' AND '.join(f'c."{a}" IS NOT NULL' for a in child)
            n=c.execute(f'SELECT count(*) FROM {table} c WHERE {nonnull} AND NOT EXISTS (SELECT 1 FROM silver_{parent} p WHERE {exists})').fetchone()[0]
            if n:
                c.execute(f"INSERT INTO silver_quality_issues VALUES ('error',NULL,{staging.literal(table)},'orphan_reference',{staging.literal(str(n)+' rows reference '+parent)})")
    checks = [
        ('participant_coverage',"SELECT (SELECT count(*) FROM silver_match_participants)<>(SELECT coalesce(sum(len(doc.info.participants)),0) FROM _matches)"),
        ('team_coverage',"SELECT (SELECT count(*) FROM silver_match_teams)<>(SELECT coalesce(sum(len(doc.info.teams)),0) FROM _matches)"),
        ('frame_coverage',"SELECT (SELECT count(*) FROM silver_timeline_frames)<>(SELECT coalesce(sum(len(doc.info.frames)),0) FROM _timelines)"),
        ('gold_match_counts',"SELECT (SELECT coalesce(sum(matches),0) FROM gold_patch_totals)<>(SELECT count(*) FROM silver_matches WHERE queue_id=420 AND duration_seconds>=300)"),
        ('gold_player_counts',"SELECT (SELECT coalesce(sum(games),0) FROM gold_champion_stats)<>(SELECT count(*) FROM _eligible_players)"),
    ]
    for rule,sql in checks:
        if c.execute(sql).fetchone()[0]:
            c.execute(f"INSERT INTO silver_quality_issues VALUES ('error',NULL,'$',{staging.literal(rule)},'Source/output reconciliation failed')")
    for name in SERVING:
        key=','.join(SERVING_KEYS[name])
        if c.execute(f'SELECT count(*) FROM (SELECT {key} FROM gold_{name} GROUP BY {key} HAVING count(*)>1)').fetchone()[0]:
            c.execute(f"INSERT INTO silver_quality_issues VALUES ('error',NULL,'gold_{name}','duplicate_key','Duplicate serving key')")


def cleanup(database, output):
    """Only known generated completed snapshots; never traverse arbitrary paths."""
    c=sqlite3.connect(database)
    try:
        candidates=c.execute("SELECT snapshot_path FROM rebuild_runs WHERE status='complete' ORDER BY completed_at DESC,run_id DESC").fetchall()[2:]
    finally:
        c.close()
    root=output.resolve()
    for (path,) in candidates:
        candidate=Path(path).resolve()
        if candidate.parent.parent != root or candidate.name!='analytics.duckdb':
            continue
        try:
            # Unlink only known generated files. Open Windows readers defer cleanup.
            candidate.unlink(missing_ok=True)
        except OSError:
            continue


def rebuild(database=None, *, output_dir=None, threads=None, memory_limit=None, spill_directory=None, publish_result=True):
    database=Path(database or db.db_path()).resolve()
    output=Path(output_dir or database.parent/'analytics').resolve()
    output.mkdir(parents=True,exist_ok=True)
    run_id=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:10]
    folder=output/run_id
    folder.mkdir()
    analytics=folder/'analytics.duckdb'
    snapshot=folder/'inputs.sqlite'
    spill=Path(spill_directory).resolve()/run_id if spill_directory else folder/'spill'
    spill.mkdir(parents=True,exist_ok=True)
    report={'run_id':run_id,'transform_version':VERSION,'status':'running','stages_seconds':{},'snapshot_path':str(analytics)}
    start=time.perf_counter()
    conn=None
    with db.writer_lock(database),Monitor(spill) as monitor:
        control=sqlite3.connect(database)
        db.init_schema(control)
        # The writer lock proves no earlier rebuild is still active. Recover
        # audit state left by a killed process without touching its inputs.
        control.execute("UPDATE rebuild_runs SET status='failed',completed_at=?,error=? WHERE status='running'",
                        (db.utcnow(), 'Previous rebuild interrupted before completion'))
        control.execute('INSERT INTO rebuild_runs(run_id,started_at,status,snapshot_path) VALUES (?,?,?,?)',(run_id,db.utcnow(),'running',str(analytics)))
        control.commit()
        try:
            tick=time.perf_counter()
            capture(database,snapshot)
            report['stages_seconds']['input_capture']=time.perf_counter()-tick
            config={'extension_directory':str(EXTENSIONS),'autoinstall_known_extensions':'false','autoload_known_extensions':'false',
                    'preserve_insertion_order':'false',
                    'memory_limit':memory_limit or str(int(psutil.virtual_memory().total*.6))+'B','temp_directory':str(spill)}
            if threads is not None:
                if threads<1: raise ValueError('threads must be positive')
                config['threads']=str(threads)
            conn=duckdb.connect(str(analytics),config=config)
            report['configuration']={'duckdb_version':duckdb.__version__,**config}
            with (folder/'executed.sql').open('w',encoding='utf-8') as audit:
                c=SQLSession(conn,audit)
                try:
                    c.execute('LOAD sqlite')
                except duckdb.Error as exc:
                    raise RuntimeError('SQLite extension unavailable. Run python -m processor.main setup before rebuilding; rebuilds never download extensions.') from exc
                c.execute(f"ATTACH {staging.literal(snapshot)} AS input_db (TYPE SQLITE, READ_ONLY)")
                tick=time.perf_counter()
                for table in INPUT_TABLES:
                    c.execute(f'CREATE TABLE {table} AS SELECT * FROM input_db.{table}')
                c.execute('DETACH input_db')
                snapshot.unlink()
                c.execute(f"CREATE TEMP TABLE _run AS SELECT {staging.literal(run_id)} AS run_id,{staging.literal(VERSION)} AS transform_version")
                staging.stage(c)
                report['stages_seconds']['load_and_parse']=time.perf_counter()-tick
                registry=models()
                tick=time.perf_counter()
                for model in registry:
                    c.execute(model.sql)
                report['stages_seconds']['silver']=time.perf_counter()-tick
                tick=time.perf_counter()
                c.execute((Path(__file__).parent/'sql'/'v1'/'gold.sql').read_text(encoding='utf-8'))
                report['stages_seconds']['gold']=time.perf_counter()-tick
                tick=time.perf_counter()
                validate(c,registry)
                report['stages_seconds']['validation']=time.perf_counter()-tick
                report['issues']={row[0]:row[1] for row in c.execute('SELECT severity,count(*) FROM silver_quality_issues GROUP BY severity').fetchall()}
                report['row_counts']={m.name:c.execute(f'SELECT count(*) FROM silver_{m.name}').fetchone()[0] for m in registry}
                report['input_counts']={t:c.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in BRONZE_TABLES}
                report['status']='partial' if issue_count(c) else 'validated'
                c.execute(f"CREATE TABLE silver_transform_runs AS SELECT *,{staging.literal(report['status'])} AS status FROM _run")
                for table in INPUT_TABLES:
                    c.execute(f'DROP TABLE {table}')
                c.execute('CHECKPOINT')
            conn.close()
            conn=None
            if report['status']=='validated' and publish_result:
                tick=time.perf_counter()
                report['publication'] = gold.publish(analytics,run_id)
                report['stages_seconds']['publication']=time.perf_counter()-tick
                report['status']='complete'
                cleanup(database,output)
        except BaseException as exc:
            report['status']='failed'
            report['error']=str(exc)
            raise
        finally:
            if conn is not None: conn.close()
            report.update(total_seconds=time.perf_counter()-start,peak_rss_bytes=monitor.peak_rss,peak_spill_bytes=monitor.peak_spill,
                          output_bytes=analytics.stat().st_size if analytics.exists() else 0)
            (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            control.execute('UPDATE rebuild_runs SET status=?,completed_at=?,report_json=?,error=? WHERE run_id=?',
                (report['status'],db.utcnow(),json.dumps(report),report.get('error'),run_id))
            control.commit()
            control.close()
    print(f"Rebuild {run_id}: {report['status']} in {report['total_seconds']:.2f}s; {analytics}")
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--setup',action='store_true')
    args=parser.parse_args()
    setup() if args.setup else rebuild()
