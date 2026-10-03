'use strict';

const $ = (id) => document.getElementById(id);
const video = $('camera-video');
const overlay = $('camera-overlay');
const overlayContext = overlay.getContext('2d');
const capture = document.createElement('canvas');
const captureContext = capture.getContext('2d', { alpha: false });
const zoneNames = { left: 'Protein bars', centre: 'Protein drinks', right: 'Protein snacks' };
let stream = null;
let running = false;
let starting = false;
let stopping = false;
let settingsBusy = false;
let serviceReady = false;
let generation = 0;
let stateRevision = 0;
let configRevision = 0;
let frameTimer = null;
let pendingFrame = null;
let statusBusy = false;
let configLoaded = false;
let configDirty = false;
let configInstance = null;
let setupNeedsConfirmation = false;
let pageActive = true;
let cameraError = '';
let lastEventSignature = '';
let lastObservationAt = null;

const asNumber = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const words = (value) => String(value || '').replaceAll('_', ' ').replaceAll('-', ' ');

const request = TraceClient.requestJSON;

function banner(message, kind = '') {
  $('service-banner').textContent = message;
  $('service-banner').className = `notice${kind ? ` ${kind}` : ''}`;
}

function syncControls() {
  $('start-camera').disabled = !pageActive || !serviceReady || running || starting || stopping || settingsBusy || setupNeedsConfirmation || serverChanged();
  $('start-camera').textContent = starting ? 'Opening camera…' : stopping ? 'Ending visit…' : 'Start camera';
  $('stop-camera').disabled = !running && !starting;
  $('camera-status').textContent = starting ? 'Starting' : running ? 'Camera on' : 'Camera off';
  $('camera-status').className = `pill${running ? ' live' : ''}`;
  $('save-config').disabled = settingsBusy || stopping;
  $('reset-run').disabled = settingsBusy || stopping;
  $('config-form').setAttribute('aria-busy', String(settingsBusy));
}

function populateConfig(config) {
  if (!config || configDirty) return;
  for (const element of $('config-form').elements) {
    if (element.name && Number.isFinite(Number(config[element.name]))) element.value = config[element.name];
  }
  configLoaded = true;
}

function serverChanged() {
  return Boolean(configInstance && TraceClient.session && configInstance !== TraceClient.session.instance);
}

function pauseForRestart() {
  if (!serverChanged()) return false;
  configInstance = TraceClient.session.instance;
  configLoaded = false;
  setupNeedsConfirmation = true;
  serviceReady = false;
  cameraError = '';
  releaseCamera();
  $('config-feedback').textContent = configDirty ? 'The service restarted. Your edits are kept. Review and save them before restarting the camera.' : 'The service restarted. Review the reloaded setup and save it before restarting the camera.';
  banner('The local service restarted. Check the shelf setup and choose Save shelf setup before starting the camera.', 'warning');
  syncControls();
  return true;
}

async function refreshStatus() {
  if (statusBusy || !pageActive) return;
  statusBusy = true;
  const revision = stateRevision;
  try {
    const data = await request('/api/status');
    if (revision !== stateRevision || stopping || settingsBusy) return;
    pauseForRestart();
    serviceReady = Boolean(data.ready);
    if (!configLoaded) populateConfig(data.config);
    if (!configInstance) configInstance = TraceClient.session?.instance ?? null;
    if (!running && data.state) renderState(data.state);
    if (cameraError) banner(cameraError, 'error');
    else if (setupNeedsConfirmation) banner('The local service restarted. Check the shelf setup and choose Save shelf setup before starting the camera.', 'warning');
    else if (!serviceReady) banner(data.model_error ? `Gaze model unavailable: ${data.model_error}` : 'The local gaze model is getting ready. Camera controls will become available when it is ready.', 'warning');
    else banner(running ? 'Estimating broad shelf zones locally. Unclear observations are left unassigned.' : 'Gaze service ready. Start the camera when the shelf and camera are in position.');
    syncControls();
  } catch {
    if (revision !== stateRevision) return;
    serviceReady = false;
    banner('Cannot reach the local shelf service. Keep this page open and start or check the service; it will reconnect automatically.', 'error');
    syncControls();
  } finally { statusBusy = false; }
}

