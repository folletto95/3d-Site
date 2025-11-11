import { initPalette } from './palette.js';
import { initPresets } from './presets.js';
import { state, getSelectedInventoryItem } from './state.js';
import { resetViewer, showViewer } from './viewer.js';
import { apiFetch } from './utils/api.js';

const viewerElement = document.getElementById('viewer');
const fileInput = document.getElementById('file');
const urlInput = document.getElementById('url');
const fetchButton = document.getElementById('btnFetch');
const deleteButton = document.getElementById('btnDelete');
const estimateButton = document.getElementById('btnEstimate');
const outputElement = document.getElementById('out');

initPalette({ containerId: 'palette', filterInputId: 'paletteFilter' });
initPresets('preset');
setupViewerInteractions();
setupFileInputs();
setupWizard();

if (fetchButton) {
  fetchButton.addEventListener('click', handleFetchFromUrl);
}
if (estimateButton) {
  estimateButton.addEventListener('click', handleEstimate);
}
if (deleteButton) {
  deleteButton.addEventListener('click', () => {
    resetViewer();
    if (fileInput) fileInput.value = '';
    if (outputElement) outputElement.innerHTML = '';
  });
}

function setupViewerInteractions() {
  if (!viewerElement) return;
  viewerElement.addEventListener('dragenter', (event) => {
    event.preventDefault();
    viewerElement.classList.add('drag');
  });
  viewerElement.addEventListener('dragover', (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
    viewerElement.classList.add('drag');
  });
  viewerElement.addEventListener('dragleave', (event) => {
    if (!viewerElement.contains(event.relatedTarget)) {
      viewerElement.classList.remove('drag');
    }
  });
  viewerElement.addEventListener('drop', (event) => {
    event.preventDefault();
    viewerElement.classList.remove('drag');
    const file = event.dataTransfer.files && event.dataTransfer.files[0];
    if (file) {
      uploadFileOrBlob(file);
    }
  });
}

function setupFileInputs() {
  if (!fileInput) return;
  fileInput.addEventListener('change', () => {
    const files = fileInput.files;
    if (!files || !files.length) return;
    Array.from(files).forEach((file) => {
      if (file) uploadFileOrBlob(file);
    });
    fileInput.value = '';
  });
}

async function uploadFileOrBlob(file) {
  setViewerStatus('Caricamento modello…');
  const formData = new FormData();
  formData.append('file', file);
  try {
    const response = await apiFetch('/upload_model', { method: 'POST', body: formData });
    if (!response.ok) {
      throw new Error(`Upload fallito (${response.status})`);
    }
    const data = await parseJson(response);
    if (!data.viewer_url) {
      throw new Error('Risposta non valida dal server');
    }
    await showViewer(data.viewer_url, data.filename);
  } catch (error) {
    alert(error.message || 'Upload fallito');
    resetViewer();
  }
}

