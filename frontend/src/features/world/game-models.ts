import * as THREE from 'three'
import tokens from '../../../../docs/contracts/design-tokens.json'
import rules from '../../../../docs/contracts/system-core-rules.target.json'
import {Sculpture, facade, planter, beam, groundModel} from './sculpture'
import {enemyCodes, enemyModel} from './enemy-models'
import type {Model} from './models'

const P = tokens.world.scene_palette
type V3 = [number, number, number]
export const unitPoses = ['idle', 'walk', 'attack', 'cast', 'hit', 'defeat', 'victory', 'rest'] as const
export type UnitPose = typeof unitPoses[number]

function books(s: Sculpture, at: V3, count = 4) {
  for (let i = 0; i < count; i++) s.box([0.034, 0.105 + i % 2 * 0.018, 0.09], [at[0] + i * 0.041, at[1], at[2]], [P.roof_forest, P.roof_plaza, P.path, P.roof_valley][i % 4], [0, 0, i === 0 ? 0.12 : 0])
}

function banner(s: Sculpture, at: V3, occupied: boolean, large = false) {
  const h = large ? 1.08 : 0.73, c = occupied ? P.flag : P.hostile_flag
  s.cylinder(0.018, 0.025, h, [at[0], at[1] + h / 2, at[2]], P.timber, 8)
  s.sphere(0.034, [at[0], at[1] + h, at[2]], P.flag)
  s.box([large ? 0.31 : 0.23, 0.22, 0.026], [at[0] + 0.12, at[1] + h - 0.16, at[2]], c, [0, 0.08, 0])
  s.add(new THREE.OctahedronGeometry(0.038), occupied ? P.wall : P.timber, [at[0] + 0.12, at[1] + h - 0.15, at[2] + 0.023], [0, 0, 0], [0.75, 1, 0.25])
}

function tiledRoof(s: Sculpture, at: V3, width: number, rise: number, depth: number, color: string) {
  s.gable(at, width, rise, depth, color)
  const half = width / 2, slope = Math.atan2(rise, half)
  for (const side of [-1, 1]) for (let row = 1; row < 6; row++) {
    const x = side * half * row / 6, y = rise * (1 - row / 6)
    s.box([0.022, 0.018, depth + 0.025], [at[0] + x, at[1] + y + 0.026, at[2]], row % 2 ? color : P.wall_shade, [0, 0, -side * slope])
  }
}

/** Three building levels: porch lodge → side studio → dormer and watch turret. */
export function campHall(level: number): Model {
  const s = new Sculpture(), high = level > 1, h = high ? 0.7 : 0.58
  facade(s, 0.78, h, 0.67, P.roof_forest, 2)
  tiledRoof(s, [0, h + 0.055, 0], 0.98, 0.42, 0.88, P.roof_forest)
  s.box([0.1, 0.35, 0.12], [-0.23, h + 0.24, -0.17], P.stone, [0, 0, 0], 0.015)
  s.box([0.15, 0.035, 0.17], [-0.23, h + 0.425, -0.17], P.wall_shade)
  for (let i = 0; i < 3; i++) s.box([0.33 + i * 0.09, 0.026, 0.09], [0, 0.055 - i * 0.012, 0.44 + i * 0.09], P.stone, [0, 0, 0], 0.01)
  // Log store, a side seat and a back service door stay visible when orbiting.
  for (let i = 0; i < 4; i++) s.cylinder(0.035, 0.035, 0.25, [-0.48, 0.065 + Math.floor(i / 2) * 0.06, -0.16 + i % 2 * 0.075], P.wood, 9, [0, 0, Math.PI / 2])
  s.box([0.28, 0.04, 0.16], [-0.5, 0.2, 0.2], P.wood, [0, 0, 0], 0.01)
  for (const x of [-0.6, -0.4]) s.box([0.035, 0.19, 0.13], [x, 0.095, 0.2], P.timber)
  s.box([0.15, 0.29, 0.025], [0.16, 0.2, -0.354], P.timber, [0, 0, 0], 0.016)
  for (const x of [-0.34, 0.34]) planter(s, x, 0.49)
  if (high) {
    s.box([0.34, 0.45, 0.44], [0.48, 0.24, -0.12], P.wall, [0, 0, 0], 0.028)
    tiledRoof(s, [0.48, 0.49, -0.12], 0.48, 0.21, 0.58, P.roof_forest)
    s.window([0.662, 0.3, -0.1], [0.18, 0.19, 0.02], [0, Math.PI / 2, 0])
    books(s, [0.39, 0.24, 0.114])
  }
  if (level > 2) {
    s.cylinder(0.16, 0.19, 0.95, [-0.33, 0.48, -0.24], P.wall_shade, 12)
    s.cylinder(0.015, 0.255, 0.42, [-0.33, 1.17, -0.24], P.roof_forest, 12)
    s.window([-0.33, 0.78, -0.435], [0.13, 0.19, 0.019], [0, Math.PI, 0])
    s.box([0.18, 0.21, 0.2], [0.12, h + 0.25, 0.2], P.wall)
    tiledRoof(s, [0.12, h + 0.36, 0.2], 0.27, 0.13, 0.29, P.roof_forest)
    s.window([0.12, h + 0.25, 0.316], [0.11, 0.13, 0.018])
    banner(s, [0.61, 0, 0.39], true)
  }
  return s.finish()
}

