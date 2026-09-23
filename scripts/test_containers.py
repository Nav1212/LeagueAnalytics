"""Run deployment checks using disposable Compose project volumes, never live data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not shutil.which("docker"):
        raise SystemExit("Docker is required for container isolation tests; no checks were run.")
    project = "championgg-test-" + uuid.uuid4().hex[:12]
    env = {**os.environ, "CHAMPIONGG_PORT": "0", "RIOT_API_KEY": ""}
    def compose(*args):
        return subprocess.check_output(["docker", "compose", "-p", project, *args], cwd=ROOT, env=env, text=True)
    try:
        print(compose("build", "processor", "api"), flush=True)
        compose("run", "--rm", "--entrypoint", "python", "processor", "-m", "processor.test_fixtures", "/data/gold", "container-fixture")
        compose("up", "-d", "api")
        address = compose("port", "api", "8000").strip()
        origin = "http://" + address
        for attempt in range(30):
            try:
                with urllib.request.urlopen(origin + "/api/meta", timeout=2) as response:
                    assert json.load(response)["runId"] == "container-fixture"
                break
            except OSError:
                if attempt == 29: raise
                time.sleep(1)
        for endpoint in ["/", "/api/meta", "/api/champions", "/api/champion/Ahri", "/api/search?q=ahri", "/api/static/runes"]:
            with urllib.request.urlopen(origin + endpoint, timeout=5) as response:
                assert response.status == 200
        script = """
            import assert from 'node:assert/strict';
            import fs from 'node:fs';
            import {DatabaseSync} from 'node:sqlite';
            assert.equal(process.env.RIOT_API_KEY, undefined);
            assert.equal(fs.existsSync('/data/private'), false);
            assert.equal(fs.existsSync('/app/processor'), false);
            assert.throws(()=>fs.writeFileSync('/data/gold/write-probe','forbidden'), /EROFS|EACCES/);
            const manifest=JSON.parse(fs.readFileSync('/data/gold/current.json','utf8'));
            const db=new DatabaseSync('/data/gold/'+manifest.snapshot,{readOnly:true});
            assert.throws(()=>db.exec('DELETE FROM gold_champions'), /readonly/i);
            assert.throws(()=>db.prepare('SELECT * FROM bronze_matches').all(), /no such table/i);
            db.close();
        """
        compose("exec", "-T", "api", "node", "--input-type=module", "-e", script)
        print("Container endpoint and storage isolation checks passed.")
    finally:
        # Only this invocation's unique project and generated fixture volumes.
        compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
