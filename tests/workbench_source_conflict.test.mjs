import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { loadWorkbenchTemplate } from './workbench-template.mjs';

const template = loadWorkbenchTemplate();
const saveFunction = template.slice(
  template.indexOf('async function saveStateToServer('),
  template.indexOf('async function handshakeWorkbench(')
);
const handshakeFunction = template.slice(
  template.indexOf('async function handshakeWorkbench('),
  template.indexOf('function updateServerStatus(')
);

test('source-file save conflicts preserve the draft revision and require repackaging', async () => {
  const warnings = [];
  const context = {
    window: { __workbenchRevision: 7, __workbenchFingerprint: 'original' },
    isLoopbackServer: () => true,
    persistenceReady: true,
    WORKBENCH_SAVE_ENDPOINT: '/save',
    fetch: async () => ({ status: 409, json: async () => ({ sourceConflict: true, coreRevision: 8 }) }),
    showPersistenceWarning: message => warnings.push(message),
  };
  vm.runInNewContext(saveFunction, context);
  assert.equal(await context.saveStateToServer({ markdown: '浏览器未保存的改稿' }), false);
  assert.match(warnings[0], /保留本页草稿/);
  assert.match(warnings[0], /最新 Markdown 重新打包/);
  assert.equal(context.window.__workbenchRevision, 7);
  assert.equal(context.window.__workbenchFingerprint, 'original');
});

test('reopening a stale workbench cannot enable editing or restore cached edits', async () => {
  const warnings = [];
  let enabled = false;
  let restored = false;
  const context = {
    window: {},
    BOOTSTRAP: { documentId: 'A', baseRevision: 7, baseFingerprint: 'original' },
    location: { pathname: '/a.html' },
    isLoopbackServer: () => true,
    fetch: async () => ({ ok: true, json: async () => ({
      documentId: 'A', documentPath: '/a.html', coreRevision: 7,
      contentFingerprint: 'original', sourceConflict: true,
    }) }),
    showPersistenceWarning: message => warnings.push(message),
    markPersistenceReady: () => { enabled = true; },
    reconcileWorkbenchCache: () => { restored = true; },
  };
  vm.runInNewContext(handshakeFunction, context);
  assert.equal(await context.handshakeWorkbench(), false);
  assert.equal(enabled, false);
  assert.equal(restored, false);
  assert.match(warnings[0], /最新 Markdown 重新打包/);
  assert.equal(context.window.__workbenchRevision, undefined);
});

test('ordinary revision conflicts keep the existing reload guidance', async () => {
  const warnings = [];
  const context = {
    window: {}, isLoopbackServer: () => true, persistenceReady: true,
    WORKBENCH_SAVE_ENDPOINT: '/save',
    fetch: async () => ({ status: 409, json: async () => ({ coreRevision: 8 }) }),
    showPersistenceWarning: message => warnings.push(message),
  };
  vm.runInNewContext(saveFunction, context);
  assert.equal(await context.saveStateToServer({ markdown: '旧页面' }), false);
  assert.match(warnings[0], /重新打开服务地址/);
});
