export const PRINTING_PROFILES = {
  quality_high: {
    label: "Alta Qualità",
    set: {
      layer_height_mm: 0.12,
      perimeters: 3,
      top_solid_layers: 6,
      bottom_solid_layers: 6,
      infill_density_percent: 15,
      infill_pattern: "gyroid",
      top_bottom_pattern: "monotonic",
      sparse_infill_layer_height_mm: 0.24,
      spiral_vase: false,
      ironing: "off",
      fuzzy_skin: "off",
      seam_position: "back"
    }
  },
  quality_std: {
    label: "Standard",
    set: {
      layer_height_mm: 0.20,
      perimeters: 3,
      top_solid_layers: 5,
      bottom_solid_layers: 5,
      infill_density_percent: 15,
      infill_pattern: "grid",
      top_bottom_pattern: "monotonic",
      sparse_infill_layer_height_mm: 0.40,
      spiral_vase: false,
      ironing: "off",
      fuzzy_skin: "off",
      seam_position: "back"
    }
  },
  draft: {
    label: "Bozza / Velocità",
    set: {
      layer_height_mm: 0.28,
      perimeters: 2,
      top_solid_layers: 4,
      bottom_solid_layers: 4,
      infill_density_percent: 10,
      infill_pattern: "lines",
      top_bottom_pattern: "rectilinear",
      sparse_infill_layer_height_mm: 0.56,
      spiral_vase: false,
      ironing: "off",
      fuzzy_skin: "off",
      seam_position: "random"
    }
  },
  strength: {
    label: "Resistente (Strength)",
    set: {
      layer_height_mm: 0.16,
      perimeters: 4,
      top_solid_layers: 7,
      bottom_solid_layers: 7,
      infill_density_percent: 30,
      infill_pattern: "cubic",
      top_bottom_pattern: "monotonic",
      sparse_infill_layer_height_mm: 0.32,
      spiral_vase: false,
      ironing: "off",
      fuzzy_skin: "off",
      seam_position: "aligned"
    }
  },
  vase: {
    label: "Vaso (Spiral Vase)",
    set: {
      layer_height_mm: 0.20,
      perimeters: 1,
      top_solid_layers: 0,
      bottom_solid_layers: 1,
      infill_density_percent: 0,
      infill_pattern: "none",
      top_bottom_pattern: "concentric",
      sparse_infill_layer_height_mm: 0.40,
      spiral_vase: true,
      ironing: "off",
      fuzzy_skin: "off",
      seam_position: "aligned"
    },
    uiLocks: ["infill", "top_bottom_layers", "perimeters"]
  },
  ironing: {
    label: "Superficie liscia (Ironing)",
    set: {
      layer_height_mm: 0.20,
      perimeters: 3,
      top_solid_layers: 6,
      bottom_solid_layers: 5,
      infill_density_percent: 15,
      infill_pattern: "grid",
      top_bottom_pattern: "monotonic",
      sparse_infill_layer_height_mm: 0.40,
      spiral_vase: false,
      ironing: "topmost",
      fuzzy_skin: "off",
      seam_position: "back"
    }
  },
  fuzzy: {
    label: "Superficie ruvida (Fuzzy skin)",
    set: {
      layer_height_mm: 0.20,
      perimeters: 3,
      top_solid_layers: 5,
      bottom_solid_layers: 5,
      infill_density_percent: 15,
      infill_pattern: "grid",
      top_bottom_pattern: "rectilinear",
      sparse_infill_layer_height_mm: 0.40,
      spiral_vase: false,
      ironing: "off",
      fuzzy_skin: "on",
      seam_position: "back"
    }
  },
  seam: {
    label: "Gestione cucitura (Seam)",
    set: {
      layer_height_mm: 0.20,
      perimeters: 3,
      top_solid_layers: 5,
      bottom_solid_layers: 5,
      infill_density_percent: 15,
      infill_pattern: "gyroid",
      top_bottom_pattern: "monotonic",
      sparse_infill_layer_height_mm: 0.40,
      spiral_vase: false,
      ironing: "off",
      fuzzy_skin: "off",
      seam_position: "aligned"
    },
    tools: ["paint_seam", "vertical_seam"]
  }
};
