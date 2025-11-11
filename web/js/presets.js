import { state, setSelectedMachine } from './state.js';

const PRESETS = {
  '': { machine: 'generic', layer_h: 0.2, infill: 15, nozzle: 0.4, print_speed: 60, travel_speed: 150 },
  x1c_standard_020: { machine: 'bambu_x1c', layer_h: 0.2, infill: 15, nozzle: 0.4, print_speed: 200, travel_speed: 500 },
  x1c_quality_016: { machine: 'bambu_x1c', layer_h: 0.16, infill: 15, nozzle: 0.4, print_speed: 200, travel_speed: 500 },
  x1c_fine_012: { machine: 'bambu_x1c', layer_h: 0.12, infill: 20, nozzle: 0.4, print_speed: 160, travel_speed: 500 },
  x1c_draft_028: { machine: 'bambu_x1c', layer_h: 0.28, infill: 15, nozzle: 0.4, print_speed: 250, travel_speed: 500 },
  x1c_strength_020: { machine: 'bambu_x1c', layer_h: 0.2, infill: 50, nozzle: 0.4, print_speed: 180, travel_speed: 500 },
  x1c_lightning_020: { machine: 'bambu_x1c', layer_h: 0.2, infill: 10, nozzle: 0.4, print_speed: 300, travel_speed: 500 },
  x1c_ultrafine_008: { machine: 'bambu_x1c', layer_h: 0.08, infill: 20, nozzle: 0.4, print_speed: 160, travel_speed: 500 },
};

export function initPresets(selectId) {
  const select = document.getElementById(selectId);
  if (!select) return;
  select.addEventListener('change', () => applyPreset(select.value));
  if (!state.selectedMachine || state.selectedMachine === 'generic') {
    select.value = 'x1c_standard_020';
    applyPreset('x1c_standard_020');
  }
}

export function applyPreset(key) {
  const preset = PRESETS[key] || PRESETS[''];
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
  if (el) el.value = value;
}