async function handleFetchFromUrl() {
  if (!urlInput) return;
  const url = urlInput.value.trim();
  if (!url) {
    alert('Inserisci una URL');
    return;
  }
  setViewerStatus('Caricamento modello da URL...');
  try {
    const response = await apiFetch('/fetch_model', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await parseJson(response);
    if (!response.ok) {
      throw new Error(data.detail || `Errore caricamento (${response.status})`);
    }
    if (!data.viewer_url) {
      throw new Error(data.detail || 'Nessun modello trovato');
    }
    await showViewer(data.viewer_url, data.filename);
  } catch (error) {
    alert(error.message || 'Caricamento da URL fallito');
    resetViewer();
  }
}

async function handleEstimate() {
  if (!state.currentViewerUrl) {
    alert('Carica prima un modello');
    return;
  }
  if (!state.selectedKey) {
    alert('Seleziona un materiale dalla palette');
    return;
  }
  if (!estimateButton) return;

  estimateButton.disabled = true;
  const previousText = estimateButton.textContent;
  estimateButton.textContent = 'Calcolo...';
  if (outputElement) {
    outputElement.innerHTML = 'Calcolo in corso...';
  }

  const payload = {
    viewer_url: state.currentViewerUrl,
    inventory_key: state.selectedKey,
    machine: state.selectedMachine,
    settings: {
      machine: state.selectedMachine,
      layer_h: parseFloat(getValue('layer_h', '0.2')),
      infill: parseFloat(getValue('infill', '15')),
      nozzle: parseFloat(getValue('nozzle', '0.4')),
      print_speed: parseFloat(getValue('print_speed', '60')),
      travel_speed: parseFloat(getValue('travel_speed', '150')),
    },
  };

  try {
    const selectedItem = getSelectedInventoryItem();
    const data = await requestEstimate(payload, selectedItem);
    if (outputElement) {
      const currency = data.currency || (selectedItem && selectedItem.currency) || 'EUR';
      const minutes = formatMinutes(data.time_s);
      const filament = formatNumber(data.filament_g, 1);
      const costFilament = formatCurrency(data.cost_filament, currency);
      const costMachine = formatCurrency(data.cost_machine, currency);
      const totalCost = formatCurrency(data.total, currency);
      let html = `
        Tempo: <b>${minutes != null ? `${minutes} min` : 'n/d'}</b> — Filamento: <b>${filament != null ? `${filament} g` : 'n/d'}</b><br>
        Costo filamento: <b>${costFilament}</b> — Costo macchina: <b>${costMachine}</b><br>
        Totale: <b>${totalCost}</b>
      `;
      if (data.gcode_url) {
        html += ` — <a href="${data.gcode_url}" target="_blank" style="color:var(--accent)">Scarica G-code</a>`;
      }
      outputElement.innerHTML = html;
    }
  } catch (error) {
    alert(error.message || 'Errore stima');
    if (outputElement) {
      outputElement.innerHTML = '';
    }
  } finally {
    estimateButton.disabled = false;
    estimateButton.textContent = previousText || 'Stima';
  }
}

function setViewerStatus(message) {
  if (viewerElement) {
    viewerElement.classList.remove('drag');
    viewerElement.textContent = message;
  }
}

function getValue(id, fallback) {
  const element = document.getElementById(id);
  if (!element) return fallback;
  return element.value || fallback;
}

async function parseJson(response) {
  try {
    return await response.json();
  } catch (error) {
    throw new Error('Risposta non valida dal server');
  }
}

async function requestEstimate(payload, selectedItem) {
  const response = await apiFetch('/slice/estimate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (response.status === 404) {
    let detail = null;
    try {
      const cloned = await response.clone().json();
      detail = cloned && cloned.detail ? String(cloned.detail) : null;
      if (detail && detail.toLowerCase() !== 'not found') {
        throw new Error(detail);
      }
    } catch (error) {
      if (detail) {
        throw error;
      }
    }
    return requestLegacyEstimate(payload, selectedItem);
  }

  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(data.detail || 'Errore stima');
  }
  return data;
}

async function requestLegacyEstimate(payload, selectedItem) {
  if (!selectedItem) {
    throw new Error('Materiale non valido per la stima');
  }
  const formData = new FormData();
  const legacyViewerUrl = convertLegacyViewerUrl(payload.viewer_url);
  if (legacyViewerUrl) {
    formData.append('viewer_url', legacyViewerUrl);
  }
  const presetSelect = document.getElementById('preset');
  if (presetSelect && presetSelect.value) {
    formData.append('preset_print', presetSelect.value);
  }
  if (selectedItem.material) {
    formData.append('material', selectedItem.material);
  }
  if (selectedItem.diameter_mm != null) {
    formData.append('diameter', String(selectedItem.diameter_mm));
  }
  if (selectedItem.price_per_kg != null) {
    formData.append('price_per_kg', String(selectedItem.price_per_kg));
  }

  let appendedFile = false;
  const modelBlob = await fetchModelForLegacy(payload.viewer_url);
  if (modelBlob) {
    const filename = inferFallbackFilename(payload.viewer_url, state.lastModelName);
    formData.append('model', modelBlob, filename);
    appendedFile = true;
  }

  const response = await apiFetch('/api/estimate', {
    method: 'POST',
    body: formData,
  });
  if (!response.ok && !appendedFile) {
    // Alcuni ambienti legacy richiedono obbligatoriamente il file del modello;
    // se la prima richiesta fallisce e non l'abbiamo allegato, riprova con il blob.
    const retryForm = new FormData();
    if (legacyViewerUrl) {
      retryForm.append('viewer_url', legacyViewerUrl);
    }
    if (presetSelect && presetSelect.value) {
      retryForm.append('preset_print', presetSelect.value);
    }
    if (selectedItem.material) {
      retryForm.append('material', selectedItem.material);
    }
    if (selectedItem.diameter_mm != null) {
      retryForm.append('diameter', String(selectedItem.diameter_mm));
    }
    if (selectedItem.price_per_kg != null) {
      retryForm.append('price_per_kg', String(selectedItem.price_per_kg));
    }
    const retryBlob = await fetchModelForLegacy(payload.viewer_url);
    if (retryBlob) {
      const retryName = inferFallbackFilename(payload.viewer_url, state.lastModelName);
      retryForm.append('model', retryBlob, retryName);
      const retryResponse = await apiFetch('/api/estimate', {
        method: 'POST',
        body: retryForm,
      });
      return await handleLegacyResponse(retryResponse, selectedItem);
    }
  }
  return await handleLegacyResponse(response, selectedItem);
}

