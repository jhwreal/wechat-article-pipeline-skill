(function (global) {
  function createWorkbenchSaveController(options) {
    options = options || {};
    const clock = options.now || Date.now;
    const set = options.setTimeout || global.setTimeout;
    const clear = options.clearTimeout || global.clearTimeout;
    const storage = options.storage || global.localStorage;
    const key = options.storageKey || 'wechat-md-workbench-generated';
    const snapshot = options.snapshot || (() => ({}));
    const transport = options.transport || (() => Promise.resolve({saved:true}));
    let timer = null, mutation = 0, inFlight = null, pending = null, state = 'idle';
    function cacheAndSchedule() {
      const value = snapshot(); mutation += 1;
      try { if (storage && storage.setItem) storage.setItem(key, JSON.stringify(value)); } catch (_) {}
      pending = {value, id: mutation}; state = 'cached';
      if (timer !== null) clear(timer);
      timer = set(() => { timer = null; flush(); }, 3000);
      return value;
    }
    function saveNow() {
      const value = snapshot(); mutation += 1;
      try { if (storage && storage.setItem) storage.setItem(key, JSON.stringify(value)); } catch (_) {}
      pending = {value, id: mutation}; state = 'saving';
      if (timer !== null) { clear(timer); timer = null; }
      flush(); return value;
    }
    function flush() {
      if (inFlight || !pending) return inFlight;
      const item = pending; pending = null; inFlight = Promise.resolve(transport(item.value)).then(result => {
        if (item.id === mutation) state = 'saved';
        return result;
      }).catch(error => { if (item.id === mutation) state = 'error'; throw error; }).finally(() => { inFlight = null; if (pending) flush(); });
      return inFlight;
    }
    return { cacheAndSchedule, saveNow, flush, getState: () => ({state, mutation, pending: !!pending, inFlight: !!inFlight}) };
  }
  global.createWorkbenchSaveController = createWorkbenchSaveController;
})(typeof globalThis !== 'undefined' ? globalThis : this);
