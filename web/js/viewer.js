import {
  AmbientLight,
  Box3,
  Color,
  DirectionalLight,
  Mesh,
  MeshStandardMaterial,
  PerspectiveCamera,
  Scene,
  Vector3,
  WebGLRenderer,
} from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { OBJLoader } from 'three/addons/loaders/OBJLoader.js';
import { ThreeMFLoader } from 'three/addons/loaders/3MFLoader.js';

import { state, setCurrentViewer, resetViewerState } from './state.js';
import { hexNorm } from './utils/colors.js';

let activeRenderer = null;
let activeControls = null;
let activeScene = null;
let animationId = null;

const DEFAULT_VIEWER_MESSAGE = 'Trascina qui un file o caricalo dal pulsante sotto.';
const fileNameElement = document.getElementById('fileName');

export function resetViewer() {
  cleanupViewer();
  const container = document.getElementById('viewer');
  if (container) {
    container.innerHTML = DEFAULT_VIEWER_MESSAGE;
    container.classList.remove('drag');
  }
  resetViewerState();
  updateFileNameDisplay(null);
}

export function rerenderCurrentModel() {
  if (state.currentViewerUrl) {
    showViewer(state.currentViewerUrl, state.lastModelName);
  }
}

export async function showViewer(path, name) {
  const displayName = name || inferNameFromPath(path);
  setCurrentViewer(path, displayName || null);
  updateFileNameDisplay(displayName);
  const container = document.getElementById('viewer');
  if (!container) return;

  cleanupViewer();
  container.innerHTML = '';
  container.classList.remove('drag');

  const ext = extractExtension(path);
  const loader = createLoader(ext);
  if (!loader) {
    container.innerHTML = `<a href="${encodeURI(path)}" target="_blank" style="color:var(--accent)">${encodeURI(path)}</a>`;
    return;
  }

  const width = container.clientWidth || container.offsetWidth || 600;
  const height = container.clientHeight || 460;

  const scene = new Scene();
  const background = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#0f172a';
  scene.background = new Color(background);
  const camera = new PerspectiveCamera(45, width / height, 0.1, 1000);
  const renderer = new WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  renderer.setSize(width, height);
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.1;

  const ambient = new AmbientLight(0xffffff, 0.6);
  const directional = new DirectionalLight(0xffffff, 0.8);
  directional.position.set(3, 10, 5);
  scene.add(ambient);
  scene.add(directional);

  activeRenderer = renderer;
  activeControls = controls;
  activeScene = scene;

  try {
    const rawObject = await loadModel(loader, path, ext);
    const materialInfo = getSelectedMaterial();
    const preparedObject = applyMaterial(rawObject, materialInfo.color, materialInfo.transparent);
    scene.add(preparedObject);
    fitCameraToObject(camera, controls, preparedObject);
    startAnimation(renderer, scene, camera, controls);
  } catch (error) {
    console.error('Errore caricamento modello', error);
    await handleLoadError({ container, path, ext, renderer, scene, controls, camera });
  }

  const out = document.getElementById('out');
  if (out) out.innerHTML = '';
}

function inferNameFromPath(path) {
  if (!path) return null;
  const segments = path.split('/').filter(Boolean);
  if (!segments.length) return null;
  const last = segments[segments.length - 1].split('?')[0];
  try {
    return decodeURIComponent(last);
  } catch (error) {
    return last;
  }
}

function updateFileNameDisplay(name) {
  if (!fileNameElement) return;
  const trimmed = (name || '').trim();
  if (trimmed) {
    fileNameElement.textContent = trimmed;
    fileNameElement.title = trimmed;
  } else {
    fileNameElement.textContent = 'Nessun file selezionato.';
    fileNameElement.removeAttribute('title');
  }
}

function getSelectedMaterial() {
  const selection = state.inventoryItems.find((item) => item.key === state.selectedKey) || {};
  const hex = hexNorm(selection.color || '#AAAAAA');
  return {
    color: hex,
    transparent: Boolean(selection.is_transparent),
  };
}

function extractExtension(path) {
  const parts = path.split('.');
  if (parts.length < 2) return '';
  return parts.pop().toLowerCase().split('?')[0];
}

function createLoader(ext) {
  switch (ext) {
    case 'stl':
      return new STLLoader();
    case 'obj':
      return new OBJLoader();
    case '3mf':
      return new ThreeMFLoader();
    default:
      return null;
  }
}

function loadModel(loader, path, ext) {
  const safePath = encodeURI(path);
  return new Promise((resolve, reject) => {
    loader.load(
      safePath,
      (result) => resolve(result),
      undefined,
      (err) => reject(err)
    );
  });
}