export function readingBench(): Model {
  const s = new Sculpture()
  for (let i = 0; i < 4; i++) s.box([0.67, 0.032, 0.064], [0, 0.22, -0.08 + i * 0.064], i % 2 ? P.wood : P.path, [0, 0, 0], 0.006)
  for (const x of [-0.25, 0.25]) {
    s.box([0.045, 0.43, 0.045], [x, 0.215, -0.13], P.timber)
    s.box([0.045, 0.23, 0.045], [x, 0.115, 0.13], P.timber)
    s.box([0.065, 0.036, 0.32], [x, 0.34, 0.01], P.timber, [0, 0, 0], 0.01)
  }
  for (let i = 0; i < 3; i++) s.box([0.7, 0.055, 0.025], [0, 0.29 + i * 0.063, -0.13], P.wood, [-0.1, 0, 0], 0.008)
  s.box([0.14, 0.025, 0.1], [0.06, 0.257, 0.03], P.roof_plaza, [0, -0.3, 0])
  s.box([0.13, 0.012, 0.09], [0.06, 0.275, 0.03], P.wall, [0, -0.3, 0])
  s.cylinder(0.025, 0.022, 0.057, [-0.16, 0.263, 0.04], P.wall, 10)
  return s.finish()
}

export function stoneWell(): Model {
  const s = new Sculpture()
  for (let layer = 0; layer < 3; layer++) for (let block = 0; block < 10; block++) {
    const a = (block + layer % 2 / 2) * Math.PI / 5
    s.box([0.17, 0.093, 0.105], [Math.sin(a) * 0.245, 0.05 + layer * 0.094, Math.cos(a) * 0.245], block % 3 ? P.stone : P.cliff, [0, a, 0], 0.017)
  }
  s.cylinder(0.195, 0.195, 0.02, [0, 0.055, 0], P.water, 16)
  for (const x of [-0.32, 0.32]) s.box([0.047, 0.69, 0.053], [x, 0.35, 0], P.timber)
  tiledRoof(s, [0, 0.72, 0], 0.82, 0.24, 0.59, P.roof_forest)
  s.cylinder(0.035, 0.035, 0.78, [0, 0.49, 0], P.wood, 10, [0, 0, Math.PI / 2])
  beam(s, [0.41, 0.49, 0], [0.41, 0.4, 0.09], 0.022, P.metal)
  beam(s, [0, 0.49, 0], [0, 0.19, 0], 0.005, P.path)
  s.cylinder(0.066, 0.044, 0.1, [0, 0.22, 0], P.wood, 10)
  planter(s, -0.28, 0.31, P.foliage[2])
  return s.finish()
}

export function stargazingDeck(): Model {
  const s = new Sculpture()
  for (let i = 0; i < 9; i++) s.box([0.095, 0.055, 0.82], [(i - 4) * 0.103, 0.13, 0], i % 2 ? P.wood : P.path, [0, 0, 0], 0.006)
  for (const x of [-0.39, 0.39]) for (const z of [-0.35, 0.35]) s.box([0.055, 0.33, 0.055], [x, 0.17, z], P.timber)
  for (const x of [-0.39, 0.39]) s.box([0.035, 0.035, 0.84], [x, 0.34, 0], P.wood)
  s.box([0.84, 0.035, 0.035], [0, 0.34, -0.36], P.wood)
  for (let i = 0; i < 3; i++) {const a = i * Math.PI * 2 / 3;beam(s, [0, 0.62, 0], [Math.sin(a) * 0.18, 0.16, Math.cos(a) * 0.18], 0.018, P.metal)}
  s.cylinder(0.064, 0.043, 0.45, [0, 0.69, -0.09], P.armor, 12, [-Math.PI / 3, 0.35, 0])
  s.sphere(0.055, [0.046, 0.795, -0.26], P.magic, [1, 0.7, 0.4])
  s.box([0.22, 0.02, 0.17], [0.23, 0.181, 0.19], P.wall, [0, 0.15, 0])
  return s.finish()
}

