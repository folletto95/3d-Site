export const state = {
  selectedKey: null,
  currentViewerUrl: null,
  selectedMachine: 'generic',
  inventoryItems: [],
  lastModelName: null,
};

export function setSelectedKey(key) {
  state.selectedKey = key;
}

export function setCurrentViewer(path, modelName = null) {
  state.currentViewerUrl = path;
  state.lastModelName = modelName;
}

export function resetViewerState() {
  state.currentViewerUrl = null;
  state.lastModelName = null;
}

export function setInventoryItems(items) {
  state.inventoryItems = items;
}

export function setSelectedMachine(machine) {
  state.selectedMachine = machine || 'generic';
}

export function getSelectedInventoryItem() {
  if (!state.selectedKey) return null;
  return state.inventoryItems.find((item) => item.key === state.selectedKey) || null;
}
