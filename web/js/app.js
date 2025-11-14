import { initPalette } from './palette.js';
import { initPresets, getPresetDefinition, getPresetProfileName, getPresetPrinterProfile } from './presets.js';
import { state, getSelectedInventoryItem, setSelectedMachine } from './state.js';
import { resetViewer, showViewer } from './viewer.js';
import { apiFetch, getApiBase } from './utils/api.js';

const viewerElement = document.getElementById('viewer');
const fileInput = document.getElementById('file');
const urlInput = document.getElementById('url');
const fetchButton = document.getElementById('btnFetch');
const deleteButton = document.getElementById('btnDelete');
const estimateButton = document.getElementById('btnEstimate');
const outputElement = document.getElementById('out');
const WIZARD_STORAGE_KEY = 'magazzinoWizardSeen';

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

  const presetSelect = document.getElementById('preset');
  const presetKey = presetSelect && presetSelect.value ? presetSelect.value : '';
  const presetDefinition = getPresetDefinition(presetKey);
  const machineFromPreset = (presetDefinition && presetDefinition.machine) || state.selectedMachine || 'generic';
  const presetProfileName = getPresetProfileName(presetKey);
  const presetPrinterProfile = getPresetPrinterProfile(presetKey);
  const presetLayer = presetDefinition && typeof presetDefinition.layer_h === 'number' ? presetDefinition.layer_h : undefined;
  const presetInfill = presetDefinition && typeof presetDefinition.infill === 'number' ? presetDefinition.infill : undefined;
  const presetNozzle = presetDefinition && typeof presetDefinition.nozzle === 'number' ? presetDefinition.nozzle : undefined;
  const presetPrintSpeed = presetDefinition && typeof presetDefinition.print_speed === 'number' ? presetDefinition.print_speed : undefined;
  const presetTravelSpeed = presetDefinition && typeof presetDefinition.travel_speed === 'number' ? presetDefinition.travel_speed : undefined;

  const parsedLayer = parseFloat(getValue('layer_h', presetLayer != null ? String(presetLayer) : '0.2'));
  const parsedInfill = parseFloat(getValue('infill', presetInfill != null ? String(presetInfill) : '15'));
  const parsedNozzle = parseFloat(getValue('nozzle', presetNozzle != null ? String(presetNozzle) : '0.4'));
  const parsedPrintSpeed = parseFloat(getValue('print_speed', presetPrintSpeed != null ? String(presetPrintSpeed) : '60'));
  const parsedTravelSpeed = parseFloat(getValue('travel_speed', presetTravelSpeed != null ? String(presetTravelSpeed) : '150'));

  const payload = {
    viewer_url: state.currentViewerUrl,
    inventory_key: state.selectedKey,
    machine: machineFromPreset,
    preset_print: presetProfileName || undefined,
    preset_printer: presetPrinterProfile || undefined,
    settings: {
      machine: machineFromPreset,
      layer_h: Number.isFinite(parsedLayer) ? parsedLayer : (presetLayer != null ? presetLayer : 0.2),
      infill: Number.isFinite(parsedInfill) ? parsedInfill : (presetInfill != null ? presetInfill : 15),
      nozzle: Number.isFinite(parsedNozzle) ? parsedNozzle : (presetNozzle != null ? presetNozzle : 0.4),
      print_speed: Number.isFinite(parsedPrintSpeed) ? parsedPrintSpeed : (presetPrintSpeed != null ? presetPrintSpeed : 60),
      travel_speed: Number.isFinite(parsedTravelSpeed) ? parsedTravelSpeed : (presetTravelSpeed != null ? presetTravelSpeed : 150),
    },
  };

  if (presetDefinition && presetDefinition.machine && machineFromPreset !== state.selectedMachine) {
    setSelectedMachine(presetDefinition.machine);
  }

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
      const presetUsed = data && data.preset_print_used ? String(data.preset_print_used) : null;
      const presetDefault = Boolean(data && data.preset_print_is_default);
      let html = `
        Tempo: <b>${minutes != null ? `${minutes} min` : 'n/d'}</b> — Filamento: <b>${filament != null ? `${filament} g` : 'n/d'}</b><br>
        Costo filamento: <b>${costFilament}</b> — Costo macchina: <b>${costMachine}</b><br>
        Totale: <b>${totalCost}</b>
      `;
      if (data.gcode_url) {
        html += ` — <a href="${data.gcode_url}" target="_blank" style="color:var(--accent)">Scarica G-code</a>`;
      }
      if (presetUsed) {
        const presetLabel = presetDefault ? `${presetUsed} (default)` : presetUsed;
        html += `<br>Preset Prusa: <b>${escapeHtml(presetLabel)}</b>`;
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
  const data = await requestModernEstimate(payload, selectedItem);
  if (data != null) {
    return data;
  }
  return requestLegacyEstimate(payload, selectedItem);
}