export function companionDen(): Model {
  const s = new Sculpture()
  s.box([0.74, 0.08, 0.64], [0, 0.04, 0], P.stone, [0, 0, 0], 0.03)
  for (const x of [-0.265, 0.265]) s.box([0.1, 0.4, 0.53], [x, 0.26, 0], P.wood, [0, 0, 0], 0.015)
  s.box([0.44, 0.4, 0.07], [0, 0.26, -0.25], P.wood)
  s.box([0.48, 0.1, 0.075], [0, 0.415, 0.255], P.wood)
  tiledRoof(s, [0, 0.465, 0], 0.79, 0.3, 0.74, P.roof_forest)
  s.sphere(0.22, [0, 0.12, 0.12], P.foliage[1], [1, 0.19, 0.9])
  s.cylinder(0.073, 0.084, 0.045, [0.28, 0.1, 0.39], P.metal, 12)
  s.cylinder(0.064, 0.064, 0.004, [0.28, 0.125, 0.39], P.water, 12)
  planter(s, -0.36, 0.29)
  return s.finish()
}

export function flowerBed(): Model {
  const s = new Sculpture()
  s.box([0.71, 0.085, 0.45], [0, 0.043, 0], P.soil, [0, 0, 0], 0.03)
  for (const x of [-0.37, 0.37]) s.box([0.045, 0.12, 0.52], [x, 0.06, 0], P.wood)
  for (const z of [-0.24, 0.24]) s.box([0.76, 0.12, 0.045], [0, 0.06, z], P.wood)
  for (let i = 0; i < 7; i++) {
    const x = Math.sin(i * 2.4) * 0.27, z = Math.cos(i * 2.4) * 0.15, h = 0.22 + i % 3 * 0.04
    beam(s, [x, 0.08, z], [x + 0.025, h, z], 0.008, P.foliage[2])
    s.sphere(0.045, [x, h * 0.65, z], P.foliage[i % 3], [1, 0.35, 0.6])
    for (let petal = 0; petal < 5; petal++) s.sphere(0.035, [x + Math.sin(petal * 1.256) * 0.036, h, z + Math.cos(petal * 1.256) * 0.036], P.flower[i % 3], [1, 0.4, 1])
    s.sphere(0.019, [x, h + 0.007, z], P.flag)
  }
  return s.finish()
}

function finishUnit(s: Sculpture, pose: UnitPose): Model {
  const model = s.finish()
  if (pose === 'defeat' || pose === 'rest') {
    const matrix = new THREE.Matrix4().makeRotationZ(pose === 'defeat' ? Math.PI / 2 : 0)
    if (pose === 'defeat') matrix.setPosition(0.32, 0.14, 0)
    else matrix.scale(new THREE.Vector3(1.08, 0.64, 1.08))
    model.body.applyMatrix4(matrix);model.light.applyMatrix4(matrix)
    groundModel(model)
    model.body.computeBoundingSphere();if (model.light.getAttribute('position')) model.light.computeBoundingSphere()
  }
  return model
}

