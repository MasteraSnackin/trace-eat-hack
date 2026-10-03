import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const sources = Object.fromEntries(await Promise.all(['client', 'app', 'display'].map(async (name) => [name, await readFile(new URL(`../static/${name}.js`, import.meta.url), 'utf8')])));
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };
const tick = () => new Promise((done) => setImmediate(done));
const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
const state = (extra = {}) => ({ camera_active: false, session_id: null, current_zone: null, dwell_s: 0, zone_totals: {}, visits: 0, events: [], offer: { title: 'General message', detail: 'Explore the shelf.', zone: null }, ...extra });
const config = { shelf_width_m: 1.2, shelf_height_m: 0.6, camera_height_m: 0.3 };

function environment(fetch) {
  let nextTimer = 1;
  const timers = new Map();
  const intervals = new Map();
  const elements = new Map();
  const drawing = new Proxy({}, { get: (_, key) => key === 'clearRect' ? () => {} : () => {} });
  function element(id = '') {
    const classes = new Set();
    return {
      id, textContent: '', value: '', disabled: false, style: {}, dataset: {}, attributes: {}, children: [], listeners: {},
      classList: { add: (v) => classes.add(v), remove: (v) => classes.delete(v), toggle: (v, active) => active ? classes.add(v) : classes.delete(v), contains: (v) => classes.has(v) },
      addEventListener(type, fn) { this.listeners[type] = fn; },
      setAttribute(key, value) { this.attributes[key] = value; },
      getContext: () => drawing,
      replaceChildren() { this.children = []; },
      append(...children) { this.children.push(...children); },
      play: async () => {}, videoWidth: 640, videoHeight: 480,
      toBlob: (callback) => callback({ type: 'image/jpeg' }),
    };
  }
  const get = (id) => { if (!elements.has(id)) elements.set(id, element(id)); return elements.get(id); };
  get('config-form').elements = Object.entries(config).map(([name, value]) => ({ name, value }));
  const document = {
    getElementById: get,
    createElement: (tag) => element(tag),
    querySelector: (selector) => get(selector),
    querySelectorAll: () => ['left', 'centre', 'right'].map((zone) => get(`[data-zone="${zone}"]`)),
    body: { dataset: {} },
  };
  const context = vm.createContext({
    document, window: { listeners: {}, addEventListener(type, callback) { this.listeners[type] = callback; } }, navigator: { sendBeacon: () => true }, console,
    fetch, AbortController, DOMException, TypeError, performance: { now: () => 10000 },
    FormData: class { constructor(form) { this.entries = form.elements.map(({ name, value }) => [name, value]); } [Symbol.iterator]() { return this.entries[Symbol.iterator](); } },
    setTimeout(fn, delay) { const id = nextTimer++; timers.set(id, { fn, delay }); return id; },
    clearTimeout: (id) => timers.delete(id),
    setInterval(fn, delay) { const id = nextTimer++; intervals.set(id, { fn, delay }); return id; },
    clearInterval: (id) => intervals.delete(id),
  });
  vm.runInContext(sources.client, context);
  return {
    context, get, document, timers, intervals,
    load: (name) => vm.runInContext(sources[name], context),
    run: (code) => vm.runInContext(code, context),
    timeout(delay) { const entry = [...timers].find(([, value]) => value.delay === delay); assert.ok(entry, `Timer ${delay} exists`); timers.delete(entry[0]); entry[1].fn(); },
    interval(delay) { const entry = [...intervals.values()].find((value) => value.delay === delay); assert.ok(entry); entry.fn(); },
  };
}

test('a hung JSON request times out, aborts transport and releases its timer', async () => {
  let signal;
  const env = environment((_, options) => { signal = options.signal; return new Promise(() => {}); });
  const pending = env.run("TraceClient.requestJSON('/api/status', { timeoutMs: 12 })");
  const rejected = assert.rejects(pending, (error) => error.code === 'REQUEST_TIMEOUT');
  env.timeout(12);
  await rejected;
  assert.equal(signal.aborted, true);
  assert.equal(env.timers.size, 0);
});

test('external cancellation is distinct from a service timeout', async () => {
  const env = environment(() => new Promise(() => {}));
  const controller = new AbortController();
  env.context.externalSignal = controller.signal;
  const pending = env.run("TraceClient.requestJSON('/api/infer', { signal: externalSignal })");
  const rejected = assert.rejects(pending, (error) => error.name === 'AbortError');
  controller.abort();
  await rejected;
  assert.equal(env.timers.size, 0);
});

