// Colors for the 3D view. Road paint is only white or yellow, following SHC 602 section 4.1.3.
export const PALETTE = {
  sky: '#cfd6dc',
  ground: [214, 209, 198],
  asphalt: [58, 63, 71],
  junction: [70, 75, 83],
  underground: [52, 56, 62],
  rampFloor: [146, 144, 138],
  concrete: [206, 202, 194],
  roof: [138, 138, 135],
  signal: {
    housing: [22, 24, 27],
    plate: [14, 15, 17],
    border: [246, 196, 30],
    pole: [150, 155, 160],
    lit: { r: [255, 45, 45], y: [255, 176, 0], g: [30, 225, 95], o: [90, 90, 90] },
    dim: { r: [64, 22, 22], y: [66, 48, 10], g: [12, 58, 30], o: [40, 40, 40] },
  },
  building: { wall: [236, 232, 225], flat: [226, 222, 214], roofLine: [168, 163, 154] },
  context: {
    street: [64, 65, 68],
    aisle: [104, 106, 110],
    path: [214, 206, 192],
    casing: [204, 201, 194],
    parking: [224, 221, 214],
    pitch: [146, 164, 120],
    green: [166, 174, 140],
    water: [178, 210, 234],
    campus: [221, 215, 203],
    landuse: [219, 214, 204],
  },
  street3d: { kerb: [222, 220, 214], sidewalk: [210, 206, 198], median: [196, 194, 188] },
  // Common Riyadh facade colors: limestone, off-white, beige and grey stone.
  // modern Riyadh facades: white and light grey render, warm stone, aluminium grey and a few
  // dark charcoal cladding panels
  facades: [
    [238, 238, 234],
    [226, 228, 226],
    [214, 206, 192],
    [232, 222, 204],
    [188, 192, 194],
    [205, 198, 186],
    [112, 118, 126],
    [244, 242, 236],
    [196, 186, 170],
    [150, 156, 162],
  ],
  hover: [86, 132, 196],
  paint: { white: [244, 244, 240], yellow: [242, 194, 48] },
}

// Day and night lighting. `n` goes from 0 (day) to 1 (night) and App animates it when the toggle changes.
// Lamps should look the same brightness in both modes, so their material is scaled by the current ambient light.
export const ENV = { n: 0, ambient: 1.75 }
const lerp = (a, b, t) => a + (b - a) * t
export const envLighting = (n) => ({
  ambient: lerp(1.75, 0.62, n),
  ambientColor: [lerp(255, 168, n), lerp(255, 182, n), lerp(255, 222, n)].map(Math.round), // bluish at night
  sun: lerp(0.75, 0.12, n), // direct light, very weak at night
})
// Material for lamps, so they keep their full color in day and night.
export const glowMaterial = (gain = 1) => ({
  ambient: Math.min(4, gain / ENV.ambient),
  diffuse: 0,
  shininess: 1,
  specularColor: [0, 0, 0],
})