export function heroModel(stage: number, pose: UnitPose): Model {
  const s = new Sculpture(), raised = pose === 'cast' || pose === 'victory', attack = pose === 'attack', stride = pose === 'walk' || attack
  s.cylinder(0.135, 0.2, 0.38, [0, 0.46, 0], P.hero_cloak, 8)
  // The cloak is a thick sculpted volume; its folds and clasp also exist behind.
  s.add(new THREE.ConeGeometry(0.25, 0.47, 8, 1, false, Math.PI / 2, Math.PI), P.hero_cloak, [0, 0.47, -0.07], [0.12, 0, 0], [1, 1, 0.7])
  s.box([0.3, 0.045, 0.24], [0, 0.38, 0.012], P.timber, [0, 0, 0], 0.01)
  s.box([0.05, 0.045, 0.026], [0, 0.38, 0.144], P.flag)
  for (const side of [-1, 1]) {
    const z = stride ? side * 0.085 : 0
    s.cylinder(0.047, 0.058, 0.26, [side * 0.085, 0.16, z], P.timber, 8, [stride ? side * 0.24 : 0, 0, 0])
    s.box([0.105, 0.09, 0.16], [side * 0.085, 0.055, z + 0.04], P.hero_hair, [0, 0, 0], 0.025)
    const hand: V3 = [side * (raised ? 0.31 : 0.2), raised ? 0.86 : attack && side > 0 ? 0.57 : 0.38, attack && side > 0 ? 0.37 : 0.035]
    beam(s, [side * 0.12, 0.61, 0], hand, 0.053, P.hero_cloak)
    s.sphere(0.05, hand, P.hero_skin)
    if (stage > 1) s.sphere(0.105, [side * 0.165, 0.6, 0], P.armor, [1, 0.55, 0.9])
  }
  s.sphere(0.14, [0, 0.77, 0.015], P.hero_skin, [0.87, 1.04, 0.86])
  s.sphere(0.145, [0, 0.835, -0.007], P.hero_hair, [0.95, 0.63, 0.95])
  for (const x of [-0.047, 0.047]) s.sphere(0.012, [x, 0.775, 0.129], P.hero_hair, [0.85, 1.15, 0.5])
  s.box([0.08, 0.05, 0.035], [0, 0.63, 0.16], P.flag, [0, 0, Math.PI / 4])
  if (attack) {
    beam(s, [0.2, 0.58, 0.33], [0.2, 0.61, 0.88], 0.026, P.armor)
    s.box([0.22, 0.03, 0.045], [0.2, 0.58, 0.44], P.flag)
  } else {
    const x = raised ? 0.31 : 0.23, y = raised ? 0.34 : 0
    beam(s, [x, 0.04 + y, 0.04], [x, 0.93 + y, 0.04], 0.023, P.wood)
    s.add(new THREE.OctahedronGeometry(0.073), P.magic, [x, 1.005 + y, 0.04], [0, 0, 0], [0.8, 1.25, 0.8], raised)
  }
  if (stage > 2) {
    s.cylinder(0.148, 0.16, 0.065, [0, 0.854, 0], P.armor, 10)
    for (const x of [-0.085, 0, 0.085]) s.add(new THREE.OctahedronGeometry(0.06), P.flag, [x, 0.92, 0.035], [0, 0, 0], [0.33, 1, 0.38])
    s.box([0.2, 0.17, 0.055], [0, 0.515, 0.132], P.armor, [0, 0, 0], 0.025)
    s.add(new THREE.OctahedronGeometry(0.036), P.magic, [0, 0.535, 0.172], [0, 0, 0], [1, 1, 0.45], true)
  }
  return finishUnit(s, pose)
}

export function bearModel(stage: number, pose: UnitPose): Model {
  const s = new Sculpture(), raised = pose === 'cast' || pose === 'victory'
  s.sphere(0.32, [0, 0.4, -0.04], P.trunk, [1.08, 1, 1.08])
  s.sphere(0.225, [0, 0.66, 0.16], P.wood, [1.08, 0.94, 0.91])
  s.sphere(0.113, [0, 0.596, 0.327], P.path, [1, 0.65, 0.6])
  s.sphere(0.033, [0, 0.625, 0.385], P.timber, [1.25, 0.7, 0.7])
  for (const side of [-1, 1]) {
    s.sphere(0.075, [side * 0.177, 0.812, 0.1], P.trunk, [1, 0.9, 0.45])
    s.sphere(0.04, [side * 0.177, 0.818, 0.135], P.path, [1, 0.75, 0.4])
    s.sphere(0.017, [side * 0.084, 0.697, 0.343], P.timber)
    s.sphere(0.14, [side * 0.19, 0.11, 0.02], P.trunk, [0.85, 0.83, 1.2])
    s.sphere(0.14, [side * (raised ? 0.36 : 0.28), raised ? 0.74 : pose === 'attack' ? 0.37 : 0.35, pose === 'attack' ? 0.3 : 0.06], P.trunk, [0.8, 1.25, 0.8])
    for (let nail = 0; nail < 3; nail++) s.sphere(0.021, [side * 0.19 + (nail - 1) * 0.04, 0.075, 0.172], P.stone, [0.6, 0.6, 1.4])
  }
  const rocks = 3 + stage * 2
  for (let i = 0; i < rocks; i++) {
    const a = i * 2.4
    s.sphere(0.11 + stage * 0.015, [Math.sin(a) * 0.255, 0.48 + i % 3 * 0.075, -0.12 + Math.cos(a) * 0.2], i % 2 ? P.cliff : P.stone, [1, 0.75, 0.8])
    if (i % 2 === 0) s.sphere(0.076, [Math.sin(a) * 0.25, 0.56 + i % 3 * 0.075, -0.1 + Math.cos(a) * 0.2], P.foliage[i % 4], [1, 0.3, 1])
  }
  if (stage > 1) for (const x of [-0.29, 0.29]) s.sphere(0.18, [x, 0.5, 0.06], P.stone, [1, 0.8, 0.95])
  if (stage > 2) {
    s.add(new THREE.OctahedronGeometry(0.12), P.heal, [0, 0.55, 0.28], [0, 0, 0], [0.65, 1, 0.38], true)
    for (const x of [-0.19, 0.19]) s.cylinder(0.01, 0.05, 0.18, [x, 0.9, 0.04], P.cliff, 5, [0, 0, -x * 2])
  }
  return finishUnit(s, pose)
}