function renderState(state) {
  if (!state || typeof state !== 'object') return;
  const totals = state.zone_totals || {};
  const maximum = Math.max(1, ...Object.values(totals).map((value) => Math.max(0, asNumber(value))));
  for (const zone of Object.keys(zoneNames)) {
    const amount = Math.max(0, asNumber(totals[zone]));
    $(`${zone}-dwell`).textContent = amount.toFixed(1);
    $(`${zone}-meter`).style.width = `${Math.min(100, amount / maximum * 100)}%`;
    document.querySelector(`[data-zone="${zone}"]`).classList.toggle('active', running && state.current_zone === zone);
  }
  const session = state.session_id ? String(state.session_id) : '';
  $('session-id').textContent = session || 'No active visit';
  $('session-id').title = session;
  $('current-dwell').textContent = Math.max(0, asNumber(state.dwell_s)).toFixed(1);
  $('visit-count').textContent = Math.max(0, asNumber(state.visits)).toLocaleString('en-GB');
  renderOffer(state.offer);
  renderEvents(state.events);
}

function renderOffer(offer) {
  const hasOffer = Boolean(offer && offer.title);
  const specific = hasOffer && Boolean(zoneNames[offer.zone]);
  $('offer-kicker').textContent = specific ? `Explore / ${zoneNames[offer.zone]}` : 'A little discovery';
  $('offer-title').textContent = hasOffer ? String(offer.title) : 'Find your next favourite.';
  $('offer-detail').textContent = hasOffer && offer.detail ? String(offer.detail) : 'An example offer appears after sustained estimated gaze towards a shelf zone.';
  $('offer-preview').classList.toggle('offer-active', specific);
}

function renderEvents(events) {
  const items = Array.isArray(events) ? [...events].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 12) : [];
  const signature = JSON.stringify(items);
  if (signature === lastEventSignature) return;
  lastEventSignature = signature;
  const list = $('event-list');
  list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-events';
    empty.textContent = 'Recorded activity will appear here once the camera starts.';
    list.append(empty);
    return;
  }
  for (const item of items) {
    const row = document.createElement('div');
    row.className = 'event-row';
    const time = document.createElement('time');
    time.className = 'event-time';
    let timestamp = item.timestamp;
    if (typeof timestamp === 'number' && timestamp < 1e12) timestamp *= 1000;
    const date = new Date(timestamp);
    time.textContent = Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    if (!Number.isNaN(date.getTime())) time.dateTime = date.toISOString();
    const content = document.createElement('div');
    const title = document.createElement('strong');
    const eventName = words(item.type) || 'Observation';
    title.textContent = `${eventName.charAt(0).toUpperCase()}${eventName.slice(1)}${zoneNames[item.zone] ? ` · ${zoneNames[item.zone]}` : ''}`;
    content.append(title);
    if (item.detail) {
      const description = document.createElement('p');
      description.textContent = typeof item.detail === 'string' ? item.detail : words(item.detail.reason || '');
      content.append(description);
    }
    row.append(time, content);
    list.append(row);
  }
}

function renderObservation(data) {
  const faces = Array.isArray(data.faces) ? data.faces : [];
  const observation = data.observation || {};
  const zone = zoneNames[observation.zone];
  const face = faces.length === 1 ? faces[0] : null;
  const hasZone = Boolean(zone && observation.point && face && face.usable);
  $('face-count').textContent = String(faces.length);
  $('face-confidence').textContent = face && Number.isFinite(Number(face.confidence)) ? `${Math.round(Number(face.confidence) * 100)}%` : '—';
  $('inference-time').textContent = Number.isFinite(Number(data.inference_ms)) ? `${Math.round(Number(data.inference_ms))} ms` : '—';
  $('observation-dot').className = `observation-dot ${hasZone ? 'good' : 'warning'}`;
  if (hasZone) $('observation-title').textContent = `Estimated gaze · ${zone}`;
  else if (faces.length > 1) $('observation-title').textContent = 'Multiple faces · not assigned';
  else if (!faces.length) $('observation-title').textContent = 'Waiting for one clear face';
  else $('observation-title').textContent = 'Gaze is not reliably measurable';
  $('observation-reason').textContent = observation.reason ? words(observation.reason) : face?.quality_reason ? words(face.quality_reason) : hasZone ? 'A broad shelf-zone estimate. Individual product selection is not measured.' : 'Move into a clear, front-facing view of the camera. No gaze target or calibration is required.';
  drawFaces(data);
}

