"""Pending requests share work; completed requests can be run again."""

import json
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from torrentlinker.web.jobs import Jobs


def finished(jobs, identifier):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        row = jobs.get(identifier)
        if row["status"] not in {"queued", "running"}:
            return row
        time.sleep(0.005)
    raise AssertionError(f"Job did not finish: {row}")


@pytest.mark.parametrize("queued", [False, True])
def test_identical_scan_reuses_pending_job(tmp_path, queued):
    jobs = Jobs(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def block(stop, progress):
        entered.set()
        assert release.wait(5)

    def scan(stop, progress):
        calls.append("scan")
        if not queued:
            block(stop, progress)

    try:
        if queued:
            jobs.submit("blocker", block)
            assert entered.wait(2)
        first = jobs.submit("scan", scan)
        if not queued:
            assert entered.wait(2)
        second = jobs.submit("scan", scan)
        assert second == first
        assert len([row for row in jobs.list() if row["kind"] == "scan"]) == 1
        release.set()
        jobs.executor.shutdown(wait=True)
        assert calls == ["scan"]
    finally:
        release.set()
        jobs.close()


def test_pending_identity_includes_parameters_client_and_kind(tmp_path):
    jobs = Jobs(tmp_path)
    release = threading.Event()

    def work(stop, progress):
        return release.wait(5)

    try:
        first = jobs.submit("check", work, parameters={"path": "/a", "options": {"x": 1, "y": 2}})
        assert (
            jobs.submit("check", work, parameters={"options": {"y": 2, "x": 1}, "path": "/a"})
            == first
        )
        others = [
            jobs.submit("check", work, parameters={"path": "/b", "options": {"x": 1, "y": 2}}),
            jobs.submit("check", work, parameters={"path": "/a", "options": {"x": 2, "y": 2}}),
            jobs.submit(
                "check",
                work,
                parameters={"path": "/a", "options": {"x": 1, "y": 2}},
                client_id="remote",
            ),
            jobs.submit("scan", work, parameters={"path": "/a"}),
        ]
        assert len(set([first, *others])) == 5
    finally:
        release.set()
        jobs.close()


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled", "partial"])
def test_terminal_job_does_not_block_same_request(tmp_path, outcome):
    jobs = Jobs(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def work(stop, progress):
        entered.set()
        assert release.wait(5)
        if outcome == "failed":
            raise ValueError("Test failure")
        return {"partial": outcome == "partial"}

    try:
        first = jobs.submit("scan", work)
        assert entered.wait(2)
        if outcome == "cancelled":
            jobs.cancel(first)
        release.set()
        assert finished(jobs, first)["status"] == outcome
        second = jobs.submit("scan", work)
        assert second != first
        finished(jobs, second)
    finally:
        release.set()
        jobs.close()


def test_reuse_precedes_capacity_limit_and_is_atomic(tmp_path):
    jobs = Jobs(tmp_path)
    release = threading.Event()

    def work(stop, progress):
        assert release.wait(5)

    try:
        # All callers race while the worker remains occupied by the shared job.
        with ThreadPoolExecutor(max_workers=8) as callers:
            identifiers = list(callers.map(lambda _: jobs.submit("scan", work), range(16)))
        assert len(set(identifiers)) == 1
        for n in range(19):
            jobs.submit("check", work, parameters={"path": f"/{n}"})
        assert jobs.submit("scan", work) == identifiers[0]
        assert len(jobs.list()) == 20
        with pytest.raises(ValueError, match="Too many pending"):
            jobs.submit("check", work, parameters={"path": "/different"})
    finally:
        release.set()
        jobs.close()


def test_explicit_independent_work_is_not_reused(tmp_path):
    jobs = Jobs(tmp_path)
    release = threading.Event()
    try:
        first = jobs.submit("check", lambda s, p: release.wait(5), deduplicate=False)
        second = jobs.submit("check", lambda s, p: None, deduplicate=False)
        normal = jobs.submit("check", lambda s, p: None)
        assert len({first, second, normal}) == 3
    finally:
        release.set()
        jobs.close()


def test_request_parameters_are_not_in_job_history_or_diagnostics(tmp_path):
    jobs = Jobs(tmp_path)
    release = threading.Event()
    secret = "private-test-confirmation-token"
    try:
        identifier = jobs.submit(
            "check", lambda s, p: release.wait(5), parameters={"confirmation": secret}
        )
        assert secret not in str(jobs.get(identifier))
        assert secret not in str(jobs.list())
        assert secret not in str(jobs.diagnostic_rows())
    finally:
        release.set()
        jobs.close()
    assert secret.encode() not in (tmp_path / "jobs.sqlite").read_bytes()


@pytest.mark.parametrize(
    "reseed_visible,reseed_running,expected_refreshes",
    [(False, True, 0), (True, False, 0), (True, True, 4)],
)
def test_browser_tracks_the_existing_job_and_its_completion(
    reseed_visible, reseed_running, expected_refreshes
):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is unavailable")
    app = Path("src/torrentlinker/web/static/app.js").read_text()
    functions = app[app.index("async function job(") : app.index("async function loadJobs(")]
    script = r"""
const assert = require('node:assert/strict');
const state = {clientId:'default', jobs:new Map(), view:'library'};
const status = {dataset:{}};
const [reseedVisible,reseedRunning,expectedRefreshes] = JSON.parse(process.argv[2]);
const reseedUI = {job:reseedRunning ? 'reseed-job' : null};
const nodes = {'workspace':{hidden:false}, 'library-reseed':{hidden:!reseedVisible}};
const $ = id => nodes[id] || status;
let reseedRefreshes = 0;
async function loadReseed() { reseedRefreshes++; }
function catalogueJobs() {}
function planJobs() {}
function signedInMember() { return false; }
const say = en => en;
const toast = message => { throw new Error(message); };
let phase = 'running', completions = 0, updates = 0;
async function api(path, body) {
  if (body) return {id:'existing-job'};
  if (path === 'jobs') return [{id:'existing-job', kind:'scan', client_id:'default',
    status:phase, progress:{done:1}}];
  assert.equal(path, 'jobs/existing-job');
  return {status:phase, result:{items:7}};
}
eval(process.argv[1] + `
(async () => {
  const done = result => { assert.equal(result.items,7); completions++; };
  const progress = result => { assert.equal(result.done,1); updates++; };
  assert.equal(await job({kind:'scan'},done,null,progress), 'existing-job');
  assert.equal(await job({kind:'scan'},done,null,progress), 'existing-job');
  assert.equal(state.jobs.size,1);
  assert.equal(updates,2);
  phase='completed'; await pollJobs(); await pollJobs();
  assert.equal(completions,1);
  assert.equal(state.jobs.size,0);
  assert.equal(reseedRefreshes,expectedRefreshes);
})().catch(error => { console.error(error); process.exitCode=1; });
`);
"""
    result = subprocess.run(
        [
            node,
            "-e",
            script,
            functions,
            json.dumps([reseed_visible, reseed_running, expected_refreshes]),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
