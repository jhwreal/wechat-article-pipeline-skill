import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('wechat-article-pipeline/assets/workbench-save-controller.js', 'utf8');

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