export function wolfModel(stage: number, pose: UnitPose): Model {
  const s = new Sculpture(), attack = pose === 'attack', h = attack ? 0.32 : 0.39
  s.sphere(0.24, [0, h, -0.02], P.wolf, [0.73, 0.9, 1.6])
  s.sphere(0.2, [0, h + 0.2, 0.25], P.wolf, [0.87, 1.04, 0.96])
  s.sphere(0.1, [0, h + 0.12, 0.42], P.wolf_light, [0.65, 0.62, 1.25])
  s.sphere(0.036, [0, h + 0.139, 0.531], P.timber, [1, 0.6, 0.65])
  for (const side of [-1, 1]) {
    s.cylinder(0.002, 0.07, 0.21, [side * 0.12, h + 0.42, 0.205], P.wolf, 3, [-0.14, 0, -side * 0.2])
    s.sphere(0.016, [side * 0.091, h + 0.236, 0.403], P.window, [1, 0.6, 0.65])
    for (const z of [-0.25, 0.21]) {
      const stride = pose === 'walk' || attack ? side * (z > 0 ? 0.1 : -0.1) : 0
      beam(s, [side * 0.126, h, z], [side * 0.135, 0.075, z + stride], 0.042, P.wolf)
      s.sphere(0.064, [side * 0.135, 0.06, z + stride + 0.02], P.wolf_light, [0.75, 0.55, 1.3])
    }
  }
  s.sphere(0.12, [0.09, h + 0.02, -0.46], P.wolf, [0.85, 0.7, 1.6])
  s.sphere(0.072, [0.12, h + 0.08, -0.625], P.wolf_light, [0.7, 0.7, 1.2])
  // A mane and distinct armour silhouette at later growth stages.
  for (let i = 0; i < 5; i++) s.cylinder(0, 0.058, 0.19, [Math.sin(i * 1.25) * 0.14, h + 0.14, 0.1 + Math.cos(i * 1.25) * 0.09], P.wolf_light, 5, [0.5, 0, 0])
  if (stage > 1) for (const x of [-0.17, 0.17]) s.sphere(0.13, [x, h + 0.055, 0.1], P.metal, [0.65, 0.8, 1.2])
  if (stage > 2) {
    for (let i = 0; i < 4; i++) s.add(new THREE.OctahedronGeometry(0.085), P.armor, [0, h + 0.24, 0.03 - i * 0.12], [0.45, 0, 0], [0.6, 1.3, 0.8])
    s.add(new THREE.OctahedronGeometry(0.054), P.magic, [0, h + 0.36, 0.355], [0, 0, 0], [0.8, 1.3, 0.5], true)
  }
  return finishUnit(s, pose)
}

