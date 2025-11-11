import { state, setInventoryItems, setSelectedKey } from './state.js';
import { hexNorm, nameFromHex } from './utils/colors.js';
import { rerenderCurrentModel } from './viewer.js';
import { apiFetch } from './utils/api.js';

const REFRESH_MS = 60000;
let paletteContainer = null;
let filterInput = null;
let refreshTimer = null;

export function initPalette({ containerId, filterInputId }) {
  paletteContainer = document.getElementById(containerId);
  filterInput = document.getElementById(filterInputId);
  if (!paletteContainer) return;

  if (filterInput) {
    filterInput.addEventListener('input', () => {
      applyFilter(filterInput.value);
    });
  }

  loadPalette();
  refreshTimer = window.setInterval(loadPalette, REFRESH_MS);
}

export function disposePalette() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
  if (filterInput) {
    filterInput.value = '';
  }
  if (paletteContainer) {
    paletteContainer.innerHTML = '';
  }
}

function applyFilter(term) {
  const query = (term || '').trim().toLowerCase();
  if (!paletteContainer) return;
  if (!query) {
    renderPalette(state.inventoryItems);
    return;
  }
  const filtered = state.inventoryItems.filter((item) => {
    const material = String(item.material || '').toLowerCase();
    const colorName = String(item.color_name || '').toLowerCase();
    return material.includes(query) || colorName.includes(query);
  });
  renderPalette(filtered);
}

async function loadPalette() {
  if (!paletteContainer) return;
  try {
    const res = await apiFetch(`/inventory?nocache=${Date.now()}`);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    const rawItems = Array.isArray(data.items) ? data.items : [];
    const mapped = rawItems.map((item, index) => {
      const normalizedColor = hexNorm(item.color_hex || item.hex || '#777777');
      const isTransparent = Boolean(item.is_transparent) || /(transpar|traspar)/i.test(String(item.color_name || ''));
      const colorName = item.color_name || item.name || nameFromHex(normalizedColor, isTransparent);
      const key = item.key || `${item.material || 'mat'}_${normalizedColor}_${index}`;
      return {
        ...item,
        color: normalizedColor,
        color_name: colorName,
        is_transparent: isTransparent,
        key,
      };
    });
    setInventoryItems(mapped);
    if (filterInput && filterInput.value.trim()) {
      applyFilter(filterInput.value);
    } else {
      renderPalette(mapped);
    }
  } catch (err) {
    console.error('Errore caricamento palette', err);
    paletteContainer.innerHTML = '<div class="hint">Impossibile caricare la palette. Riprova più tardi.</div>';
  }
}

function renderPalette(items) {
  if (!paletteContainer) return;
  paletteContainer.innerHTML = '';
  const sorted = [...items].sort((a, b) => {
    const mat = String(a.material || '').localeCompare(b.material || '');
    if (mat !== 0) return mat;
    return String(a.color_name || '').localeCompare(b.color_name || '');
  });

  sorted.forEach((item) => {
    const hex = hexNorm(item.color);
    const priceText = item.price_per_kg != null
      ? `${Number(item.price_per_kg).toFixed(2)} ${item.currency || 'EUR'}/kg`
      : 'n/d';
    const colorName = item.color_name || nameFromHex(hex, item.is_transparent);

    const row = document.createElement('div');
    row.className = 'pill';
    row.dataset.key = item.key;
    row.setAttribute('role', 'option');
    row.setAttribute('aria-label', `${item.material}, ${colorName}, ${priceText}`);
    row.setAttribute('aria-selected', state.selectedKey === item.key ? 'true' : 'false');
    row.tabIndex = 0;

    const onSelect = () => {
      setSelectedKey(item.key);
      [...paletteContainer.children].forEach((child) => child.setAttribute('aria-selected', 'false'));
      row.setAttribute('aria-selected', 'true');
      rerenderCurrentModel();
    };

    row.addEventListener('click', onSelect);
    row.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        onSelect();
      }
    });

    const left = document.createElement('div');
    left.className = 'left';
    const dot = document.createElement('span');
    dot.className = 'dot' + (item.is_transparent ? ' transparent' : '');
    if (!item.is_transparent) {
      dot.style.backgroundColor = hex;
    }
    dot.title = colorName;
    dot.setAttribute('aria-hidden', 'true');

    const col = document.createElement('div');
    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = item.material || 'n/d';
    const subtitle = document.createElement('div');
    subtitle.className = 'sub';
    subtitle.textContent = colorName;
    col.appendChild(title);
    col.appendChild(subtitle);

    left.appendChild(dot);
    left.appendChild(col);

    const price = document.createElement('div');
    price.className = 'price';
    price.textContent = priceText;

    row.appendChild(left);
    row.appendChild(price);
    paletteContainer.appendChild(row);
  });
}