async function handleLoadError({ container, path, ext, renderer, scene, controls, camera }) {
  if (ext === '3mf') {
    try {
      const fallbackGeometry = await loadStlFallback(path);
      if (fallbackGeometry && scene && controls && renderer && camera instanceof PerspectiveCamera) {
        const materialInfo = getSelectedMaterial();
        const preparedObject = applyMaterial(fallbackGeometry, materialInfo.color, materialInfo.transparent);
        scene.add(preparedObject);
        fitCameraToObject(camera, controls, preparedObject);
        startAnimation(renderer, scene, camera, controls);
        return;
      }
    } catch (fallbackErr) {
      console.error('Fallback STL fallito', fallbackErr);
    }
  }
  cleanupViewer();
  const link = encodeURI(path);
  container.innerHTML = `<a href="${link}" target="_blank" style="color:var(--accent)">${link}</a>`;
  resetViewerState();
}

async function loadStlFallback(path) {
  const stlPath = path.replace(/\.3mf(\?.*)?$/i, '.stl$1');
  const bust = stlPath.includes('?') ? '&' : '?';
  const finalPath = `${stlPath}${bust}nocache=${Date.now()}`;
  const response = await fetch(finalPath);
  if (!response.ok) {
    throw new Error(`STL non trovato: ${response.status}`);
  }
  const buffer = await response.arrayBuffer();
  if (buffer.byteLength < 84) {
    throw new Error(`STL non valido o troppo corto (${buffer.byteLength} B)`);
  }
  const loader = new STLLoader();
  const geometry = loader.parse(buffer);
  return geometry;
}

function applyMaterial(object, hex, transparent) {
  const color = new Color(hex);
  if (object && (object.isBufferGeometry || object.isGeometry)) {
    return createMeshFromGeometry(object, color, transparent);
  }
  if (object && object.isMesh) {
    tintMesh(object, color, transparent);
    return object;
  }
  if (object && object.traverse) {
    object.traverse((child) => {
      if (child.isMesh) {
        tintMesh(child, color, transparent);
      }
    });
  }
  return object;
}

function tintMesh(mesh, color, transparent) {
  const applyToMaterial = (material) => {
    if (!material) return;
    const cloned = material.clone ? material.clone() : material;
    cloned.color = color.clone();
    cloned.transparent = transparent;
    cloned.opacity = transparent ? 0.6 : 1;
    return cloned;
  };

  if (Array.isArray(mesh.material)) {
    mesh.material = mesh.material.map((mat) => applyToMaterial(mat));
  } else {
    mesh.material = applyToMaterial(mesh.material);
  }
}

function createMeshFromGeometry(geometry, color, transparent) {
  const material = new MeshStandardMaterial({
    color,
    transparent,
    opacity: transparent ? 0.6 : 1,
    metalness: 0.1,
    roughness: 0.8,
  });
  return new Mesh(geometry, material);
}

function fitCameraToObject(camera, controls, object) {
  const box = new Box3().setFromObject(object);
  const size = box.getSize(new Vector3());
  const center = box.getCenter(new Vector3());
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  const fov = camera.fov * (Math.PI / 180);
  const cameraZ = Math.abs(maxDim / (2 * Math.tan(fov / 2)));
  camera.position.set(center.x, center.y, center.z + cameraZ * 1.5);
  camera.near = Math.max(0.001, maxDim / 100);
  camera.far = Math.max(10, maxDim * 100);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}

function startAnimation(renderer, scene, camera, controls) {
  const loop = () => {
    controls.update();
    renderer.render(scene, camera);
    animationId = window.requestAnimationFrame(loop);
  };
  loop();
}

function cleanupViewer() {
  if (animationId) {
    window.cancelAnimationFrame(animationId);
    animationId = null;
  }
  if (activeControls) {
    activeControls.dispose();
    activeControls = null;
  }
  if (activeScene) {
    activeScene.traverse((child) => {
      if (child.isMesh) {
        if (child.geometry && child.geometry.dispose) {
          child.geometry.dispose();
        }
        disposeMaterial(child.material);
      }
    });
    activeScene = null;
  }
  if (activeRenderer) {
    activeRenderer.dispose();
    const canvas = activeRenderer.domElement;
    if (canvas && canvas.parentNode) {
      canvas.parentNode.removeChild(canvas);
    }
    activeRenderer = null;
  }
}

function disposeMaterial(material) {
  if (!material) return;
  if (Array.isArray(material)) {
    material.forEach(disposeMaterial);
    return;
  }
  if (material.dispose) {
    material.dispose();
  }
}
