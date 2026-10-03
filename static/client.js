'use strict';

// Shared by the two plain JavaScript pages. No camera or visit data is retained.
let traceSession = null;
globalThis.TraceClient = Object.freeze({
  get session() { return traceSession ? { ...traceSession } : null; },
  async requestJSON(path, options = {}) {
    const { timeoutMs = 5000, signal, ...fetchOptions } = options;
    const requestInstance = traceSession?.instance ?? null;
    const controller = new AbortController();
    let interrupt;
    const interrupted = new Promise((_, reject) => { interrupt = reject; });
    const cancel = () => {
      controller.abort();
      interrupt(new DOMException('Request cancelled.', 'AbortError'));
    };
    signal?.addEventListener('abort', cancel, { once: true });
    const timer = setTimeout(() => {
      controller.abort();
      const error = new Error('The local service did not respond in time. Check that it is running, then try again.');
      error.code = 'REQUEST_TIMEOUT';
      interrupt(error);
    }, timeoutMs);
    if (signal?.aborted) cancel();
    try {
      const operation = (async () => {
        const response = await fetch(path, { cache: 'no-store', ...fetchOptions, signal: controller.signal });
        const instance = response.headers?.get('X-Session-Instance');
        const rawGeneration = response.headers?.get('X-Session-Generation');
        const generation = Number(rawGeneration);
        if (/^[a-f0-9]{32}$/.test(instance || '') && /^\d+$/.test(rawGeneration || '') && Number.isSafeInteger(generation)) {
          if (!traceSession || traceSession.instance === instance || traceSession.instance === requestInstance) {
            traceSession = { instance, generation: traceSession?.instance === instance ? Math.max(traceSession.generation, generation) : generation };
          }
          // An earlier request cannot restore the token of a retired server.
        }
        let body;
        try { body = await response.json(); }
        catch {
          const error = new Error(response.ok ? 'The local service returned an unreadable response. Try again.' : `The local service returned ${response.status}. Try again.`);
          error.status = response.status;
          error.code = 'INVALID_RESPONSE';
          throw error;
        }
        if (instance && traceSession && instance !== traceSession.instance) {
          const error = new Error('A response from an earlier service session was discarded.');
          error.code = 'STALE_RESPONSE';
          throw error;
        }
        if (!response.ok) {
          let detail = typeof body?.detail === 'string' ? body.detail : typeof body?.error === 'string' ? body.error : '';
          if (Array.isArray(body?.detail)) {
            detail = body.detail.map((item) => {
              const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.').replaceAll('_', ' ') : '';
              const reason = String(item.msg || 'Invalid value.').replace(/^Value error, /, '');
              return `${field ? `${field}: ` : ''}${reason}`;
            }).join(' ');
          }
          if (response.status === 422) detail = detail.replace(/^Value error, /, '');
          const error = new Error(detail || `The local service returned ${response.status}.`);
          error.status = response.status;
          error.code = body?.code;
          throw error;
        }
        if (!body || typeof body !== 'object' || Array.isArray(body)) {
          const error = new Error('The local service returned an unexpected response. Try again.');
          error.code = 'INVALID_RESPONSE';
          throw error;
        }
        return body;
      })();
      return await Promise.race([operation, interrupted]);
    } catch (error) {
      if (error instanceof TypeError) {
        const unavailable = new Error('Cannot reach the local service. Check that it is running, then try again.');
        unavailable.code = 'NETWORK_ERROR';
        throw unavailable;
      }
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
    }
  },
});
