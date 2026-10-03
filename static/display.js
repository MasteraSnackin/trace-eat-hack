'use strict';

const names = { left: 'Protein bars', centre: 'Protein drinks', right: 'Protein snacks' };
let busy = false;
let lastSignature = '';

async function updateDisplay() {
  if (busy) return;
  busy = true;
  try {
    const response = await fetch('/api/state', { cache: 'no-store' });
    if (!response.ok) throw new Error('Unavailable');
    const result = await response.json();
    const state = result.state || result;
    const offer = state.offer;
    const signature = JSON.stringify([offer, state.camera_active]);
    if (signature !== lastSignature) {
      lastSignature = signature;
      const hasOffer = Boolean(offer?.title && state.camera_active !== false);
      document.getElementById('display-kicker').textContent = hasOffer && names[offer.zone] ? `Explore / ${names[offer.zone]}` : 'A little discovery';
      document.getElementById('display-title').textContent = hasOffer ? String(offer.title) : 'Find your next favourite.';
      document.getElementById('display-detail').textContent = hasOffer && offer.detail ? String(offer.detail) : 'Explore something new on the shelf.';
      document.body.dataset.zone = hasOffer && names[offer.zone] ? offer.zone : '';
    }
    document.getElementById('display-status').textContent = state.camera_active ? 'Live shelf demonstration' : 'Ready for the next visit';
  } catch {
    document.getElementById('display-status').textContent = 'Local connection paused';
    document.getElementById('display-kicker').textContent = 'A little discovery';
    document.getElementById('display-title').textContent = 'Find your next favourite.';
    document.getElementById('display-detail').textContent = 'Explore something new on the shelf.';
    document.body.dataset.zone = '';
    lastSignature = '';
  } finally { busy = false; }
}

updateDisplay();
setInterval(updateDisplay, 500);