test('validation details and backend codes survive the browser request helper', async () => {
  const env = environment(async () => response({ code: 'INVALID_CONFIG', detail: [{ loc: ['body', 'camera_height_m'], msg: 'Camera height must be within the shelf height.' }] }, 422));
  await assert.rejects(env.run("TraceClient.requestJSON('/api/config')"), (error) => error.status === 422 && error.code === 'INVALID_CONFIG' && error.message.includes('camera height m: Camera height must be within the shelf height.'));
});

test('malformed successful JSON does not become a fabricated empty state', async () => {
  const env = environment(async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('Bad JSON'); } }));
  await assert.rejects(env.run("TraceClient.requestJSON('/api/state')"), (error) => error.code === 'INVALID_RESPONSE');
});

test('customer display drops a stale offer after a hung poll and recovers next poll', async () => {
  let calls = 0;
  const active = state({ camera_active: true, offer: { title: 'Bar offer', detail: 'Demo only.', zone: 'left' } });
  const env = environment(() => ++calls === 2 ? new Promise(() => {}) : Promise.resolve(response(active)));
  env.load('display');
  await tick();
  assert.equal(env.get('display-title').textContent, 'Bar offer');
  env.interval(500);
  env.timeout(2000);
  await tick();
  assert.equal(env.get('display-title').textContent, 'Find your next favourite.');
  assert.equal(env.document.body.dataset.zone, '');
  assert.equal(env.get('display-status').textContent, 'Local connection paused');
  env.interval(500);
  await tick();
  assert.equal(env.get('display-title').textContent, 'Bar offer');
});

test('a late setup response preserves edits made while saving', async () => {
  const saved = deferred();
  const env = environment((path) => path === '/api/config' ? saved.promise : Promise.resolve(response({ ready: true, config, state: state() })));
  env.load('app');
  await tick();
  const form = env.get('config-form');
  const save = form.listeners.submit({ preventDefault() {}, currentTarget: form });
  form.elements[0].value = 2.4;
  form.listeners.input();
  saved.resolve(response(config));
  await save;
  assert.equal(form.elements[0].value, 2.4);
  assert.match(env.get('config-feedback').textContent, /newer edits are not saved/);
  assert.equal(env.get('save-config').disabled, false);
  assert.equal(form.attributes['aria-busy'], 'false');
});

test('stop disables restart until acknowledged and clears the visible offer immediately', async () => {
  const stopped = deferred();
  const env = environment((path) => path === '/api/stop' ? stopped.promise : Promise.resolve(response({ ready: true, config, state: state() })));
  env.load('app');
  await tick();
  env.run("running = true; renderOffer({ title: 'Old offer', zone: 'left' });");
  const pending = env.run('stopCamera()');
  assert.equal(env.get('start-camera').disabled, true);
  assert.equal(env.get('offer-title').textContent, 'Find your next favourite.');
  stopped.resolve(response(state()));
  await pending;
  assert.equal(env.get('start-camera').disabled, false);
});

test('a status response captured before reset cannot restore an old visit', async () => {
  const status = deferred();
  const env = environment((path) => path === '/api/status' ? status.promise : Promise.resolve(response(state())));
  env.load('app');
  await env.get('reset-run').listeners.click();
  status.resolve(response({ ready: true, config, state: state({ session_id: 'Visit 999', dwell_s: 9 }) }));
  await tick();
  assert.equal(env.get('session-id').textContent, 'No active visit');
  assert.equal(env.get('current-dwell').textContent, '0.0');
});

test('a missing encoded frame stops capture instead of leaving a frozen live indicator', async () => {
  const env = environment(async () => response({ ready: true, config, state: state() }));
  env.load('app');
  await tick();
  env.run('running = true; capture.toBlob = (callback) => callback(null);');
  await env.run('inferFrame(generation)');
  assert.equal(env.get('camera-status').textContent, 'Camera off');
  assert.match(env.get('service-banner').textContent, /could not encode/);
});

test('current gaze and offer are cleared when the last observation becomes stale', async () => {
  const env = environment(async () => response({ ready: true, config, state: state() }));
  env.load('app');
  await tick();
  env.run("running = true; lastObservationAt = 8000; renderOffer({ title: 'Old offer', zone: 'left' });");
  env.interval(250);
  assert.equal(env.get('observation-title').textContent, 'Waiting for a fresh observation');
  assert.equal(env.get('offer-title').textContent, 'Find your next favourite.');
  assert.equal(env.get('current-dwell').textContent, '0.0');
});

