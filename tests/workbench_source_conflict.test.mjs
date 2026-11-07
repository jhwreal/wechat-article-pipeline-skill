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
    showPersistenceWarning: (message, reason) => warnings.push({message, reason}),
  };
  vm.runInNewContext(saveFunction, context);
  assert.equal(await context.saveStateToServer({ markdown: '浏览器未保存的改稿' }), false);
  assert.match(warnings[0].message, /保留本页草稿/);
  assert.match(warnings[0].message, /最新 Markdown 重新打包/);
  assert.equal(warnings[0].reason, 'conflict');
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
    showPersistenceWarning: (message, reason) => warnings.push({message, reason}),
    markPersistenceReady: () => { enabled = true; },
    reconcileWorkbenchCache: () => { restored = true; },
  };
  vm.runInNewContext(handshakeFunction, context);
  assert.equal(await context.handshakeWorkbench(), false);
  assert.equal(enabled, false);
  assert.equal(restored, false);
  assert.match(warnings[0].message, /最新 Markdown 重新打包/);
  assert.equal(warnings[0].reason, 'conflict');
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

test('conflict warning distinguishes a running service from a connection failure', () => {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {});
    return elements.get(id);
  };
  let editable = true;
  const context = {
    document: { getElementById: element },
    persistenceReady: true,
    setEditingEnabled: value => { editable = value; },
    persistenceWarningMessage: {}, persistenceWarning: {}, saveStatus: {},
    articleStatus: {}, manifestStatus: {}, storageModeLabel: {},
  };
  vm.runInNewContext(template.slice(template.indexOf('function showPersistenceWarning('),
    template.indexOf('function markPersistenceReady(')), context);
  context.showPersistenceWarning('保留本页草稿', 'conflict');
  assert.equal(editable, false);
  assert.equal(context.persistenceReady, false);
  assert.match(element('persistenceWarningTitle').textContent, /版本冲突/);
  assert.match(element('persistenceWarningHint').textContent, /保存服务仍在运行/);
  assert.equal(context.storageModeLabel.textContent, '只读：版本冲突');
  context.showPersistenceWarning('连接中断');
  assert.match(element('persistenceWarningTitle').textContent, /加载失败/);
  assert.match(context.storageModeLabel.textContent, /未连接/);
});