export function starFoxModel(stage: number, pose: UnitPose): Model {
  const s = new Sculpture(), raised = pose === 'cast' || pose === 'victory'
  s.sphere(0.23, [0, 0.28, 0], P.star_fox, [0.8, 1.02, 0.85])
  s.sphere(0.205, [0, 0.56, 0.035], P.star_fox, [1, 0.83, 0.85])
  s.sphere(0.11, [0, 0.51, 0.178], P.wall, [0.9, 0.62, 0.65])
  for (const side of [-1, 1]) {
    s.cylinder(0.003, 0.086, 0.25, [side * 0.139, 0.76, 0], P.star_fox, 3, [-0.12, 0, -side * 0.18])
    s.cylinder(0.003, 0.038, 0.14, [side * 0.139, 0.79, 0.034], P.roof_plaza, 3, [-0.12, 0, -side * 0.18])
    s.sphere(0.018, [side * 0.088, 0.581, 0.203], P.timber, [1, 1.1, 0.6])
    s.sphere(0.075, [side * 0.1, 0.064, 0.064], P.star_fox, [0.65, 0.65, 1.1])
    s.sphere(0.08, [side * (raised ? 0.24 : 0.16), raised ? 0.56 : 0.3, 0.067], P.star_fox, [0.6, 1.2, 0.65])
  }
  s.sphere(0.023, [0, 0.53, 0.249], P.timber)
  s.cylinder(0.145, 0.16, 0.053, [0, 0.409, 0.004], P.roof_valley, 10)
  s.box([0.07, 0.19, 0.025], [0.09, 0.32, 0.166], P.roof_valley, [0, 0, 0.18])
  for (let tail = 0; tail < stage; tail++) {
    const a = (tail - (stage - 1) / 2) * 0.64
    s.sphere(0.16, [Math.sin(a) * 0.33, 0.18, -0.24 - Math.cos(a) * 0.065], P.star_fox, [0.8, 0.6, 1.6])
    s.sphere(0.11, [Math.sin(a) * 0.46, 0.22, -0.32 - Math.cos(a) * 0.14], P.wall, [0.7, 0.55, 1.4])
  }
  s.add(new THREE.OctahedronGeometry(stage > 1 ? 0.066 : 0.045), P.window, [0, 0.376, 0.172], [0, 0, Math.PI / 4], [1, 1, 0.55], true)
  if (stage > 1) s.add(new THREE.TorusGeometry(0.092, 0.012, 5, 12), P.flag, [0.25, 0.51, 0.11], [Math.PI / 2, 0, 0])
  if (stage > 2) {
    s.add(new THREE.OctahedronGeometry(0.075), P.magic, [0.25, 0.58, 0.11], [0, 0, 0], [0.8, 1.3, 0.8], true)
    s.cylinder(0.157, 0.16, 0.03, [0, 0.685, 0], P.flag, 10)
    s.add(new THREE.OctahedronGeometry(0.06), P.window, [0, 0.72, 0.157], [0, 0, 0], [0.65, 1, 0.5], true)
  }
  return finishUnit(s, pose)
}

export function outpostModel(theme: string, boss: boolean, occupied: boolean): Model {
  const s = new Sculpture(), roof = theme === 'frost_ridge' ? P.roof_valley : theme === 'ancient_ruins' ? P.roof_plaza : P.roof_forest
  s.cylinder(0.48, 0.53, 0.13, [0, 0.065, 0], theme === 'frost_ridge' ? P.snow : P.stone, 12)
  if (boss) {
    for (const side of [-1, 1]) {
      s.cylinder(0.16, 0.19, 0.86, [side * 0.28, 0.53, -0.08], P.wall_shade, 12)
      s.cylinder(0.007, 0.22, 0.34, [side * 0.28, 1.13, -0.08], roof, 12)
      if (occupied) s.window([side * 0.28, 0.72, 0.087], [0.095, 0.2, 0.02])
    }
    s.box([0.63, 0.22, 0.27], [0, 0.73, 0.01], P.stone, [0, 0, 0], 0.025)
    s.gable([0, 0.86, 0], 0.45, 0.16, 0.35, roof)
    banner(s, [0.38, 0.12, 0.26], occupied, true)
    for (let i = 0; i < 3; i++) s.box([0.34 + i * 0.08, 0.04, 0.1], [0, 0.14 - i * 0.03, 0.27 + i * 0.09], P.stone)
  } else if (theme === 'ancient_ruins') {
    for (const x of [-0.24, 0.24]) s.cylinder(0.065, 0.086, occupied ? 0.58 : x > 0 ? 0.39 : 0.58, [x, 0.4, -0.08], P.stone, 8)
    s.box([0.7, 0.1, 0.21], [0, 0.72, -0.08], P.wall_shade, [0, 0, occupied ? 0 : -0.06], 0.02)
    s.add(new THREE.OctahedronGeometry(0.145), occupied ? P.magic : P.unknown, [0, 0.49, 0], [0, Math.PI / 4, 0], [0.65, 1.3, 0.65], occupied)
    banner(s, [0.31, 0.13, 0.25], occupied)
  } else {
    facade(s, 0.48, 0.41, 0.43, roof, 1)
    tiledRoof(s, [0, 0.47, 0], 0.67, 0.29, 0.59, roof)
    for (const x of [-0.36, 0.36]) {
      s.box([0.052, 0.33, 0.052], [x, 0.24, 0.24], P.wood)
      s.box([0.25, 0.043, 0.04], [x, 0.27, 0.24], P.timber)
    }
    banner(s, [0.32, 0.13, -0.26], occupied)
  }
  return s.finish()
}

export function trophyModel(theme: string): Model {
  const s = new Sculpture()
  s.cylinder(0.19, 0.24, 0.16, [0, 0.08, 0], P.stone, 8)
  s.cylinder(0.155, 0.16, 0.1, [0, 0.21, 0], P.flag, 8)
  if (theme.includes('forest')) s.sphere(0.15, [0, 0.42, 0], P.foliage[0], [1, 1.25, 0.8])
  else if (theme.includes('frost')) s.add(new THREE.OctahedronGeometry(0.2), P.magic, [0, 0.43, 0], [0, 0, 0], [0.7, 1.4, 0.7])
  else {s.add(new THREE.TorusGeometry(0.17, 0.028, 7, 18), P.flag, [0, 0.46, 0]);s.sphere(0.064, [0, 0.46, 0], P.window)}
  return s.finish()
}

