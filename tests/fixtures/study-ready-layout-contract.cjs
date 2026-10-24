const assert = require('node:assert/strict');
const fs = require('node:fs');
const source = JSON.parse(fs.readFileSync(0, 'utf8'));

function fixture() {
  let now = 0, current = true, geometry = 1, snapshots = 0;
  const queue = [], payload = { dataset: { nativeState: 'preparing' } };
  const child = { width: 300, dataset: { studyChildSource: 'same-source', studyChildToken: 'same-token' },
    getBoundingClientRect() { return { width: this.width }; } };
  const proof = { ready: false, signature: 'same-source-layout', readySignature: null, readyWidth: 300 };
  const doc = {
    fonts: { status: 'loaded' },
    querySelectorAll(selector) {
      if (selector === 'iframe.etymology-source-frame') return [child];
      if (selector === 'script.anki-final-reviewed-data') return [payload];
      throw Error('Unexpected selector: ' + selector);
    },
    querySelector() { return { textContent: 'original native validation failure' }; },
  };
  const entry = { doc, win: { __ankiCigenFrames: { known: new Map([[child, proof]]) } } };
  const snapshot = (actual, includeText) => {
    assert.equal(actual, doc); assert.equal(includeText, false);
    snapshots++; return { geometry };
  };
  const wait = new Function('performance', 'requestAnimationFrame', 'snapshot', source + ';return waitPrepared;')(
    { now: () => now }, callback => queue.push(callback), snapshot);
  const promise = wait(entry, () => current);
  return {
    doc, child, payload, proof, promise,
    snapshots: () => snapshots,
    cancel() { current = false; },
    geometry(value) { geometry = value; },
    async step(at) { now = at === undefined ? now + 16 : at; assert.ok(queue.length); queue.shift()(); await Promise.resolve(); },
    ready() { payload.dataset.nativeState = 'ready'; proof.ready = true; proof.readySignature = proof.signature; },
  };
}

(async () => {
  let contracts = 0;
  {
    const f = fixture(); let completed = false; f.promise.then(() => { completed = true; });
    await f.step(); await f.step();
    assert.equal(f.snapshots(), 0, 'pending native/child readiness forced a whole-card geometry snapshot');
    f.payload.dataset.nativeState = 'ready'; await f.step();
    assert.equal(f.snapshots(), 0, 'pending child readiness forced a whole-card geometry snapshot');
    f.ready(); f.doc.fonts.status = 'loading'; await f.step();
    assert.equal(f.snapshots(), 0, 'pending fonts forced a whole-card geometry snapshot');
    f.doc.fonts.status = 'loaded';
    await f.step(); await f.step(); assert.equal(completed, false, 'committed before three stable samples');
    await f.step(); assert.equal(await f.promise, true); assert.equal(f.snapshots(), 3);
    contracts++;
  }
  {
    const f = fixture(); f.ready(); await f.step(); await f.step();
    f.geometry(2); await f.step(); await f.step();
    let completed = false; f.promise.then(() => { completed = true; });
    assert.equal(completed, false); await f.step(); assert.equal(await f.promise, true); contracts++;
  }
  {
    const f = fixture(); f.ready(); await f.step(); await f.step();
    f.proof.ready = false; await f.step(); assert.equal(f.snapshots(), 2);
    f.ready(); await f.step(); await f.step();
    let completed = false; f.promise.then(() => { completed = true; });
    assert.equal(completed, false, 'unready interval retained an earlier stable-sample streak');
    await f.step(); assert.equal(await f.promise, true); assert.equal(f.snapshots(), 5); contracts++;
  }
  {
    const f = fixture(); f.ready(); f.proof.readySignature = 'stale'; await f.step();
    assert.equal(f.snapshots(), 0); f.proof.readySignature = f.proof.signature; f.child.width = 305;
    await f.step(); assert.equal(f.snapshots(), 0);
    f.child.width = 300; await f.step(); await f.step(); await f.step();
    assert.equal(await f.promise, true); contracts++;
  }
  {
    const f = fixture(); const rejection = assert.rejects(f.promise, /original native validation failure/);
    f.payload.dataset.nativeState = 'failed'; await f.step(); await rejection;
    assert.equal(f.snapshots(), 0); contracts++;
  }
  {
    const f = fixture(); const error = Error('original child failed'), rejection = assert.rejects(f.promise, e => e === error);
    f.proof.error = error; await f.step(); await rejection; assert.equal(f.snapshots(), 0); contracts++;
  }
  {
    const f = fixture(); f.cancel(); await f.step(); assert.equal(await f.promise, false);
    assert.equal(f.snapshots(), 0); contracts++;
  }
  {
    const f = fixture(); const rejection = assert.rejects(f.promise, /Connected original card preparation timed out/);
    await f.step(10001); await rejection; assert.equal(f.snapshots(), 0); contracts++;
  }
  console.log(JSON.stringify({ contracts }));
})().catch(error => { console.error(error); process.exitCode = 1; });
