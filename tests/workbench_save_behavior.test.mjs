import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('wechat-article-pipeline/assets/workbench-save-controller.js', 'utf8');

test('cache recovery requires the original document, revision and content fingerprint', () => {
  const context = {};
  vm.runInNewContext(source, context);
  const current = {documentId: 'A', coreRevision: 2, contentFingerprint: 'new', markdown: '最新正文'};
  const stale = {documentId: 'A', baseRevision: 1, baseFingerprint: 'old', markdown: '旧稿修改'};
  assert.equal(context.reconcileWorkbenchCache(stale, current), 'conflict');
  assert.equal(context.reconcileWorkbenchCache({...stale, baseRevision: 2}, current), 'conflict');
  assert.equal(context.reconcileWorkbenchCache({...stale, baseRevision: 2, baseFingerprint: 'new'}, current), 'restore');
  assert.equal(context.reconcileWorkbenchCache({...stale, documentId: 'B'}, current), 'conflict');
  assert.equal(context.reconcileWorkbenchCache({markdown: '无版本旧缓存'}, current), 'conflict');
});

test('acknowledged cache records its saved revision without overwriting newer pending edits', async () => {
  const context = {setTimeout, clearTimeout};
  vm.runInNewContext(source, context);
  let resolve, value = 'first', cached;
  const controller = context.createWorkbenchSaveController({
    storage: {setItem(_key, raw) { cached = JSON.parse(raw); }},
    snapshot: () => ({markdown: value, documentId: 'A', baseRevision: 0, baseFingerprint: 'original'}),
    transport: () => new Promise(r => { resolve = r; }),
  });
  controller.saveNow();
  value = 'second'; controller.saveNow();
  resolve({saved: true, revision: 1, contentFingerprint: 'first-hash'});
  await new Promise(r => setTimeout(r, 0));
  assert.equal(cached.markdown, 'second');
  assert.equal(cached.baseRevision, 1);
  assert.equal(cached.baseFingerprint, 'first-hash');
  resolve({saved: true, revision: 2, contentFingerprint: 'second-hash'});
  await controller.flush();
  assert.equal(cached.baseRevision, 2);
});

function harness() {
  let now = 0, next = 1, timers = new Map(), calls = [], writes = [];
  const context = { setTimeout: (fn, ms) => { const id = next++; timers.set(id, {at: now + ms, fn}); return id; }, clearTimeout: id => timers.delete(id), console };
  vm.runInNewContext(source + '\nthis.createWorkbenchSaveController = createWorkbenchSaveController;', context);
  const storage = { setItem: (k,v) => writes.push([k,v]) };
  const transport = snapshot => { calls.push(snapshot); return Promise.resolve({saved:true}); };
  const controller = context.createWorkbenchSaveController({storage, storageKey:'k', snapshot:()=>({value: writes.length}), transport, now:()=>now});
  return {controller, calls, writes, tick(ms){ now += ms; for (const [id,t] of [...timers]) if (t.at <= now) { timers.delete(id); t.fn(); } }};
}

test('caches immediately and debounces server save for 3000ms', async () => {
  const h = harness(); h.controller.cacheAndSchedule(); assert.equal(h.writes.length, 1); h.tick(2999); assert.equal(h.calls.length, 0); h.tick(1); await Promise.resolve(); assert.equal(h.calls.length, 1);
});

test('manual save clears timer and later input arms a fresh timer', async () => {
  const h = harness(); h.controller.cacheAndSchedule(); h.controller.saveNow(); await Promise.resolve(); await Promise.resolve(); assert.equal(h.calls.length,1); h.tick(5000); assert.equal(h.calls.length,1); await Promise.resolve(); await Promise.resolve(); h.controller.cacheAndSchedule(); h.tick(3000); await Promise.resolve(); await Promise.resolve(); assert.equal(h.calls.length,2);
});

test('initial controller creation does not schedule or save', () => { const h = harness(); h.tick(10000); assert.equal(h.writes.length,0); assert.equal(h.calls.length,0); });

test('keeps only newest pending snapshot during an in-flight save', async () => {
  let resolveFirst; const calls = []; const states = [];
  const context = {setTimeout, clearTimeout}; vm.runInNewContext(source + '\nthis.createWorkbenchSaveController = createWorkbenchSaveController;', context);
  let value = 0;
  const transport = payload => { calls.push(payload); if (calls.length === 1) return new Promise(r => { resolveFirst = r; }); return Promise.resolve({saved:true}); };
  const c = context.createWorkbenchSaveController({storage:{setItem(){}}, snapshot:()=>({value:++value}), transport, onStateChange:s=>states.push(s)});
  c.cacheAndSchedule(); c.flush(); for (let i=0;i<20;i++) c.cacheAndSchedule();
  assert.equal(calls.length, 1); assert.equal(c.getState().pending, true); resolveFirst({saved:true}); await Promise.resolve(); await Promise.resolve();
  assert.notEqual(states.at(-1), 'saved'); await new Promise(r=>setTimeout(r,0)); await Promise.resolve();
  assert.equal(calls.length, 2); assert.equal(calls[1].value, 21);
});

test('failed transport never reports saved and resolves as an error state', async () => {
  const states = [];
  const context = {setTimeout, clearTimeout};
  vm.runInNewContext(source + '\nthis.createWorkbenchSaveController = createWorkbenchSaveController;', context);
  const controller = context.createWorkbenchSaveController({
    storage: {setItem() {}},
    snapshot: () => ({value: 1}),
    transport: () => Promise.resolve(false),
    onStateChange: state => states.push(state),
  });

  controller.saveNow();
  const result = await controller.flush();

  assert.equal(result.saved, false);
  assert.equal(states.includes('saved'), false);
  assert.equal(states.at(-1), 'error');
});
