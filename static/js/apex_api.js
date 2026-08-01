/* APEX 65.1 — shared frontend API reliability client. */
(function (global) {
  'use strict';

  const NATIVE_FETCH = global.fetch.bind(global);
  const DEFAULT_TIMEOUT_MS = 12000;
  const cache = new Map();
  const metrics = new Map();

  function nowIso() { return new Date().toISOString(); }
  function requestKey(method, url) { return String(method || 'GET').toUpperCase() + ' ' + String(url); }
  function classify(status, ok, data) {
    const explicit = String((data && (data.status || data.state || data.health_state)) || '').toUpperCase();
    if (['HEALTHY','READY','OK','PASS','LIVE'].includes(explicit)) return 'HEALTHY';
    if (['DEGRADED','WARNING','WARN','STALE'].includes(explicit)) return explicit === 'STALE' ? 'STALE' : 'DEGRADED';
    if (['DISABLED'].includes(explicit)) return 'DISABLED';
    if (['UNAVAILABLE','OFFLINE','MISSING'].includes(explicit)) return 'UNAVAILABLE';
    if (!ok || status >= 500) return 'FAILED';
    if (status >= 400) return 'UNAVAILABLE';
    return 'HEALTHY';
  }

  function emit(detail) {
    try { global.dispatchEvent(new CustomEvent('apex:api-result', { detail })); } catch (_) {}
  }

  async function request(url, options) {
    const opts = Object.assign({}, options || {});
    const method = String(opts.method || 'GET').toUpperCase();
    const timeoutMs = Number(opts.timeoutMs || DEFAULT_TIMEOUT_MS);
    const fallback = opts.fallback;
    const cacheFallback = opts.cacheFallback !== false && method === 'GET';
    delete opts.timeoutMs; delete opts.fallback; delete opts.cacheFallback;
    if (method === 'GET' && !('cache' in opts)) opts.cache = 'no-store';

    const controller = new AbortController();
    const externalSignal = opts.signal;
    let timeout;
    if (externalSignal) {
      if (externalSignal.aborted) controller.abort(externalSignal.reason);
      else externalSignal.addEventListener('abort', () => controller.abort(externalSignal.reason), { once: true });
    }
    opts.signal = controller.signal;
    timeout = setTimeout(() => controller.abort(new DOMException('APEX request timed out', 'TimeoutError')), timeoutMs);

    const started = performance.now();
    let result;
    try {
      const response = await NATIVE_FETCH(url, opts);
      const durationMs = Math.round((performance.now() - started) * 10) / 10;
      const requestId = response.headers.get('X-APEX-Request-ID') || '';
      const serverDurationMs = response.headers.get('X-APEX-Duration-Ms') || '';
      const contentType = response.headers.get('content-type') || '';
      let data;
      if (contentType.includes('application/json')) {
        try { data = await response.json(); } catch (e) { throw new Error('Invalid JSON response'); }
      } else {
        const text = await response.text();
        try { data = text ? JSON.parse(text) : {}; } catch (_) { data = { raw: text }; }
      }
      if (!response.ok) {
        const err = new Error((data && (data.error || data.message || data.detail)) || ('HTTP ' + response.status));
        err.status = response.status; err.data = data; err.requestId = requestId;
        throw err;
      }
      const state = classify(response.status, true, data);
      result = { ok: true, data, status: response.status, state, requestId, durationMs, serverDurationMs, url: String(url), method, stale: false };
      if (cacheFallback) cache.set(requestKey(method, url), { data, at: Date.now() });
      metrics.set(requestKey(method, url), result);
      emit(result);
      return result;
    } catch (error) {
      const durationMs = Math.round((performance.now() - started) * 10) / 10;
      const cached = cacheFallback ? cache.get(requestKey(method, url)) : null;
      let data = cached ? cached.data : fallback;
      if (typeof data === 'function') data = data(error);
      const state = cached ? 'STALE' : (error && error.name === 'AbortError' || error && error.name === 'TimeoutError' ? 'UNAVAILABLE' : 'FAILED');
      result = {
        ok: false, data: data === undefined ? null : data, status: Number(error && error.status) || 0,
        state, requestId: (error && error.requestId) || '', durationMs, serverDurationMs: '',
        url: String(url), method, stale: !!cached, error: String((error && error.message) || error || 'Request failed'), at: nowIso()
      };
      metrics.set(requestKey(method, url), result);
      emit(result);
      return result;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function json(url, options) {
    const result = await request(url, options);
    return result.data;
  }

  function snapshot() {
    const rows = Array.from(metrics.values());
    const bad = rows.filter(x => x.state !== 'HEALTHY');
    return {
      total: rows.length,
      healthy: rows.length - bad.length,
      degraded: bad.length,
      status: bad.length ? 'DEGRADED' : 'HEALTHY',
      latestRequestId: rows.length ? rows[rows.length - 1].requestId : '',
      requests: rows.slice(-100)
    };
  }

  global.ApexAPI = { request, json, get: (url, options) => request(url, Object.assign({}, options || {}, { method: 'GET' })), runtimeHealth: (options) => request('/api/runtime/health', Object.assign({ timeoutMs: 6000, cacheFallback: true }, options || {}, { method: 'GET' })), snapshot };
})(window);
