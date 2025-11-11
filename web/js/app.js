import { initPalette } from './palette.js';
import { initPresets } from './presets.js';
import { state } from './state.js';
import { resetViewer, showViewer } from './viewer.js';

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
    const response = await fetch('/upload_model', { method: 'POST', body: formData });
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
    const response = await fetch('/fetch_model', {
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
    const response = await fetch('/slice/estimate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await parseJson(response);
    if (!response.ok) {
      throw new Error(data.detail || 'Errore stima');
    }
    const minutes = Math.round(data.time_s / 60);
    if (outputElement) {
      outputElement.innerHTML = `
        Tempo: <b>${minutes} min</b> — Filamento: <b>${data.filament_g} g</b><br>
        Costo filamento: <b>${data.cost_filament} ${data.currency}</b> — Costo macchina: <b>${data.cost_machine} ${data.currency}</b><br>
        Totale: <b>${data.total} ${data.currency}</b> — <a href="${data.gcode_url}" target="_blank" style="color:var(--accent)">Scarica G-code</a>
      `;
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