async function requestModernEstimate(payload, selectedItem) {
  const attempted = new Set();
  const paths = buildModernEstimatePaths();
  let last404 = null;

  for (const path of paths) {
    if (!path || attempted.has(path)) continue;
    attempted.add(path);
    try {
      const response = await apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (response.status === 404) {
        const detail = await readErrorDetail(response);
        if (detail && detail.toLowerCase() !== 'not found') {
          throw createHttpError(detail, response.status, path);
        }
        last404 = createHttpError('Not found', response.status, path, detail);
        continue;
      }

      const data = await parseJson(response);
      if (!response.ok) {
        throw createHttpError(data.detail || 'Errore stima', response.status, path, data.detail);
      }
      return normalizeEstimateResponse(data, selectedItem);
    } catch (error) {
      if (error && error.status === 404) {
        last404 = error;
        continue;
      }
      if (error && error.name === 'TypeError') {
        // Network failures produce TypeError; try next path.
        continue;
      }
      throw error;
    }
  }

  if (last404) {
    console.warn('Modern estimate endpoint non trovato, ricado sul fallback legacy', last404);
  }
  return null;
}

function buildModernEstimatePaths() {
  const paths = ['/slice/estimate'];
  const base = getApiBase();
  if (!base) {
    paths.push('/api/slice/estimate');
  }
  return paths;
}

async function readErrorDetail(response) {
  try {
    const data = await response.clone().json();
    if (data && data.detail) {
      return String(data.detail);
    }
  } catch (error) {
    // ignore JSON parse errors
  }
  return null;
}

function createHttpError(message, status, path, detail = null) {
  const error = new Error(message);
  error.status = status;
  error.path = path;
  error.detail = detail;
  return error;
}

async function requestLegacyEstimate(payload, selectedItem) {
  if (!selectedItem) {
    throw new Error('Materiale non valido per la stima');
  }
  const formData = new FormData();
  const legacyViewerUrl = convertLegacyViewerUrl(payload.viewer_url);
  if (legacyViewerUrl || payload.viewer_url) {
    formData.delete('model_url');
  }
  if (legacyViewerUrl) {
    formData.append('viewer_url', legacyViewerUrl);
    formData.append('model_url', legacyViewerUrl);
  }
  if (payload.viewer_url && payload.viewer_url !== legacyViewerUrl) {
    formData.append('model_url', payload.viewer_url);
  }
  const presetSelect = document.getElementById('preset');
  const presetValue = payload && payload.preset_print ? payload.preset_print : (presetSelect && presetSelect.value);
  const printerPresetValue = payload && payload.preset_printer ? payload.preset_printer : null;
  if (presetValue) {
    formData.append('preset_print', presetValue);
  }
  if (printerPresetValue) {
    formData.append('preset_printer', printerPresetValue);
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
    cache: 'no-store',
  });
  if (!response.ok && !appendedFile) {
    // Alcuni ambienti legacy richiedono obbligatoriamente il file del modello;
    // se la prima richiesta fallisce e non l'abbiamo allegato, riprova con il blob.
    const retryForm = new FormData();
    if (legacyViewerUrl || payload.viewer_url) {
      retryForm.delete('model_url');
    }
    if (legacyViewerUrl) {
      retryForm.append('viewer_url', legacyViewerUrl);
      retryForm.append('model_url', legacyViewerUrl);
    }
    if (payload.viewer_url && payload.viewer_url !== legacyViewerUrl) {
      retryForm.append('model_url', payload.viewer_url);
    }
    if (presetValue) {
      retryForm.append('preset_print', presetValue);
    }
    if (printerPresetValue) {
      retryForm.append('preset_printer', printerPresetValue);
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
        cache: 'no-store',
      });
      return await handleLegacyResponse(retryResponse, selectedItem);
    }
  }
  return await handleLegacyResponse(response, selectedItem);
}