function drawFaces(data) {
  const width = asNumber(data.width, capture.width);
  const height = asNumber(data.height, capture.height);
  if (width <= 0 || height <= 0) return;
  overlay.width = width;
  overlay.height = height;
  overlayContext.clearRect(0, 0, width, height);
  for (const face of data.faces || []) {
    if (!Array.isArray(face.bbox) || face.bbox.length < 4) continue;
    const [x, y, w, h] = face.bbox.map(Number);
    if (![x, y, w, h].every(Number.isFinite)) continue;
    overlayContext.strokeStyle = face.usable ? '#d1edb1' : '#edc585';
    overlayContext.lineWidth = 2;
    overlayContext.strokeRect(x, y, w, h);
    const gaze = Array.isArray(face.gaze) ? face.gaze : [face.gaze?.x, face.gaze?.y, face.gaze?.z];
    if (!face.usable || !gaze.slice(0, 3).every((n) => Number.isFinite(Number(n)))) continue;
    const gx = Number(gaze[0]), gy = Number(gaze[1]);
    const startX = x + w / 2, startY = y + h * .4;
    const length = Math.min(w, h) * .7;
    // The local vision service defines x as image-right and y as image-up.
    const endX = startX + gx * length, endY = startY - gy * length;
    const angle = Math.atan2(endY - startY, endX - startX);
    overlayContext.beginPath();
    overlayContext.moveTo(startX, startY);
    overlayContext.lineTo(endX, endY);
    if (Math.hypot(endX - startX, endY - startY) > 5) {
      overlayContext.moveTo(endX - 7 * Math.cos(angle - .45), endY - 7 * Math.sin(angle - .45));
      overlayContext.lineTo(endX, endY);
      overlayContext.lineTo(endX - 7 * Math.cos(angle + .45), endY - 7 * Math.sin(angle + .45));
    }
    overlayContext.stroke();
    overlayContext.fillStyle = '#d1edb1';
    overlayContext.beginPath();
    overlayContext.arc(startX, startY, 3, 0, Math.PI * 2);
    overlayContext.fill();
  }
}

function cameraMessage(error) {
  if (error.name === 'NotAllowedError' || error.name === 'SecurityError') return 'Camera permission was not granted. Allow camera access for this local page, then choose Start camera.';
  if (error.name === 'NotFoundError') return 'No camera was found. Connect a webcam, then choose Start camera.';
  if (error.name === 'NotReadableError' || error.name === 'AbortError') return 'The camera could not start. Close other apps using it, then try again.';
  return `The camera could not start: ${error.message || 'unknown camera error'}`;
}

async function startCamera() {
  if (pauseForRestart()) { refreshStatus(); return; }
  if (!pageActive || running || starting || stopping || settingsBusy || setupNeedsConfirmation || !serviceReady) return;
  ++stateRevision;
  cameraError = '';
  if (!navigator.mediaDevices?.getUserMedia) {
    cameraError = 'Camera access is unavailable in this browser. Open this app on localhost in a browser that supports camera access.';
    banner(cameraError, 'error');
    return;
  }
  const token = ++generation;
  starting = true;
  syncControls();
  try {
    const incoming = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, aspectRatio: { ideal: 4 / 3 }, facingMode: 'user', frameRate: { ideal: 15, max: 30 } }, audio: false });
    if (token !== generation) { incoming.getTracks().forEach((track) => track.stop()); return; }
    stream = incoming;
    video.srcObject = stream;
    await video.play();
    if (token !== generation) return;
    starting = false;
    running = true;
    $('camera-stage').classList.add('running');
    $('camera-placeholder').hidden = true;
    $('camera-live-label').hidden = false;
    for (const track of stream.getVideoTracks()) track.addEventListener('ended', () => { if (running && token === generation) stopCamera('The camera disconnected. Reconnect it and start again.'); });
    syncControls();
    banner('Estimating broad shelf zones locally. Unclear observations are left unassigned.');
    inferFrame(token);
  } catch (error) {
    if (token !== generation) return;
    await stopCamera(cameraMessage(error));
  }
}

