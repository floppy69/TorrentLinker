"""Persistent job subjects and lane-aware queue metadata for reconnecting pages."""

import json
import threading

from tests.test_job_lanes import finished
from torrentlinker.web.jobs import Jobs


def test_subjects_survive_restart_but_never_enter_diagnostics(tmp_path):
    jobs = Jobs(tmp_path)
    parameters = {
        "path": "/library/private-title.mkv",
        "hashes": ["a" * 40],
        "draft_id": "draft-1",
        "confirmation": "secret-confirmation",
        "torrent_data": "secret-torrent",
        "candidate_key": "https://tracker.invalid/download?apikey=secret",
        "upload": {"api_key": "secret"},
    }
    identifier = jobs.submit("details", lambda *_: {}, parameters=parameters)
    assert finished(jobs, identifier)["subject"] == {
        "kind": "details",
        "path": parameters["path"],
        "hashes": parameters["hashes"],
        "draft_id": "draft-1",
    }
    assert "secret" not in json.dumps(jobs.list())
    assert "private-title" not in json.dumps(jobs.diagnostic_rows())
    jobs.close()
    reopened = Jobs(tmp_path)
    try:
        assert reopened.list()[0]["subject"]["path"] == parameters["path"]
        assert set(reopened.diagnostic_rows()[0]) == {"kind", "status", "client_id"}
    finally:
        reopened.close()


def test_waiting_job_identifies_predecessor_in_its_own_lane(tmp_path):
    jobs = Jobs(tmp_path)
    release = threading.Event()
    started = threading.Event()

    def batch(stop, report):
        report({"done": 2, "total": 10})
        started.set()
        release.wait(5)

    try:
        first = jobs.submit("scan", batch, client_id="studio")
        assert started.wait(2)
        second = jobs.submit("reseed", lambda *_: {}, client_id="seedbox")
        third = jobs.submit("manage", lambda *_: {})
        interactive = jobs.submit("details", lambda *_: {})
        assert finished(jobs, interactive)["status"] == "completed"
        rows = {r["id"]: r for r in jobs.list()}
        assert rows[second]["queue_position"] == 1
        assert rows[second]["waiting_for"] == {"id": first, "kind": "scan", "client_id": "studio"}
        assert rows[third]["queue_position"] == 2
        assert rows[third]["waiting_for"]["id"] == second
        assert rows[first]["progress"] == {"done": 2, "total": 10}
    finally:
        release.set()
        jobs.close()


def test_pending_jobs_remain_visible_after_many_interactive_completions(tmp_path):
    jobs = Jobs(tmp_path)
    release = threading.Event()
    started = threading.Event()

    def held(*_):
        started.set()
        release.wait(10)

    try:
        first = jobs.submit("scan", held)
        assert started.wait(2)
        queued = jobs.submit("reseed", lambda *_: {})
        for number in range(105):
            identifier = jobs.submit("details", lambda *_: {}, parameters={"path": str(number)})
            finished(jobs, identifier)
        rows = {row["id"]: row for row in jobs.list()}
        assert first in rows
        assert rows[queued]["waiting_for"]["id"] == first
        assert rows[queued]["queue_position"] == 1
        assert len(rows) == 102
    finally:
        release.set()
        jobs.close()


def test_recovery_reconnect_reads_existing_job_without_replaying_mutation():
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    source = Path("src/torrentlinker/web/static/reseed/recovery.js").read_text()
    function = source[
        source.index("async function recoveryJob(") : source.index("async function openRecovery(")
    ]
    script = r"""
const assert = require("node:assert/strict");
const calls = [];
const recoveryCurrent = () => true;
const drawRecovery = () => {};
const api = async (action, body) => {
  calls.push([action,body]);
  return {status:"completed",progress:{done:1,total:1},result:{id:"repair-1",status:"ready"}};
};
eval(process.argv[1] + `
(async () => {
  const state = {busy:false,row:{id:"repair-1"}};
  await recoveryJob(state, "prepare-repair", {}, "existing-job");
  assert.deepEqual(calls, [["recovery-job",{id:"existing-job"}]]);
  assert.equal(state.row.status, "ready");
  assert.equal(state.busy, false);
})().catch(error => {console.error(error);process.exitCode=1;});
`);
"""
    result = subprocess.run(
        [node, "-e", script, function], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