async function handleLegacyResponse(response, selectedItem) {
  const data = await parseJson(response);
  if (!response.ok) {
    const detail = (data && data.detail) ? String(data.detail) : '';
    if (detail && /prusaslicer\s+non\s+trovato/i.test(detail)) {
      throw new Error(
        'Il server legacy richiede PrusaSlicer ma non è installato. ' +
        'Aggiorna o ricostruisci il container slicer con PrusaSlicer oppure abilita l\'endpoint moderno /slice/estimate.'
      );
    }
    throw new Error(detail || 'Errore stima');
  }
  return normalizeEstimateResponse(data, selectedItem);
}

function normalizeEstimateResponse(data, selectedItem) {
  const source = (data && typeof data === 'object') ? data : {};
  const costFilament = toNumber(source.cost_material ?? source.cost_filament);
  const costMachine = toNumber(source.cost_machine);
  let total = toNumber(source.cost_total ?? source.total);
  if (total == null && costFilament != null && costMachine != null) {
    total = costFilament + costMachine;
  }

  const presetsUsed = normalizePresetsUsed(source.presets_used);
  const presetPrintUsed = extractPresetUsed(source, 'print', presetsUsed);
  const presetPrinterUsed = extractPresetUsed(source, 'printer', presetsUsed);
  const presetFilamentUsed = extractPresetUsed(source, 'filament', presetsUsed);
  const presetPrintDefault = determinePresetDefault(source, presetsUsed, 'print');

  return {
    time_s: toNumber(source.time_s),
    filament_g: toNumber(source.filament_g),
    cost_filament: costFilament,
    cost_machine: costMachine,
    total,
    currency: source.currency || (selectedItem && selectedItem.currency) || 'EUR',
    gcode_url: source.gcode_url || source.download_url || null,
    preset_print_used: presetPrintUsed,
    preset_printer_used: presetPrinterUsed,
    preset_filament_used: presetFilamentUsed,
    preset_print_is_default: presetPrintDefault,
    presets_used: presetsUsed,
  };
}

function normalizePresetsUsed(raw) {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const kinds = ['print', 'filament', 'printer'];
  const normalized = {};
  for (const kind of kinds) {
    const value = raw[kind];
    if (!value || typeof value !== 'object') {
      continue;
    }
    const path = safeString(value.path);
    const filename = safeString(value.filename) || (path ? path.split('/').pop() : null);
    const foundFlag = value.found;
    const found = foundFlag === true || (typeof foundFlag === 'string' && foundFlag.trim().toLowerCase() === 'true');
    const isDefaultFlag = value.is_default;
    const isDefault = (
      isDefaultFlag === true ||
      (typeof isDefaultFlag === 'string' && isDefaultFlag.trim().toLowerCase() === 'true') ||
      (foundFlag === false || (typeof foundFlag === 'string' && foundFlag.trim().toLowerCase() === 'false'))
    );
    normalized[kind] = {
      requested: safeString(value.requested ?? value.selected ?? value.desired),
      path,
      filename,
      found,
      is_default: isDefault,
    };
  }
  return Object.keys(normalized).length ? normalized : null;
}

function extractPresetUsed(data, kind, presetsUsed) {
  if (presetsUsed && presetsUsed[kind]) {
    const entry = presetsUsed[kind];
    if (entry.filename) {
      return entry.filename;
    }
    if (entry.path) {
      return entry.path;
    }
    if (entry.requested) {
      return entry.requested;
    }
  }
  const directKey = safeString(data[`preset_${kind}_used`]);
  if (directKey) {
    return directKey;
  }
  const fallback = safeString(data[`preset_${kind}`]);
  return fallback;
}