async function handleLegacyResponse(response, selectedItem) {
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(data.detail || 'Errore stima');
  }

  const costFilament = toNumber(data.cost_material ?? data.cost_filament);
  const costMachine = toNumber(data.cost_machine);
  let total = toNumber(data.cost_total ?? data.total);
  if (total == null && costFilament != null && costMachine != null) {
    total = costFilament + costMachine;
  }

  return {
    time_s: toNumber(data.time_s),
    filament_g: toNumber(data.filament_g),
    cost_filament: costFilament,
    cost_machine: costMachine,
    total,
    currency: data.currency || selectedItem.currency || 'EUR',
    gcode_url: data.gcode_url || data.download_url || null,
  };
}

function convertLegacyViewerUrl(url) {
  if (!url) return null;
  if (url.startsWith('/ui/uploads/')) return url;
  if (url.startsWith('/files/')) {
    const name = url.split('/').pop();
    if (name) {
      const clean = name.split('?')[0];
      if (clean) {
        return `/ui/uploads/${clean}`;
      }
    }
  }
  return url;
}

async function fetchModelForLegacy(url) {
  if (!url) return null;
  try {
    const response = await fetch(url);
    if (!response.ok) {
      return null;
    }
    const blob = await response.blob();
    if (!blob) {
      return null;
    }
    return blob;
  } catch (error) {
    console.warn('Impossibile recuperare il modello per il fallback legacy', error);
    return null;
  }
}

function inferFallbackFilename(url, fallback) {
  if (fallback && typeof fallback === 'string' && fallback.trim()) {
    return fallback.trim();
  }
  if (url && typeof url === 'string') {
    try {
      const raw = url.split('/').filter(Boolean).pop();
      if (raw) {
        const clean = raw.split('?')[0];
        if (clean) {
          return decodeURIComponent(clean);
        }
      }
    } catch (error) {
      // ignora e usa fallback generico
    }
  }
  return 'model.stl';
}

function toNumber(value) {
  if (value == null) return null;
  const num = Number(value);
  if (Number.isNaN(num) || !Number.isFinite(num)) {
    return null;
  }
  return num;
}

function formatNumber(value, digits) {
  const num = toNumber(value);
  if (num == null) return null;
  if (typeof digits === 'number') {
    return num.toFixed(digits);
  }
  return String(num);
}

function formatCurrency(value, currency) {
  const num = formatNumber(value, 2);
  if (num == null) return 'n/d';
  const curr = currency || '';
  return curr ? `${num} ${curr}` : num;
}

function formatMinutes(seconds) {
  const num = toNumber(seconds);
  if (num == null) return null;
  return Math.round(num / 60);
}

function setupWizard() {
  const wizardButton = document.getElementById('btnWizard');
  const wizardOverlay = document.getElementById('wizard');
  const wizardClose = document.getElementById('wizardClose');
  if (wizardButton && wizardOverlay) {
    wizardButton.addEventListener('click', () => {
      wizardOverlay.style.display = 'block';
    });
  }
  if (wizardClose && wizardOverlay) {
    wizardClose.addEventListener('click', () => {
      wizardOverlay.style.display = 'none';
    });
  }
}