/** A modelled interior with thick walls, furnishings and readable open frontage. */
export function restRoomModel(): Model {
  const s = new Sculpture()
  s.box([2.3, 0.14, 1.8], [0, 0.07, 0], P.stone, [0, 0, 0], 0.065)
  for (let i = 0; i < 15; i++) s.box([0.144, 0.025, 1.65], [-1.05 + i * 0.15, 0.16, 0], i % 3 ? P.wood : P.path)
  s.box([2.2, 1.16, 0.13], [0, 0.7, -0.84], P.wall, [0, 0, 0], 0.02)
  s.box([0.13, 0.67, 1.7], [-1.085, 0.48, -0.02], P.wall_shade, [0, 0, 0], 0.02)
  s.box([2.25, 0.07, 0.18], [0, 1.32, -0.84], P.timber)
  s.window([-0.5, 0.82, -0.755], [0.49, 0.55, 0.025])
  s.box([0.77, 0.2, 0.4], [-0.42, 0.34, -0.21], P.foliage[2], [0, 0, 0], 0.075)
  s.box([0.81, 0.4, 0.15], [-0.42, 0.56, -0.43], P.hero_cloak, [0, 0, 0], 0.06)
  for (const x of [-0.79, -0.05]) s.box([0.14, 0.24, 0.48], [x, 0.45, -0.19], P.hero_cloak, [0, 0, 0], 0.04)
  s.sphere(0.16, [-0.57, 0.52, -0.3], P.path, [1, 0.7, 0.4])
  for (const x of [0.43, 0.96]) s.box([0.045, 0.9, 0.28], [x, 0.64, -0.61], P.timber)
  for (let shelf = 0; shelf < 4; shelf++) {
    s.box([0.57, 0.04, 0.28], [0.695, 0.21 + shelf * 0.255, -0.61], P.wood)
    books(s, [0.48, 0.28 + shelf * 0.255, -0.59], shelf === 3 ? 3 : 9)
  }
  s.cylinder(0.24, 0.24, 0.045, [-0.18, 0.36, 0.42], P.wood, 14)
  for (let i = 0; i < 3; i++) {const a = i * Math.PI * 2 / 3;beam(s, [-0.18, 0.34, 0.42], [-0.18 + Math.sin(a) * 0.17, 0.17, 0.42 + Math.cos(a) * 0.17], 0.023, P.timber)}
  s.box([0.17, 0.024, 0.14], [-0.24, 0.4, 0.43], P.roof_plaza, [0, 0.2, 0])
  s.cylinder(0.035, 0.03, 0.07, [-0.05, 0.416, 0.45], P.wall, 10)
  s.cylinder(0.02, 0.04, 0.67, [-0.94, 0.5, -0.5], P.metal, 8)
  s.add(new THREE.CylinderGeometry(0.12, 0.19, 0.2, 12), '#FFFFFF', [-0.94, 0.91, -0.5], [0, 0, 0], [1, 1, 1], true)
  return s.finish()
}

