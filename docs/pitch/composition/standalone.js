/*
 * Interim standalone bridge for HyperFrames 0.8.114's official slideshow player.
 * The CLI engine still owns normal composition checks and snapshots. This bridge
 * runs only inside the same-origin standalone/present player, with no engine.
 */
(() => {
  'use strict';
  let slideshow;
  try {
    if (window.parent === window || window.__hf || window.__player) return;
    slideshow = window.parent.document.querySelector('hyperframes-slideshow');
    if (!slideshow || !slideshow.querySelector('hyperframes-player')) return;
  } catch {
    return;
  }
  if (!window.gsap || !window.__timelines) return;

  const scenes = [...document.querySelectorAll('[data-composition-id]')].map((element) => ({
    element,
    id: element.dataset.compositionId,
    start: Number(element.dataset.start || 0),
    duration: Number(element.dataset.duration),
    timeline: window.__timelines[element.dataset.compositionId],
  })).filter((scene) => Number.isFinite(scene.duration) && scene.duration > 0);
  if (!scenes.length) return;
  const duration = Math.max(...scenes.map((scene) => scene.start + scene.duration));
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let activeId = null;
  let lastTime = null;
  let entrances = [];
  const revealed = new Set();

  function cancelEntrances() {
    entrances.forEach((animation) => animation.cancel());
    entrances = [];
  }

  function entrance(elements) {
    if (reducedMotion.matches) return;
    elements.forEach((element, index) => {
      if (!element.animate) return;
      const opacity = Number(getComputedStyle(element).opacity);
      if (opacity <= 0 || getComputedStyle(element).visibility === 'hidden') return;
      // A transient opacity overlay never changes the authored transform or
      // timeline endpoint. Cancelling it restores the exact seekable frame.
      entrances.push(element.animate([{ opacity: 0 }, { opacity }], {
        duration: 440,
        delay: Math.min(index * 65, 260),
        easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
        fill: 'backwards',
      }));
    });
  }

  function setTime(time) {
    const t = Math.max(0, Math.min(duration - 0.001, Number(time) || 0));
    if (lastTime === t) return;
    cancelEntrances();
    const current = scenes.find((scene) => t >= scene.start && t < scene.start + scene.duration);
    const changed = current && current.id !== activeId;
    const newlyRevealed = [];

    for (const scene of scenes) {
      // Scene timelines use absolute composition time. Preserve their original
      // references before exposing the bridge as the player's chosen timeline.
      scene.timeline?.pause().seek(t, false);
      const active = scene === current;
      scene.element.style.opacity = active ? '1' : '0';
      scene.element.style.visibility = active ? 'visible' : 'hidden';
      scene.element.style.pointerEvents = active ? 'auto' : 'none';
      scene.element.setAttribute('aria-hidden', active ? 'false' : 'true');
      scene.element.inert = !active;

      for (const element of scene.element.querySelectorAll('[data-reveal-at]')) {
        const show = active && t >= Number(element.dataset.revealAt);
        element.style.visibility = show ? 'visible' : 'hidden';
        element.style.pointerEvents = show ? '' : 'none';
        element.setAttribute('aria-hidden', show ? 'false' : 'true');
        element.inert = !show;
        if (show && !revealed.has(element)) newlyRevealed.push(element);
        if (show) revealed.add(element);
        else revealed.delete(element);
      }
    }
    if (lastTime !== null && current) {
      if (changed) entrance([...current.element.querySelectorAll('[data-anim]')]);
      entrance(newlyRevealed.filter((element) => !changed || !element.hasAttribute('data-anim')));
    }
    activeId = current?.id ?? null;
    lastTime = t;
  }

  const root = gsap.timeline({ paused: true });
  root.to({}, { duration });
  root.eventCallback('onUpdate', () => setTime(root.time()));
  window.__timelines.root = root;
  // v0.8.114 prefers the first scene's registry key over "root". This alias is
  // deliberately confined to this standalone iframe; the source DOM and the
  // CLI composition timeline registry remain unchanged.
  window.__timelines[scenes[0].id] = root;
  window.__hfSetTime = setTime;
  setTime(0);

  function postTimeline() {
    window.parent.postMessage({
      source: 'hf-preview',
      type: 'timeline',
      durationInFrames: duration * 30,
      durationSeconds: duration,
      compositionWidth: Number(scenes[0].element.dataset.width) || 1920,
      compositionHeight: Number(scenes[0].element.dataset.height) || 1080,
      scenes: scenes.map(({ id, start, duration }) => ({ id, start, duration })),
    }, window.location.origin);
  }
  if (document.readyState === 'complete') postTimeline();
  else window.addEventListener('load', postTimeline, { once: true });
})();