test('an expired inference clears the old offer and schedules the next frame', async () => {
  const env = environment(async (path) => path === '/api/infer' ? response({ detail: 'Frame expired.', code: 'frame_expired' }, 409) : response({ ready: true, config, state: state() }));
  env.load('app');
  await tick();
  env.run("running = true; renderOffer({ title: 'Old offer', zone: 'left' });");
  await env.run('inferFrame(generation)');
  assert.equal(env.get('observation-title').textContent, 'Waiting for a fresh frame');
  assert.match(env.get('observation-reason').textContent, /took too long/);
  assert.equal(env.get('offer-title').textContent, 'Find your next favourite.');
  assert.equal(env.run('running'), true);
  assert.ok([...env.timers.values()].some(({ delay }) => delay === 333));
});

const sessionResponse = (body, instance, generation, status = 200) => ({ ...response(body, status), headers: { get: (name) => name === 'X-Session-Instance' ? instance : name === 'X-Session-Generation' ? String(generation) : null } });
const firstInstance = 'a'.repeat(32);
const secondInstance = 'b'.repeat(32);

test('session tokens advance on errors, recover after restart and ignore late retired responses', async () => {
  const old = deferred();
  let calls = 0;
  const env = environment(() => {
    calls += 1;
    if (calls === 1) return Promise.resolve(sessionResponse({}, firstInstance, 4));
    if (calls === 2) return old.promise;
    if (calls === 3) return Promise.resolve(sessionResponse({ detail: 'Old server session.', code: 'stale_frame' }, secondInstance, 0, 409));
    return Promise.resolve(sessionResponse({}, secondInstance, 1));
  });
  await env.run("TraceClient.requestJSON('/api/status')");
  const late = env.run("TraceClient.requestJSON('/api/state')");
  await assert.rejects(env.run("TraceClient.requestJSON('/api/infer')"), (error) => error.code === 'stale_frame');
  assert.equal(env.run('TraceClient.session.instance'), secondInstance);
  assert.equal(env.run('TraceClient.session.generation'), 0);
  const discarded = assert.rejects(late, (error) => error.code === 'STALE_RESPONSE');
  old.resolve(sessionResponse({}, firstInstance, 8));
  await discarded;
  assert.equal(env.run('TraceClient.session.instance'), secondInstance);
  assert.equal(env.run('TraceClient.session.generation'), 0);
  await env.run("TraceClient.requestJSON('/api/status')");
  assert.equal(env.run('TraceClient.session.generation'), 1);
});

test('frame request carries the session captured before asynchronous image encoding', async () => {
  const sent = [];
  const env = environment(async (path, options) => {
    sent.push({ path, headers: options.headers });
    if (path === '/api/status') return sessionResponse({ ready: true, config, state: state() }, firstInstance, 3);
    if (path === '/api/stop') return sessionResponse(state(), firstInstance, 4);
    return sessionResponse({ faces: [], width: 640, height: 480, observation: {}, state: state() }, firstInstance, 4);
  });
  env.load('app');
  await tick();
  env.run('running = true; capture.toBlob = (callback) => { globalThis.finishEncoding = callback; };');
  const frame = env.run('inferFrame(generation)');
  await env.run("request('/api/stop', { method: 'POST' })");
  env.run("finishEncoding({ type: 'image/jpeg' });");
  await frame;
  const inference = sent.find(({ path }) => path === '/api/infer');
  assert.equal(inference.headers['X-Session-Generation'], '3');
  assert.equal(inference.headers['X-Session-Instance'], firstInstance);
  assert.equal(env.run('TraceClient.session.generation'), 4);
});

