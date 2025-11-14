import { state, setSelectedMachine } from './state.js';

const DEFAULT_PRESET_KEY = 'x1c_standard_020';
const PRESETS = {
  '': {
    machine: 'generic',
    profile: 'print.ini',
    printer_profile: 'printer.ini',
    layer_h: 0.2,
    infill: 15,
    nozzle: 0.4,
    print_speed: 60,
    travel_speed: 150,
  },
  x1c_standard_020: {
    machine: 'bambu_x1c',
    profile: 'x1c_standard_020.ini',
    printer_profile: 'printer.ini',
    layer_h: 0.2,
    infill: 15,
    nozzle: 0.4,
    print_speed: 200,
    travel_speed: 500,
  },
  x1c_quality_016: {
    machine: 'bambu_x1c',
    profile: 'x1c_quality_016.ini',
    printer_profile: 'printer.ini',
    layer_h: 0.16,
    infill: 15,
    nozzle: 0.4,
    print_speed: 200,
    travel_speed: 500,
  },
  x1c_fine_012: {
    machine: 'bambu_x1c',
    profile: 'x1c_fine_012.ini',
    printer_profile: 'printer.ini',
    layer_h: 0.12,
    infill: 20,
    nozzle: 0.4,
    print_speed: 160,
    travel_speed: 500,
  },
  x1c_draft_028: {
    machine: 'bambu_x1c',
    profile: 'x1c_draft_028.ini',
    printer_profile: 'printer.ini',
    layer_h: 0.28,
    infill: 15,
    nozzle: 0.4,
    print_speed: 250,
    travel_speed: 500,
  },
  x1c_strength_020: {
    machine: 'bambu_x1c',
    profile: 'x1c_strength_020.ini',
    printer_profile: 'printer.ini',
    layer_h: 0.2,
    infill: 50,
    nozzle: 0.4,
    print_speed: 180,
    travel_speed: 500,
  },
  x1c_lightning_020: {
    machine: 'bambu_x1c',
    profile: 'x1c_lightning_020.ini',
    printer_profile: 'printer.ini',
    layer_h: 0.2,
    infill: 10,
    nozzle: 0.4,
    print_speed: 300,
    travel_speed: 500,
  },
  x1c_ultrafine_008: {
    machine: 'bambu_x1c',
    profile: 'x1c_ultrafine_008.ini',
    printer_profile: 'printer.ini',
    layer_h: 0.08,
    infill: 20,
    nozzle: 0.4,
    print_speed: 160,
    travel_speed: 500,
  },
};

function normalizePresetKey(key) {
  if (!key) return '';
  const text = String(key).trim();
  if (!text) return '';
  const lower = text.toLowerCase();
  if (lower.endsWith('.ini')) {
    return lower.slice(0, -4);
  }
  return lower;
}

export function getPresetDefinition(key) {
  const normalized = normalizePresetKey(key);
  return PRESETS[normalized] || null;
}

export function getPresetProfileName(key) {
  const preset = getPresetDefinition(key);
  if (preset && preset.profile) {
    return preset.profile;
  }
  const normalized = normalizePresetKey(key);
  if (!normalized) return null;
  return `${normalized}.ini`;
}

export function getPresetPrinterProfile(key) {
  const preset = getPresetDefinition(key);
  if (preset && preset.printer_profile) {
    return preset.printer_profile;
  }
  return 'printer.ini';
}

export function initPresets(selectId) {
  const select = document.getElementById(selectId);
  if (!select) return;
  select.addEventListener('change', () => applyPreset(select.value));
  if (!state.selectedMachine || state.selectedMachine === 'generic') {
    select.value = DEFAULT_PRESET_KEY;
    applyPreset(DEFAULT_PRESET_KEY);
  }
}

export function applyPreset(key) {
  const preset = getPresetDefinition(key) || PRESETS[''];
  setSelectedMachine(preset.machine);
  setValue('layer_h', preset.layer_h != null ? preset.layer_h.toFixed(2) : undefined);
  setValue('infill', preset.infill != null ? String(preset.infill) : undefined);
  setValue('nozzle', preset.nozzle != null ? preset.nozzle.toFixed(1) : undefined);
  setValue('print_speed', preset.print_speed != null ? String(preset.print_speed) : undefined);
  setValue('travel_speed', preset.travel_speed != null ? String(preset.travel_speed) : undefined);
}

function setValue(id, value) {
  if (value == null) return;
  const el = document.getElementById(id);
  if (!el) return;

  const stringValue = String(value);

  if (el instanceof HTMLSelectElement) {
    const hasOption = Array.from(el.options).some((option) => option.value === stringValue);
    if (!hasOption) {
      const option = document.createElement('option');
      option.value = stringValue;
      option.textContent = formatOptionLabel(id, stringValue);
      el.appendChild(option);
    }
  }

  el.value = stringValue;
}

function formatOptionLabel(id, value) {
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return value;
  }

  switch (id) {
    case 'layer_h':
    case 'nozzle':
      return `${num.toFixed(2)} mm`;
    case 'infill':
      return `${num}%`;
    case 'print_speed':
    case 'travel_speed':
      return `${num} mm/s`;
    default:
      return value;
  }
}