/** Study cabin: a desk under the window, a warm lamp, an open book and a shelf. */
export function studyRoomModel(): Model {
  const s = new Sculpture()
  s.box([2.3, 0.14, 1.8], [0, 0.07, 0], P.stone, [0, 0, 0], 0.065)
  for (let i = 0; i < 15; i++) s.box([0.144, 0.025, 1.65], [-1.05 + i * 0.15, 0.16, 0], i % 3 ? P.wood : P.path)
  s.box([2.2, 1.16, 0.13], [0, 0.7, -0.84], P.wall, [0, 0, 0], 0.02)
  s.box([0.13, 0.67, 1.7], [-1.085, 0.48, -0.02], P.wall_shade, [0, 0, 0], 0.02)
  s.box([2.25, 0.07, 0.18], [0, 1.32, -0.84], P.timber)
  s.window([0.05, 0.86, -0.755], [0.72, 0.5, 0.025])
  s.box([1.2, 0.18, 0.025], [0.05, 1.18, -0.76], P.roof_forest, [0, 0, 0], 0.01)
  // rug, desk and chair
  s.box([1.25, 0.012, 0.8], [0.05, 0.18, 0.1], P.roof_plaza, [0, 0, 0], 0.004)
  s.box([1.05, 0.05, 0.46], [0.05, 0.56, -0.48], P.wood, [0, 0, 0], 0.012)
  for (const x of [-0.42, 0.52]) for (const z of [-0.66, -0.3]) s.box([0.05, 0.38, 0.05], [x, 0.36, z], P.timber)
  s.box([0.3, 0.16, 0.4], [0.36, 0.44, -0.48], P.timber, [0, 0, 0], 0.01)
  s.box([0.36, 0.05, 0.34], [0.02, 0.38, -0.02], P.wood, [0, 0.12, 0], 0.012)
  s.box([0.36, 0.38, 0.05], [0.0, 0.58, 0.14], P.wood, [0, 0.12, 0], 0.012)
  for (const x of [-0.13, 0.17]) for (const z of [-0.15, 0.12]) s.box([0.04, 0.22, 0.04], [x, 0.26, z], P.timber)
  // open book, a stack, a mug and the lamp
  s.box([0.2, 0.012, 0.15], [-0.06, 0.592, -0.42], P.wall, [0, 0, 0.07])
  s.box([0.2, 0.012, 0.15], [0.14, 0.592, -0.42], P.wall, [0, 0, -0.07])
  books(s, [-0.36, 0.64, -0.55], 4)
  s.cylinder(0.036, 0.032, 0.08, [0.32, 0.625, -0.36], P.roof_valley, 12)
  s.cylinder(0.07, 0.08, 0.025, [-0.3, 0.597, -0.62], P.metal, 14)
  beam(s, [-0.3, 0.6, -0.62], [-0.22, 0.86, -0.6], 0.012, P.metal)
  beam(s, [-0.22, 0.86, -0.6], [-0.08, 0.84, -0.5], 0.012, P.metal)
  s.add(new THREE.ConeGeometry(0.08, 0.1, 14, 1, true), '#FFFFFF', [-0.06, 0.8, -0.49], [0.3, 0, 0], [1, 1, 1], true)
  // shelf with books and a small plant
  for (const x of [-0.98, -0.5]) s.box([0.045, 0.9, 0.26], [x, 0.64, -0.62], P.timber)
  for (let shelf = 0; shelf < 4; shelf++) {
    s.box([0.5, 0.04, 0.26], [-0.74, 0.21 + shelf * 0.255, -0.62], P.wood)
    if (shelf < 3) books(s, [-0.92, 0.28 + shelf * 0.255, -0.6], 6 + shelf % 2 * 2)
  }
  s.cylinder(0.07, 0.05, 0.11, [-0.66, 1.07, -0.62], P.roof_plaza, 12)
  s.sphere(0.11, [-0.66, 1.18, -0.62], P.foliage[1], [1, 0.8, 1])
  return s.finish()
}

const decorators: Record<string, () => Model> = {flower_bed: flowerBed, reading_bench: readingBench, stone_well: stoneWell, stargazing_deck: stargazingDeck, companion_den: companionDen}
const units: Record<string, (stage: number, pose: UnitPose) => Model> = {hero: heroModel, moss_bear: bearModel, shadow_wolf: wolfModel, star_fox: starFoxModel}

export function gameModelFactory(key: string): (() => Model) | undefined {
  const [kind, code, stageText, poseText] = key.split(':'), stage = Number(stageText)
  if (kind === 'home' && code === 'camp_hall' && Number.isInteger(stage) && stage >= 1 && stage <= rules.home.max_building_level) return () => campHall(stage)
  if (kind === 'decor' && Object.hasOwn(decorators,code)) return decorators[code]
  if (kind === 'unit' && Object.hasOwn(units,code) && Number.isInteger(stage) && stage >= 1 && stage <= (code === 'hero' ? rules.hero.visual_stage_min_levels.length : rules.monsters.visual_stage_min_levels.length) && unitPoses.includes(poseText as UnitPose)) return () => units[code](stage, poseText as UnitPose)
  if (kind === 'unit' && enemyCodes.includes(code) && Number.isInteger(stage) && stage >= 1 && stage <= 3 && unitPoses.includes(poseText as UnitPose)) return () => enemyModel(code, poseText as UnitPose)
  if (kind === 'outpost' && rules.content.suggested_region_themes.includes(code) && ['boss', 'camp'].includes(stageText) && ['occupied', 'hostile'].includes(poseText)) return () => outpostModel(code, stageText === 'boss', poseText === 'occupied')
  if (kind === 'trophy' && rules.content.suggested_region_themes.includes(code)) return () => trophyModel(code)
  if (key === 'room:reading') return restRoomModel
  if (key === 'room:study') return studyRoomModel
  return undefined
}