test('a restart reloads saved geometry and blocks capture until setup is saved again', async () => {
  let restarted = false;
  const env = environment(async (path, options) => {
    const instance = restarted ? secondInstance : firstInstance;
    if (path === '/api/config') return sessionResponse(JSON.parse(options.body), instance, 1);
    return sessionResponse({ ready: true, config: { ...config, shelf_width_m: restarted ? 1.2 : 2.4 }, state: state() }, instance, 0);
  });
  env.load('app');
  await tick();
  assert.equal(env.get('config-form').elements[0].value, 2.4);
  env.run('running = true; frameTimer = setTimeout(() => inferFrame(generation), 333);');
  restarted = true;
  await env.run('refreshStatus()');
  assert.equal(env.get('config-form').elements[0].value, 1.2);
  assert.equal(env.run('running'), false);
  assert.equal(env.get('start-camera').disabled, true);
  assert.match(env.get('service-banner').textContent, /service restarted/);
  assert.equal([...env.timers.values()].some(({ delay }) => delay === 333), false);
  const form = env.get('config-form');
  await form.listeners.submit({ preventDefault() {}, currentTarget: form });
  assert.equal(env.get('start-camera').disabled, false);
});

test('a restart preserves unsaved geometry and requires a successful save', async () => {
  let restarted = false;
  const env = environment(async () => sessionResponse({ ready: true, config, state: state() }, restarted ? secondInstance : firstInstance, 0));
  env.load('app');
  await tick();
  const form = env.get('config-form');
  form.elements[0].value = 2.8;
  form.listeners.input();
  restarted = true;
  await env.run('refreshStatus()');
  assert.equal(form.elements[0].value, 2.8);
  assert.equal(env.get('start-camera').disabled, true);
  assert.match(env.get('config-feedback').textContent, /edits are kept/);
  assert.equal(env.run('setupNeedsConfirmation'), true);
});

test('a restart first detected by an inference error stops capture before retry', async () => {
  let restarted = false;
  const env = environment(async (path) => {
    if (path === '/api/infer') { restarted = true; return sessionResponse({ detail: 'Old session.', code: 'stale_frame' }, secondInstance, 0, 409); }
    return sessionResponse({ ready: true, config, state: state() }, restarted ? secondInstance : firstInstance, 0);
  });
  env.load('app');
  await tick();
  env.run('running = true;');
  await env.run('inferFrame(generation)');
  await tick();
  assert.equal(env.run('running'), false);
  assert.equal(env.get('start-camera').disabled, true);
  assert.equal(env.run('setupNeedsConfirmation'), true);
  assert.equal([...env.timers.values()].some(({ delay }) => delay === 333), false);
});

test('pagehide cancels scheduled frames and page restoration cannot restart capture', async () => {
  const requests = [];
  let stoppedTracks = 0;
  const env = environment(async (path) => { requests.push(path); return sessionResponse({ ready: true, config, state: state() }, firstInstance, 0); });
  env.context.stopTrack = () => { stoppedTracks += 1; };
  env.load('app');
  await tick();
  env.run('running = true; stream = { getTracks: () => [{ stop: stopTrack }] }; frameTimer = setTimeout(() => inferFrame(generation), 333);');
  const oldGeneration = env.run('generation');
  env.run('window.listeners.pagehide({ persisted: true })');
  assert.equal(env.run('running'), false);
  assert.equal(env.run('starting'), false);
  assert.equal(env.run('generation'), oldGeneration + 1);
  assert.equal(stoppedTracks, 1);
  assert.equal(env.get('camera-status').textContent, 'Camera off');
  assert.equal([...env.timers.values()].some(({ delay }) => delay === 333), false);
  env.run('window.listeners.pageshow({ persisted: true })');
  await tick();
  await env.run(`inferFrame(${oldGeneration})`);
  assert.equal(requests.filter((path) => path === '/api/infer').length, 0);
  assert.equal(env.run('running'), false);
});

test('late camera permission after pagehide releases the incoming stream', async () => {
  const permission = deferred();
  let stoppedTracks = 0;
  const env = environment(async () => response({ ready: true, config, state: state() }));
  env.context.navigator.mediaDevices = { getUserMedia: () => permission.promise };
  env.load('app');
  await tick();
  const started = env.run('startCamera()');
  env.run('window.listeners.pagehide({ persisted: true })');
  permission.resolve({ getTracks: () => [{ stop: () => { stoppedTracks += 1; } }] });
  await started;
  assert.equal(stoppedTracks, 1);
  assert.equal(env.run('running'), false);
  assert.equal(env.get('camera-status').textContent, 'Camera off');
});

test('Pydantic validation removes only the leading Value error prefix', async () => {
  const env = environment(async () => response({ detail: [{ loc: ['body'], msg: 'Value error, Camera height must be within the shelf height.' }] }, 422));
  await assert.rejects(env.run("TraceClient.requestJSON('/api/config')"), (error) => error.message === 'Camera height must be within the shelf height.');
});
