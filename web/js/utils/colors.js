const KNOWN_HEX_LABELS = {
  '#FFFFFF': 'Bianco',
  '#000000': 'Nero',
  '#020000': 'Nero',
  '#A6A9AA': 'Grigio',
  '#E4BD68': 'Oro',
  '#FF9016': 'Arancione',
  '#F4EE2A': 'Giallo',
  '#0A2989': 'Blu',
  '#5E43B7': 'Viola',
  '#00AE42': 'Verde',
  '#EC008C': 'Rosa',
  '#F5547C': 'Rosa',
  '#C12E1F': 'Rosso',
  '#9D432C': 'Marrone',
  '#F7E6DE': 'Bianco',
};

export function hexNorm(value) {
  if (!value) return '#777777';
  let str = String(value).trim();
  if (!str.startsWith('#')) str = `#${str}`;
  return str.toUpperCase();
}

function hexToRgb(hex) {
  const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '');
  if (!match) return { r: 119, g: 119, b: 119 };
  return {
    r: parseInt(match[1], 16),
    g: parseInt(match[2], 16),
    b: parseInt(match[3], 16),
  };
}

function rgbToHsv(r, g, b) {
  r /= 255;
  g /= 255;
  b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  let h = 0;
  if (delta !== 0) {
    switch (max) {
      case r:
        h = (g - b) / delta + (g < b ? 6 : 0);
        break;
      case g:
        h = (b - r) / delta + 2;
        break;
      case b:
        h = (r - g) / delta + 4;
        break;
      default:
        break;
    }
    h *= 60;
  }
  const s = max === 0 ? 0 : delta / max;
  const v = max;
  return { h, s, v };
}

export function nameFromHex(hex, isTransparent = false) {
  const normalized = hexNorm(hex);
  if (isTransparent) return 'Trasparente';
  if (KNOWN_HEX_LABELS[normalized]) return KNOWN_HEX_LABELS[normalized];
  const { r, g, b } = hexToRgb(normalized);
  const { h, s, v } = rgbToHsv(r, g, b);

  if (s < 0.1) {
    if (v > 0.9) return 'Bianco';
    if (v < 0.15) return 'Nero';
    return 'Grigio';
  }

  if (h >= 15 && h < 40 && v < 0.6) return 'Marrone';
  if (h >= 40 && h < 55 && s > 0.4 && v > 0.6) return 'Oro';
  if (h < 15 || h >= 345) return 'Rosso';
  if (h >= 15 && h < 40) return 'Arancione';
  if (h >= 55 && h < 75) return 'Giallo';
  if (h >= 75 && h < 160) return 'Verde';
  if (h >= 160 && h < 190) return 'Ciano';
  if (h >= 190 && h < 255) return 'Blu';
  if (h >= 255 && h < 295) return 'Viola';
  if (h >= 295 && h < 345) return 'Rosa';
  return 'N/D';
}

export function coherentName(hex, given, isTransparent = false) {
  const auto = nameFromHex(hex, isTransparent);
  if (!given) return auto;
  const synonyms = {
    fucsia: 'fucsia',
    magenta: 'magenta',
    azzurro: 'blu chiaro',
    gold: 'oro',
    transparent: 'trasparente',
    translucent: 'trasparente',
  };

  const candidate = String(given).trim().toLowerCase();
  const normalizedCandidate = synonyms[candidate] || candidate;
  if (normalizedCandidate === auto.toLowerCase()) {
    return given;
  }

  const normalizedHex = hexNorm(hex);
  if (candidate.includes('bianco') && normalizedHex !== '#FFFFFF') {
    return auto;
  }
  if (candidate.includes('trasp')) {
    return 'Trasparente';
  }
  return auto;
}