async function inferFrame(token) {
  if (!pageActive || !running || token !== generation) return;
  if (pauseForRestart()) { refreshStatus(); return; }
  if (settingsBusy) {
    frameTimer = setTimeout(() => inferFrame(token), 333);
    return;
  }
  const revision = stateRevision;
  const session = TraceClient.session;
  const started = performance.now();
  try {
    if (!video.videoWidth || !video.videoHeight) throw new Error('The camera has not produced a frame yet.');
    const scale = Math.min(640 / video.videoWidth, 480 / video.videoHeight, 1);
    capture.width = Math.round(video.videoWidth * scale);
    capture.height = Math.round(video.videoHeight * scale);
    captureContext.drawImage(video, 0, 0, capture.width, capture.height);
    const blob = await new Promise((resolve) => capture.toBlob(resolve, 'image/jpeg', .78));
    if (!running || token !== generation) return;
    if (!blob) throw new Error('The browser could not encode a camera frame. Start the camera again.');
    $('frame-info').textContent = `${capture.width} × ${capture.height}`;
    const controller = new AbortController();
    pendingFrame = controller;
    let result;
    const headers = { 'Content-Type': 'image/jpeg' };
    if (session) {
      headers['X-Session-Instance'] = session.instance;
      headers['X-Session-Generation'] = String(session.generation);
    }
    try { result = await request('/api/infer', { method: 'POST', headers, body: blob, signal: controller.signal, timeoutMs: 20000 }); }
    finally { if (pendingFrame === controller) pendingFrame = null; }
    if (!running || token !== generation) return;
    if (pauseForRestart()) { refreshStatus(); return; }
    if (revision === stateRevision) {
      renderObservation(result);
      lastObservationAt = performance.now();
      if (result.state) renderState(result.state);
    }
  } catch (error) {
    if (!running || token !== generation) return;
    if (pauseForRestart()) { refreshStatus(); return; }
    if (revision !== stateRevision) {
      // A setup change or reset invalidated this frame. The next frame resumes.
    } else if (error.status === 429) {
      clearObservation('Waiting for the gaze service', 'An earlier frame is still being processed. The next frame will be sent shortly.');
    } else if (error.status === 409) {
      clearObservation('Waiting for a fresh frame', error.code === 'frame_expired' ? 'The last frame took too long to process and was discarded. The next frame will be sent shortly.' : 'The previous frame belongs to an earlier visit or setup. Waiting for the next observation.');
    } else {
      await stopCamera(error.name === 'AbortError' ? 'The gaze service did not respond in time. Check the service, then start the camera again.' : `Gaze estimation stopped: ${error.message}`);
      return;
    }
  }
  if (running && token === generation) frameTimer = setTimeout(() => inferFrame(token), Math.max(0, 333 - (performance.now() - started)));
}

function clearCurrentVisit() {
  $('session-id').textContent = 'No current estimate';
  $('current-dwell').textContent = '0.0';
  renderOffer(null);
  for (const card of document.querySelectorAll('.zone-card')) card.classList.remove('active');
}

function clearObservation(title, reason) {
  lastObservationAt = null;
  clearCurrentVisit();
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  $('face-count').textContent = '—';
  $('face-confidence').textContent = '—';
  $('inference-time').textContent = '—';
  $('observation-dot').className = 'observation-dot warning';
  $('observation-title').textContent = title;
  $('observation-reason').textContent = reason;
}

function finishSettingsFeedback(revision) {
  if (revision !== stateRevision) return;
  $('observation-dot').className = 'observation-dot';
  $('observation-title').textContent = running ? 'Waiting for a fresh observation' : 'Camera is off';
  $('observation-reason').textContent = running ? 'The next camera frame will use the current saved setup.' : 'Start the camera to begin a new visit.';
}