function determinePresetDefault(data, presetsUsed, kind) {
  if (presetsUsed && presetsUsed[kind]) {
    const entry = presetsUsed[kind];
    if (entry.is_default === true) {
      return true;
    }
    if (entry.found === false) {
      return true;
    }
    return false;
  }
  if (data && Object.prototype.hasOwnProperty.call(data, `preset_${kind}_is_default`)) {
    const flag = data[`preset_${kind}_is_default`];
    if (flag === true) {
      return true;
    }
    if (flag === false) {
      return false;
    }
    if (typeof flag === 'string') {
      const low = flag.trim().toLowerCase();
      if (low === 'true' || low === '1' || low === 'yes') {
        return true;
      }
      if (low === 'false' || low === '0' || low === 'no') {
        return false;
      }
    }
  }
  return false;
}

function safeString(value) {
  if (value == null) {
    return null;
  }
  const text = String(value);
  const trimmed = text.trim();
  return trimmed ? trimmed : null;
}

function escapeHtml(value) {
  if (value == null) {
    return '';
  }
  return String(value).replace(/[&<>"']/g, (char) => {
    switch (char) {
      case '&':
        return '&amp;';
      case '<':
        return '&lt;';
      case '>':
        return '&gt;';
      case '"':
        return '&quot;';
      case '\'':
        return '&#39;';
      default:
        return char;
    }
  });
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
  const candidates = buildLegacyDownloadCandidates(url);
  for (const candidate of candidates) {
    try {
      const response = await fetch(candidate);
      if (!response.ok) {
        continue;
      }
      const blob = await response.blob();
      if (blob) {
        return blob;
      }
    } catch (error) {
      console.warn('Impossibile recuperare il modello per il fallback legacy', error);
    }
  }
  return null;
}

function buildLegacyDownloadCandidates(url) {
  const candidates = [];
  if (!url) {
    return candidates;
  }
  const unique = new Set();
  const push = (value) => {
    if (!value) return;
    if (!unique.has(value)) {
      unique.add(value);
      candidates.push(value);
    }
  };

  push(url);

  if (typeof url === 'string' && url.startsWith('/')) {
    const base = getApiBase();
    if (base) {
      const normalizedBase = base.endsWith('/') ? base.slice(0, -1) : base;
      push(`${normalizedBase}${url}`);
    } else if (!url.startsWith('/api/')) {
      push(`/api${url}`);
    }
  }

  return candidates;
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
  if (!wizardOverlay) {
    return;
  }

  const isOpen = () => wizardOverlay.getAttribute('aria-hidden') === 'false';
  const openWizard = () => {
    wizardOverlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('wizard-open');
    if (wizardClose) {
      wizardClose.focus();
    }
  };
  const closeWizard = () => {
    wizardOverlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('wizard-open');
    markWizardSeen();
    if (wizardButton) {
      wizardButton.focus();
    }
  };

  if (wizardButton) {
    wizardButton.addEventListener('click', () => {
      if (!isOpen()) {
        openWizard();
      }
    });
  }

  if (wizardClose) {
    wizardClose.addEventListener('click', () => {
      if (isOpen()) {
        closeWizard();
      }
    });
  }

  wizardOverlay.addEventListener('click', (event) => {
    if (event.target === wizardOverlay && isOpen()) {
      closeWizard();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && isOpen()) {
      closeWizard();
    }
  });

  if (!hasWizardBeenSeen()) {
    openWizard();
  }
}

function hasWizardBeenSeen() {
  try {
    return window.localStorage.getItem(WIZARD_STORAGE_KEY) === '1';
  } catch (error) {
    return false;
  }
}

function markWizardSeen() {
  try {
    window.localStorage.setItem(WIZARD_STORAGE_KEY, '1');
  } catch (error) {
    // Ignora errori di storage (es. modalità privata)
  }
}
