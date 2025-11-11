const rawBase = (document.body && document.body.dataset ? document.body.dataset.apiBase : '') || '';
const API_BASE = rawBase.replace(/\/+$/, '');

export function getApiBase() {
  return API_BASE;
}

export function buildApiUrl(path) {
  if (!path) return API_BASE || '/';
  let normalized = path.startsWith('/') ? path : `/${path}`;
  if (!API_BASE) {
    return normalized;
  }
  if (normalized === API_BASE || normalized.startsWith(`${API_BASE}/`)) {
    return normalized;
  }
  return `${API_BASE}${normalized}`;
}

export function apiFetch(path, options) {
  return fetch(buildApiUrl(path), options);
}
