/* APEX 66.3.3 — safe structured-value presentation boundary.
 * Backend contracts remain structured; UI renderers must never rely on
 * JavaScript's implicit object -> string coercion.
 */
(function (root) {
  'use strict';

  const PREFERRED_KEYS = [
    'label', 'title', 'name', 'text', 'note', 'reason', 'summary',
    'executive_summary', 'primary_thesis', 'current_thesis', 'description',
    'direction', 'institutional_bias', 'bias', 'state', 'status', 'regime',
    'market_regime', 'decision', 'decision_state', 'action', 'type', 'value'
  ];

  const TOKEN_KEYS = [
    'direction', 'bias', 'state', 'status', 'regime', 'decision',
    'decision_state', 'action', 'label', 'name', 'type', 'value'
  ];

  function isScalar(v) {
    return v === null || v === undefined || ['string', 'number', 'boolean', 'bigint'].includes(typeof v);
  }

  function scalarString(v) {
    if (v === null || v === undefined) return null;
    if (typeof v === 'string') return v.trim();
    if (typeof v === 'number') return Number.isFinite(v) ? String(v) : null;
    if (typeof v === 'boolean' || typeof v === 'bigint') return String(v);
    return null;
  }

  function firstReadable(obj, keys, depth) {
    for (const key of keys) {
      if (!Object.prototype.hasOwnProperty.call(obj, key)) continue;
      const rendered = toText(obj[key], '', { depth: depth + 1, maxDepth: 4 });
      if (rendered) return rendered;
    }
    return '';
  }

  function toText(value, fallback, options) {
    const opts = options || {};
    const depth = Number(opts.depth || 0);
    const maxDepth = Number(opts.maxDepth || 4);
    const emptyFallback = fallback === undefined ? '—' : fallback;

    const scalar = scalarString(value);
    if (scalar !== null) return scalar || emptyFallback;
    if (depth >= maxDepth) return emptyFallback;

    if (Array.isArray(value)) {
      const parts = value
        .map(v => toText(v, '', { depth: depth + 1, maxDepth }))
        .filter(Boolean);
      return parts.length ? parts.join(opts.separator || ' · ') : emptyFallback;
    }

    if (value && typeof value === 'object') {
      const preferred = firstReadable(value, opts.keys || PREFERRED_KEYS, depth);
      if (preferred) return preferred;

      // Last-resort structured summary: readable scalar leaf values only.
      // Never stringify the object itself.
      const leaves = [];
      for (const [key, val] of Object.entries(value)) {
        if (!isScalar(val)) continue;
        const rendered = scalarString(val);
        if (rendered) leaves.push(`${key.replace(/_/g, ' ')}: ${rendered}`);
        if (leaves.length >= 3) break;
      }
      return leaves.length ? leaves.join(' · ') : emptyFallback;
    }

    return emptyFallback;
  }

  function token(value, fallback) {
    const out = toText(value, fallback === undefined ? 'UNKNOWN' : fallback, { keys: TOKEN_KEYS });
    return String(out || fallback || 'UNKNOWN').trim();
  }

  function evidence(value, fallback) {
    if (isScalar(value)) return toText(value, fallback === undefined ? '' : fallback);
    if (!value || typeof value !== 'object') return fallback || '';

    const source = toText(value.source || value.engine_name || value.engine || value.domain, '', { keys: ['label', 'name', 'value'] });
    const body = toText(value.note || value.reason || value.label || value.text || value.summary || value.description, '');
    const direction = token(value.direction || value.bias || '', '');

    const parts = [];
    if (source) parts.push(source.replace(/_/g, ' '));
    if (body) parts.push(body);
    if (!body && direction) parts.push(direction.replace(/_/g, ' '));
    return parts.join(': ') || toText(value, fallback === undefined ? '' : fallback);
  }

  function list(value, fallback) {
    if (!Array.isArray(value)) {
      const one = evidence(value, '');
      return one ? [one] : (fallback ? [fallback] : []);
    }
    const out = value.map(v => evidence(v, '')).filter(Boolean);
    return out.length ? out : (fallback ? [fallback] : []);
  }

  function escapeHtml(value, fallback) {
    return toText(value, fallback === undefined ? '' : fallback)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  root.APEXDisplay = Object.freeze({ toText, token, evidence, list, escapeHtml });
})(window);
