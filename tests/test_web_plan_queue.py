"""Large plans queue in bounded batches without exhausting pending job capacity."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_plan_queue_batches_selected_hashes_and_waits_for_each_client_job():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the web handler test")
    source = Path("src/torrentlinker/web/static/app.js").read_text()
    panel = Path("src/torrentlinker/web/static/plan.js").read_text()
    handler = panel[
        panel.index('window.addEventListener("message",') : panel.index(
            'window.addEventListener("resize"'
        )
    ]
    waiter = "async function waitForJob" + source.split("async function waitForJob", 1)[1]
    # Run the actual handler and completion polling, with only transport/UI stubbed.
    script = r"""
const assert = require('node:assert/strict');
const rows = Array.from({length: 21105}, (_, i) => ({
  hash: i.toString(16).padStart(40, '0'), client_id: i < 21001 ? 'home' : 'remote'
}));
const state = {clientId:'other'};
const location={origin:'https://fixture.test'};
let response,handler;
const planFrame={contentWindow:{postMessage:value=>{response=value;}}};
const window={addEventListener:(event,callback)=>{handler=callback;}};
const calls = [], guard = f => f(), loadQueue = () => {};
const control = {hidden:false}, $ = () => control, say = en => en;
let active = false, read = 0;
const job = async body => {
  assert.equal(active, false, 'previous batch must finish before another is submitted');
  assert(body.hashes.length <= 1000); calls.push(body); active = true; read = 0;
  return String(calls.length);
};
const api = async path => {
  if(path.startsWith('zen/plan?'))return {plan_id:'reviewed',
    rows:[...rows,{hash:'unselected',client_id:'home'}]};
  assert.equal(path, 'jobs/' + calls.length);
  if (++read === 1) return {status:'running'};
  active = false; return {status:'completed'};
};
const setTimeout = f => f();
const navigate = async view => {
  assert.equal(view, 'queue'); assert.equal(calls.length, 23); assert.equal(active, false);
};
eval(process.argv[2]);
(async () => {
  eval(process.argv[1]);
  await handler({source:planFrame.contentWindow,origin:location.origin,
    data:{type:'plan-request',id:1,path:'queue',
      body:{_client:'other',plan_id:'reviewed',hashes:rows.map(r=>r.hash)}}});
  assert.equal(response.error,undefined);
  assert.equal(response.value.queued,21105);
  assert.deepEqual(calls.slice(-2).map(c=>[c.client_id,c.hashes.length]),
    [['home',1],['remote',104]]);
  assert.deepEqual(calls.flatMap(c=>c.hashes), rows.map(r=>r.hash));
})().catch(error => { console.error(error); process.exitCode=1; });
"""
    subprocess.run(
        [node, "-e", script, handler, waiter], check=True, capture_output=True, text=True
    )


def test_queue_actions_batch_the_entire_selection_and_refresh_after_failure():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the web handler test")
    source = Path("src/torrentlinker/web/static/search/queue.js").read_text()
    handler = (
        "async function queueAction"
        + source.split("async function queueAction", 1)[1].split('\n$("start-queue")', 1)[0]
    )
    script = r"""
const assert = require('node:assert/strict');
const keys = Array.from({length: 2001}, (_, i) => String(i));
const calls = [];
let refreshed = 0, fail = false;
let queueSnapshot = "old";
const request = async (path, body) => {
  const batch = body.keys;
  assert(batch.length <= 1000);
  calls.push([path, batch]);
  if (fail) throw Error('busy');
};
const loadQueue = async () => { refreshed++; };
eval(process.argv[1]);
(async () => {
  await queueAction('remove', {keys});
  assert.deepEqual(calls.map(c => c[1].length), [1000, 1000, 1]);
  assert.deepEqual(calls.flatMap(c => c[1]), keys);
  assert(calls.every(c => c[0] === 'remove'));
  assert.equal(refreshed, 1);
  fail = true;
  await assert.rejects(queueAction('retry', {keys}), /busy/);
  assert.equal(calls.at(-1)[0], 'retry');
  assert.equal(refreshed, 2);
})().catch(error => { console.error(error); process.exitCode=1; });
"""
    subprocess.run([node, "-e", script, handler], check=True, capture_output=True, text=True)
