import { initPalette } from './palette.js';
import { initPresets, getPresetDefinition, getPresetProfileName, getPresetFilamentProfile, getPresetPrinterProfile } from './presets.js';
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
let isEstimating = false;
const WIZARD_STORAGE_KEY = 'magazzinoWizardSeen';

initPalette({ containerId: 'palette', filterInputId: 'paletteFilter' });
initPresets('preset');
setupViewerInteractions();
setupFileInputs();
setupWizard();

function getSelectedPresetLabel() {
  const select = document.getElementById('preset');
  if (!select) {
    return '';
  }
  const option = select.options[select.selectedIndex];
  return (option && option.text) || select.value || '';
}

if (fetchButton) {
  fetchButton.addEventListener('click', handleFetchFromUrl);
}
if (estimateButton) {
  estimateButton.addEventListener('click', () => handleEstimate());
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

async function handleEstimate(options = {}) {
  const silent = Boolean(options && options.silent);
  if (isEstimating) {
    if (!silent) {
      alert('Una stima è già in corso, attendi il completamento.');
    }
    return null;
  }
  if (!state.currentViewerUrl) {
    if (!silent) {
      alert('Carica prima un modello');
    }
    return null;
  }
  if (!state.selectedKey) {
    if (!silent) {
      alert('Seleziona un materiale dalla palette');
    }
    return null;
  }
  if (!estimateButton) {
    return null;
  }

  isEstimating = true;
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
  const presetFilamentProfile = getPresetFilamentProfile(presetKey);
  const presetPrinterProfile = getPresetPrinterProfile(presetKey);
  const payload = {
    viewer_url: state.currentViewerUrl,
    inventory_key: state.selectedKey,
    machine: machineFromPreset,
    preset_print: presetProfileName || undefined,
    preset_filament: presetFilamentProfile || undefined,
    preset_printer: presetPrinterProfile || undefined,
  };

  const manualSettings = collectManualOverrides(presetDefinition);
  if (manualSettings) {
    payload.settings = manualSettings;
  }

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
      const selectedPresetLabel = getSelectedPresetLabel();
      const presetUsageHtml = renderPresetUsage(data && data.presets_used);
      let html = `
        Tempo: <b>${minutes != null ? `${minutes} min` : 'n/d'}</b> — Filamento: <b>${filament != null ? `${filament} g` : 'n/d'}</b><br>
        Costo filamento: <b>${costFilament}</b> — Costo macchina: <b>${costMachine}</b><br>
        Totale: <b>${totalCost}</b><br>
        <p style="margin:6px 0 0;">Preset slicer: <span id="estimate-preset-value">—</span></p>
      `;
      if (data.gcode_url) {
        html += ` — <a href="${data.gcode_url}" target="_blank" style="color:var(--accent)">Scarica G-code</a>`;
      }
      if (presetUsageHtml) {
        html += `<br>${presetUsageHtml}`;
      }
      const debugHtml = renderEstimateDebug(data.debug);
      if (debugHtml) {
        html += `<br>${debugHtml}`;
      }
      outputElement.innerHTML = html;
      const presetValueElement = document.getElementById('estimate-preset-value');
      if (presetValueElement) {
        presetValueElement.textContent = selectedPresetLabel || 'N/D';
      }
    }
    return data;
  } catch (error) {
    if (!silent) {
      alert(error.message || 'Errore stima');
    } else {
      console.error('Stima automatica fallita', error);
    }
    if (outputElement) {
      outputElement.innerHTML = '';
    }
    return null;
  } finally {
    isEstimating = false;
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

function collectManualOverrides(presetDefinition) {
  const overrides = {};
  let hasOverrides = false;

  const numericFields = [
    { id: 'layer_h', key: 'layer_h' },
    { id: 'infill', key: 'infill' },
    { id: 'nozzle', key: 'nozzle' },
    { id: 'print_speed', key: 'print_speed' },
    { id: 'travel_speed', key: 'travel_speed' },
  ];

  const tolerance = 1e-6;

  for (const field of numericFields) {
    const element = document.getElementById(field.id);
    if (!element) {
      continue;
    }
    const raw = typeof element.value === 'string' ? element.value.trim() : '';
    if (!raw) {
      continue;
    }
    const value = Number(raw.replace(',', '.'));
    if (!Number.isFinite(value)) {
      continue;
    }

    const presetValue =
      presetDefinition && typeof presetDefinition[field.key] === 'number'
        ? Number(presetDefinition[field.key])
        : null;

    if (presetValue == null || Math.abs(value - presetValue) > tolerance) {
      overrides[field.key] = value;
      hasOverrides = true;
    }
  }

  return hasOverrides ? overrides : null;
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
  const presetFilamentValue = payload && payload.preset_filament ? payload.preset_filament : null;
  const printerPresetValue = payload && payload.preset_printer ? payload.preset_printer : null;
  if (presetValue) {
    formData.append('preset_print', presetValue);
  }
  if (presetFilamentValue) {
    formData.append('preset_filament', presetFilamentValue);
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
    if (presetFilamentValue) {
      retryForm.append('preset_filament', presetFilamentValue);
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

  const prusaCmd = normalizePrusaslicerCmd(source.prusaslicer_cmd);
  const prusaOverrides = normalizePrusaOverrides(source.override_settings);
  const debug = normalizeEstimateDebug(source.debug);
  if (prusaCmd || prusaOverrides) {
    const enriched = debug && typeof debug === 'object' ? debug : {};
    if (prusaCmd) {
      enriched.prusaslicer_cmd = prusaCmd;
    }
    if (prusaOverrides) {
      enriched.prusaslicer_overrides = prusaOverrides;
    }
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
      debug: enriched,
    };
  }

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
    debug,
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
    const reportedId = safeString(value.reported_id);
    const expectedId = safeString(value.expected_id);
    const matchesFlag = value.reported_matches_expected;
    const matchesExpected = matchesFlag == null
      ? null
      : matchesFlag === true || (typeof matchesFlag === 'string' && matchesFlag.trim().toLowerCase() === 'true');
    normalized[kind] = {
      requested: safeString(value.requested ?? value.selected ?? value.desired),
      path,
      filename,
      found,
      is_default: isDefault,
      reported_id: reportedId || null,
      expected_id: expectedId || null,
      matches_expected: matchesExpected,
    };
  }
  return Object.keys(normalized).length ? normalized : null;
}

function renderPresetUsage(presetsUsed) {
  if (!presetsUsed || typeof presetsUsed !== 'object') {
    return '';
  }

  const labels = {
    print: 'Stampa',
    filament: 'Filamento',
    printer: 'Stampante',
  };

  let html = '<div style="margin-top:4px;"><b>Preset Prusa:</b>';
  const kinds = ['print', 'filament', 'printer'];
  for (const kind of kinds) {
    const entry = presetsUsed[kind];
    if (!entry) continue;

    const label = labels[kind] || kind;
    const requested = entry.requested || 'n/d';
    const used = entry.filename || entry.path || 'n/d';
    const defaultNote = entry.is_default ? ' (default)' : '';

    html += `<br><small>${escapeHtml(label)}: richiesto <b>${escapeHtml(requested)}</b> → ` +
      `usato <b>${escapeHtml(used)}</b>${defaultNote}</small>`;

    if (entry.reported_id || entry.expected_id) {
      const idParts = [];
      if (entry.reported_id) {
        idParts.push(`ID G-code: <b>${escapeHtml(entry.reported_id)}</b>`);
      }
      if (entry.expected_id) {
        idParts.push(`atteso <b>${escapeHtml(entry.expected_id)}</b>`);
      }
      if (idParts.length) {
        const mismatch = entry.matches_expected === false ? ' ⚠️' : '';
        html += `<br><small>${idParts.join(' — ')}${mismatch}</small>`;
      }
    }
  }

  html += '</div>';
  return html;
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

function normalizeEstimateDebug(raw) {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const debug = {};
  const cura = normalizeCuraDebug(raw.cura);
  if (cura) {
    debug.cura = cura;
  }
  const motion = normalizeMotionDebug(raw.motion);
  if (motion) {
    debug.motion = motion;
  }
  return Object.keys(debug).length ? debug : null;
}

function normalizePrusaslicerCmd(raw) {
  if (!raw) {
    return null;
  }
  if (Array.isArray(raw)) {
    const parts = raw.map((value) => safeString(value)).filter(Boolean);
    return parts.length ? parts : null;
  }
  const text = safeString(raw);
  if (!text) {
    return null;
  }
  const tokens = text.split(/\s+/).map((token) => token.trim()).filter(Boolean);
  return tokens.length ? tokens : null;
}

function normalizePrusaOverrides(raw) {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const overrides = Object.entries(raw)
    .map(([key, value]) => ({ key: safeString(key), value: toNumber(value) }))
    .filter((entry) => entry.key && entry.value != null);
  return overrides.length ? overrides : null;
}

function normalizeCuraDebug(raw) {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const result = {};
  const args = Array.isArray(raw.args)
    ? raw.args.map((value) => safeString(value)).filter(Boolean)
    : [];
  if (args.length) {
    result.args = args;
  }
  const profile = normalizeCuraProfile(raw.profile);
  if (profile) {
    result.profile = profile;
  }
  const definitions = normalizeCuraDefinitions(raw.definitions);
  if (definitions) {
    result.definitions = definitions;
  }
  const stdout = normalizeDebugLines(raw.stdout_tail ?? raw.stdout);
  if (stdout.length) {
    result.stdout = stdout;
  }
  const stderr = normalizeDebugLines(raw.stderr_tail ?? raw.stderr);
  if (stderr.length) {
    result.stderr = stderr;
  }
  const modelPath = safeString(raw.model_to_slice ?? raw.model);
  if (modelPath) {
    result.model = modelPath;
  }
  const outputPath = safeString(raw.output_gcode ?? raw.output);
  if (outputPath) {
    result.output = outputPath;
  }
  const returnCode = toNumber(raw.returncode);
  if (returnCode != null) {
    result.returncode = returnCode;
  }
  return Object.keys(result).length ? result : null;
}

function normalizeCuraProfile(raw) {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const profile = {};
  const machine = safeString(raw.machine);
  if (machine) {
    profile.machine = machine;
  }
  const layer = toNumber(raw.layer_height ?? raw.layer_h ?? raw.layerHeight);
  if (layer != null) {
    profile.layer_height = layer;
  }
  const infill = toNumber(raw.infill);
  if (infill != null) {
    profile.infill = infill;
  }
  const nozzle = toNumber(raw.nozzle ?? raw.machine_nozzle_size);
  if (nozzle != null) {
    profile.nozzle = nozzle;
  }
  const printSpeed = toNumber(raw.print_speed ?? raw.speed_print);
  if (printSpeed != null) {
    profile.print_speed = printSpeed;
  }
  const travelSpeed = toNumber(raw.travel_speed ?? raw.speed_travel);
  if (travelSpeed != null) {
    profile.travel_speed = travelSpeed;
  }
  const filamentDiameter = toNumber(raw.filament_diameter ?? raw.material_diameter);
  if (filamentDiameter != null) {
    profile.filament_diameter = filamentDiameter;
  }
  return Object.keys(profile).length ? profile : null;
}

function normalizeCuraDefinitions(raw) {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const definitions = {};
  const printer = safeString(raw.printer);
  if (printer) {
    definitions.printer = printer;
  }
  const extruder = safeString(raw.extruder);
  if (extruder) {
    definitions.extruder = extruder;
  }
  return Object.keys(definitions).length ? definitions : null;
}

function normalizeDebugLines(value) {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value.map((item) => safeString(item)).filter(Boolean);
  }
  return String(value)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function normalizeMotionDebug(raw) {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const motion = {};
  if (raw.error) {
    motion.error = safeString(raw.error);
  }
  const timeEstimate = toNumber(raw.time_s_estimate);
  if (timeEstimate != null) {
    motion.time_s_estimate = timeEstimate;
  }
  const timeBase = toNumber(raw.time_s_without_fudge);
  if (timeBase != null) {
    motion.time_s_without_fudge = timeBase;
  }
  const fudge = toNumber(raw.fudge_factor);
  if (fudge != null) {
    motion.fudge_factor = fudge;
  }
  const printAxis = normalizeMotionAxis(raw.print);
  if (printAxis) {
    motion.print = printAxis;
  }
  const travelAxis = normalizeMotionAxis(raw.travel);
  if (travelAxis) {
    motion.travel = travelAxis;
  }
  return Object.keys(motion).length ? motion : null;
}

function normalizeMotionAxis(raw) {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const axis = {};
  const distance = toNumber(raw.distance_mm);
  if (distance != null) {
    axis.distance_mm = distance;
  }
  const moves = toNumber(raw.moves);
  if (moves != null) {
    axis.moves = Math.round(moves);
  }
  const timeRaw = toNumber(raw.time_s_raw);
  if (timeRaw != null) {
    axis.time_s_raw = timeRaw;
  }
  const timeEffective = toNumber(raw.time_s_effective);
  if (timeEffective != null) {
    axis.time_s_effective = timeEffective;
  }
  if (raw.used_fallback === true) {
    axis.used_fallback = true;
  }
  const fallbackFeed = toNumber(raw.fallback_feed_mm_s);
  if (fallbackFeed != null) {
    axis.fallback_feed_mm_s = fallbackFeed;
  }
  const effectiveFeed = toNumber(raw.effective_feed_mm_s);
  if (effectiveFeed != null) {
    axis.effective_feed_mm_s = effectiveFeed;
  }
  const gcodeFeed = normalizeMotionFeed(raw.gcode_feed);
  if (gcodeFeed) {
    axis.gcode_feed = gcodeFeed;
  }
  return Object.keys(axis).length ? axis : null;
}

function normalizeMotionFeed(raw) {
  if (!raw || typeof raw !== 'object') {
    return null;
  }
  const feed = {};
  const count = toNumber(raw.count);
  if (count != null) {
    feed.count = Math.round(count);
  }
  const avg = toNumber(raw.avg);
  if (avg != null) {
    feed.avg = avg;
  }
  const min = toNumber(raw.min);
  if (min != null) {
    feed.min = min;
  }
  const max = toNumber(raw.max);
  if (max != null) {
    feed.max = max;
  }
  const samples = Array.isArray(raw.samples)
    ? raw.samples.map((value) => toNumber(value)).filter((value) => value != null)
    : [];
  if (samples.length) {
    feed.samples = samples;
  }
  return Object.keys(feed).length ? feed : null;
}

function renderEstimateDebug(debug) {
  if (!debug || typeof debug !== 'object') {
    return '';
  }
  const sections = [];
  const prusaSection = renderPrusaDebug(debug.prusaslicer_cmd, debug.prusaslicer_overrides);
  if (prusaSection) {
    sections.push(prusaSection);
  }
  const motionSection = renderMotionDebug(debug.motion);
  if (motionSection) {
    sections.push(motionSection);
  }
  const curaSection = renderCuraDebug(debug.cura);
  if (curaSection) {
    sections.push(curaSection);
  }
  if (!sections.length) {
    return '';
  }
  const body = sections.join('<hr class="estimate-debug-sep">');
  return `<details class="estimate-debug"><summary>Debug slicing</summary>${body}</details>`;
}

function renderPrusaDebug(cmd, overrides) {
  const hasCmd = Array.isArray(cmd) && cmd.length;
  const hasOverrides = Array.isArray(overrides) && overrides.length;
  if (!hasCmd && !hasOverrides) {
    return '';
  }
  const parts = [];
  if (hasCmd) {
    const rendered = escapeHtml(cmd.join(' '));
    parts.push(`<div>Comando PrusaSlicer: <code>${rendered}</code></div>`);
  }
  if (hasOverrides) {
    const renderedOverrides = overrides
      .map((entry) => `${escapeHtml(entry.key)}=${escapeHtml(formatNumber(entry.value, 3))}`)
      .join(', ');
    parts.push(`<div>Override applicati: <code>${renderedOverrides}</code></div>`);
  }
  return `<div class="estimate-debug-block">${parts.join('<br>')}</div>`;
}

function renderMotionDebug(motion) {
  if (!motion || typeof motion !== 'object') {
    return '';
  }
  const parts = [];
  if (motion.error) {
    parts.push(`<span style="color:#ff6b6b;font-weight:bold;">Analisi G-code fallita: ${escapeHtml(motion.error)}</span>`);
  }
  if (motion.time_s_estimate != null) {
    const minutes = formatMinutes(motion.time_s_estimate);
    const seconds = formatNumber(motion.time_s_estimate, 0);
    const fudge = motion.fudge_factor != null ? formatNumber(motion.fudge_factor, 2) : null;
    const label = minutes != null ? `${minutes} min` : (seconds != null ? `${seconds} s` : 'n/d');
    const suffix = fudge ? ` (fattore ${fudge})` : '';
    parts.push(`Stima G-code: <b>${label}</b>${suffix}`);
  }
  const printLine = renderMotionAxis('Estrusione', motion.print);
  if (printLine) {
    parts.push(printLine);
  }
  const travelLine = renderMotionAxis('Travel', motion.travel);
  if (travelLine) {
    parts.push(travelLine);
  }
  if (!parts.length) {
    return '';
  }
  return `<div class="estimate-debug-block">${parts.join('<br>')}</div>`;
}

function renderMotionAxis(label, axis) {
  if (!axis || typeof axis !== 'object') {
    return '';
  }
  const bits = [];
  if (axis.distance_mm != null) {
    bits.push(`distanza ${formatNumber(axis.distance_mm, 1)} mm`);
  }
  if (axis.moves != null) {
    bits.push(`${axis.moves} mosse`);
  }
  if (axis.effective_feed_mm_s != null) {
    bits.push(`feed effettivo ${formatNumber(axis.effective_feed_mm_s, 1)} mm/s`);
  }
  const gcodeFeed = axis.gcode_feed;
  if (gcodeFeed && typeof gcodeFeed === 'object' && Array.isArray(gcodeFeed.samples) && gcodeFeed.samples.length) {
    bits.push(`feed G-code: ${formatFeedSamples(gcodeFeed.samples)}`);
  }
  if (axis.used_fallback && (!gcodeFeed || !gcodeFeed.samples || !gcodeFeed.samples.length)) {
    const fallback = axis.fallback_feed_mm_s != null ? `${formatNumber(axis.fallback_feed_mm_s, 1)} mm/s` : 'preset';
    bits.push(`velocità da preset (${fallback})`);
  }
  return bits.length ? `${label}: ${bits.join(' — ')}` : '';
}

function formatFeedSamples(values) {
  return values
    .map((value) => {
      const formatted = formatNumber(value, value >= 100 ? 0 : 1);
      return formatted != null ? `${formatted} mm/s` : null;
    })
    .filter(Boolean)
    .join(', ');
}

function renderCuraDebug(cura) {
  if (!cura || typeof cura !== 'object') {
    return '';
  }
  const parts = [];
  if (cura.profile) {
    const profile = [];
    if (cura.profile.machine) {
      profile.push(`macchina ${escapeHtml(cura.profile.machine)}`);
    }
    if (cura.profile.layer_height != null) {
      profile.push(`layer ${formatNumber(cura.profile.layer_height, 2)} mm`);
    }
    if (cura.profile.print_speed != null) {
      profile.push(`print ${formatNumber(cura.profile.print_speed, 0)} mm/s`);
    }
    if (cura.profile.travel_speed != null) {
      profile.push(`travel ${formatNumber(cura.profile.travel_speed, 0)} mm/s`);
    }
    if (cura.profile.infill != null) {
      profile.push(`infill ${formatNumber(cura.profile.infill, 0)}%`);
    }
    if (profile.length) {
      parts.push(`Preset inviato: ${profile.join(' — ')}`);
    }
  }
  if (cura.definitions) {
    const defs = [];
    if (cura.definitions.printer) {
      defs.push(`printer: ${escapeHtml(cura.definitions.printer)}`);
    }
    if (cura.definitions.extruder) {
      defs.push(`extruder: ${escapeHtml(cura.definitions.extruder)}`);
    }
    if (defs.length) {
      parts.push(defs.join(' — '));
    }
  }
  if (cura.args && cura.args.length) {
    parts.push(`<div>Comando: <code>${escapeHtml(cura.args.join(' '))}</code></div>`);
  }
  if (cura.model) {
    parts.push(`Modello: <code>${escapeHtml(cura.model)}</code>`);
  }
  if (cura.output) {
    parts.push(`G-code: <code>${escapeHtml(cura.output)}</code>`);
  }
  if (cura.returncode != null) {
    parts.push(`Return code: ${cura.returncode}`);
  }
  const logs = [];
  if (cura.stdout && cura.stdout.length) {
    logs.push(`<details><summary>stdout</summary><pre>${escapeHtml(cura.stdout.join('\n'))}</pre></details>`);
  }
  if (cura.stderr && cura.stderr.length) {
    logs.push(`<details><summary>stderr</summary><pre>${escapeHtml(cura.stderr.join('\n'))}</pre></details>`);
  }
  const content = parts.concat(logs);
  return content.length ? `<div class="estimate-debug-block">${content.join('<br>')}</div>` : '';
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
document.addEventListener('preset:changed', (event) => {
  const reason = event && event.detail && event.detail.reason ? event.detail.reason : null;
  if (reason === 'init') {
    return;
  }
  if (!state.currentViewerUrl || !state.selectedKey) {
    return;
  }
  if (!estimateButton || estimateButton.disabled || isEstimating) {
    return;
  }
  handleEstimate({ silent: true, reason: reason || 'preset-change' });
});