function releaseCamera() {
  const revision = ++stateRevision;
  ++generation;
  running = false;
  starting = false;
  lastObservationAt = null;
  clearTimeout(frameTimer);
  frameTimer = null;
  pendingFrame?.abort();
  pendingFrame = null;
  stream?.getTracks().forEach((track) => track.stop());
  stream = null;
  video.srcObject = null;
  captureContext.clearRect(0, 0, capture.width, capture.height);
  overlayContext.clearRect(0, 0, overlay.width, overlay.height);
  $('camera-stage').classList.remove('running');
  $('camera-placeholder').hidden = false;
  $('camera-live-label').hidden = true;
  $('frame-info').textContent = '';
  $('observation-title').textContent = 'Camera is off';
  $('observation-reason').textContent = 'Frames are no longer being captured. Start the camera to begin a new visit.';
  $('observation-dot').className = 'observation-dot';
  $('face-count').textContent = '—';
  $('face-confidence').textContent = '—';
  $('inference-time').textContent = '—';
  clearCurrentVisit();
  return revision;
}

async function stopCamera(errorMessage = '') {
  if (stopping) return;
  stopping = true;
  const revision = releaseCamera();
  cameraError = errorMessage;
  syncControls();
  if (errorMessage) banner(errorMessage, 'error');
  else banner('Camera stopped. No frames are being captured.');
  try {
    const data = await request('/api/stop', { method: 'POST' });
    if (revision === stateRevision) renderState(data.state || data);
  } catch {
    serviceReady = false;
    if (!errorMessage) banner('Camera stopped on this device. The service has not confirmed that the visit ended. Checking the connection automatically.', 'warning');
  } finally { stopping = false; syncControls(); }
}

$('config-form').addEventListener('input', () => { ++configRevision; configDirty = true; $('config-feedback').textContent = 'Unsaved changes'; });
$('config-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (settingsBusy || stopping) return;
  settingsBusy = true;
  const revision = ++stateRevision;
  const submittedConfigRevision = configRevision;
  pendingFrame?.abort();
  clearObservation('Shelf setup is being saved', 'Current estimates are paused until the service confirms the setup.');
  const config = Object.fromEntries([...new FormData(event.currentTarget)].map(([key, value]) => [key, Number(value)]));
  syncControls();
  $('config-feedback').textContent = 'Saving…';
  try {
    const data = await request('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(config) });
    configInstance = TraceClient.session?.instance ?? configInstance;
    setupNeedsConfirmation = false;
    if (submittedConfigRevision === configRevision) {
      configDirty = false;
      populateConfig(data.config || data);
      $('config-feedback').textContent = 'Shelf setup saved. The next observation starts a new visit.';
    } else $('config-feedback').textContent = 'Shelf setup saved. Your newer edits are not saved.';
    if (revision === stateRevision && data.state) renderState(data.state);
  } catch (error) { $('config-feedback').textContent = `Could not save: ${error.message}`; }
  finally { settingsBusy = false; finishSettingsFeedback(revision); syncControls(); }
});

$('reset-run').addEventListener('click', async () => {
  if (settingsBusy || stopping) return;
  settingsBusy = true;
  const revision = ++stateRevision;
  pendingFrame?.abort();
  clearObservation('Resetting the run', 'Waiting for the service to clear the previous visit.');
  syncControls();
  $('reset-run').textContent = 'Resetting…';
  try {
    const data = await request('/api/reset', { method: 'POST' });
    if (revision !== stateRevision) return;
    if (pauseForRestart()) { refreshStatus(); return; }
    lastEventSignature = '';
    renderState(data.state || data);
    cameraError = '';
    banner(running ? 'Run reset. The camera is continuing with a fresh visit.' : 'Run reset. Start the camera for a new observation.');
  } catch (error) { banner(`Could not reset the run: ${error.message}`, 'error'); }
  finally { settingsBusy = false; $('reset-run').textContent = 'Reset run'; finishSettingsFeedback(revision); syncControls(); }
});

$('start-camera').addEventListener('click', startCamera);
$('stop-camera').addEventListener('click', () => stopCamera());
window.addEventListener('pagehide', () => {
  const hadCamera = running || starting;
  pageActive = false;
  releaseCamera();
  serviceReady = false;
  syncControls();
  if (hadCamera) navigator.sendBeacon('/api/stop', '');
});
window.addEventListener('pageshow', () => { pageActive = true; refreshStatus(); });
refreshStatus();
setInterval(refreshStatus, 2500);
setInterval(() => {
  if (running && lastObservationAt !== null && performance.now() - lastObservationAt > 1500) {
    clearObservation('Waiting for a fresh observation', 'The previous estimate has expired. Current gaze and offers will return when a fresh frame is processed.');
  }
}, 250);
