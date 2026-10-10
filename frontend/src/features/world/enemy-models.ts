import * as THREE from 'three'
import tokens from '../../../../docs/contracts/design-tokens.json'
import {Sculpture, beam, groundModel} from './sculpture'
import type {Model} from './models'
import type {UnitPose} from './game-models'

const P = tokens.world.scene_palette
export const enemyCodes: readonly string[] = ['bramble', 'boar', 'wisp', 'forest_boss', 'ice_guard', 'ice_wolf', 'snow_oracle', 'frost_boss', 'ruin_guard', 'ruin_mage', 'ruin_oracle', 'ruin_boss']

function eyes(s: Sculpture, y: number, z: number, apart = 0.09, color = P.window) {
  for (const side of [-1, 1]) s.sphere(0.025, [side * apart, y, z], color, [1, 0.65, 0.45])
}
function crystal(s: Sculpture, at: [number, number, number], size: number, color = P.magic, light = false) {
  s.add(new THREE.OctahedronGeometry(size), color, at, [0, Math.PI / 4, 0], [0.6, 1.5, 0.7], light)
}

/** Silhouettes are authored per creature. No reference image is used as a sprite. */
export function enemyModel(code: string, pose: UnitPose): Model {
  const s = new Sculpture(), strike = pose === 'attack', cast = pose === 'cast', victory = pose === 'victory'
  if (code === 'bramble') {
    s.sphere(0.28, [0, 0.32, 0], P.foliage[2], [1, 0.88, 0.9])
    for (let i = 0; i < 8; i++) {
      const a = i * Math.PI / 4, x = Math.sin(a) * 0.22, z = Math.cos(a) * 0.22
      beam(s, [x, 0.3, z], [x * 1.5, 0.065, z * 1.5], 0.03, P.trunk)
      s.cylinder(0, 0.065, 0.25, [x, 0.45, z], P.wood, 5, [Math.cos(a) * 0.35, 0, -Math.sin(a) * 0.35])
    }
    eyes(s, 0.4, 0.238)
    for (const side of [-1, 1]) beam(s, [side * 0.21, 0.32, 0], [side * 0.47, strike ? 0.44 : 0.22, strike ? 0.32 : 0.1], 0.033, P.foliage[1])
    s.sphere(0.08, [0, 0.62, 0], P.flower[2], [1, 0.6, 1])
  } else if (code === 'boar' || code === 'ice_wolf') {
    const wolf = code === 'ice_wolf', coat = wolf ? P.snow : P.trunk
    s.sphere(0.27, [0, 0.35, -0.1], coat, [wolf ? 0.65 : 1.1, 0.88, 1.55])
    s.sphere(0.22, [0, wolf ? 0.61 : 0.36, 0.24], coat, [0.88, wolf ? 0.9 : 1.12, 1])
    s.sphere(0.12, [0, wolf ? 0.54 : 0.29, 0.44], wolf ? P.wolf : P.wood, [0.76, 0.6, 0.7])
    eyes(s, wolf ? 0.65 : 0.43, 0.418, 0.088, wolf ? P.magic : P.window)
    for (const side of [-1, 1]) {
      s.cylinder(0, 0.07, wolf ? 0.22 : 0.12, [side * 0.145, wolf ? 0.85 : 0.59, 0.13], coat, 3, [0, 0, -side * 0.28])
      if (!wolf) {
        beam(s, [side * 0.1, 0.21, 0.39], [side * 0.16, 0.26, 0.55], 0.035, P.wall)
        beam(s, [side * 0.16, 0.26, 0.55], [side * 0.13, 0.36, 0.56], 0.023, P.wall)
      }
      for (const z of [-0.3, 0.15]) {
        const step = (strike || pose === 'walk') ? side * (z < 0 ? 0.09 : -0.09) : 0
        beam(s, [side * 0.16, 0.29, z], [side * 0.16, 0.055, z + step], 0.047, wolf ? P.wolf_light : P.timber)
        s.box([0.085, 0.075, 0.14], [side * 0.16, 0.04, z + step + 0.02], wolf ? P.snow : P.timber, [0, 0, 0], 0.014)
      }
    }
    for (let i = 0; i < 5; i++) {
      if (wolf) crystal(s, [0, 0.63 - i * 0.025, 0.04 - i * 0.1], 0.1)
      else s.cylinder(0, 0.045, 0.16, [0, 0.61, 0.09 - i * 0.12], P.timber, 4, [0.4, 0, 0])
    }
    s.sphere(wolf ? 0.1 : 0.04, [0.1, 0.33, -0.56], coat, [1, 0.7, wolf ? 2 : 1.5])
  } else if (code === 'wisp' || code === 'snow_oracle' || code === 'ruin_oracle' || code === 'ruin_mage') {
    const snow = code === 'snow_oracle', oracle = code === 'ruin_oracle', mage = code === 'ruin_mage'
    const color = snow ? P.snow : oracle ? P.roof_plaza : mage ? P.wolf : P.foliage[1]
    if (code === 'wisp') {
      s.sphere(0.16, [0, 0.52, 0], P.magic)
      for (let i = 0; i < 6; i++) {const a = i * Math.PI / 3;s.sphere(0.09, [Math.sin(a) * 0.22, 0.54, Math.cos(a) * 0.22], P.foliage[i % 4], [1, 0.3, 1.65])}
      for (let i = 0; i < 4; i++) s.sphere(0.06 - i * 0.009, [Math.sin(i) * 0.065, 0.31 - i * 0.063, -0.025], P.magic)
    } else {
      s.cylinder(0.085, 0.27, 0.5, [0, 0.49, 0], color, oracle ? 6 : 10)
      s.sphere(0.15, [0, 0.85, 0], P.wall_shade, [0.84, 1, 0.75])
      s.cylinder(0.015, 0.25, 0.34, [0, 1.09, -0.025], color, mage ? 8 : 6, [-0.08, 0, mage ? 0.17 : 0])
      s.cylinder(0.27, 0.27, 0.035, [0, 0.922, 0], color, 12)
      for (const side of [-1, 1]) {
        beam(s, [side * 0.09, 0.69, 0], [side * 0.32, cast ? 0.9 : 0.56, 0.11], 0.059, color)
        s.sphere(0.055, [side * 0.34, cast ? 0.92 : 0.57, 0.12], P.wall_shade)
      }
      if (snow) {
        beam(s, [0.35, 0.18, 0.13], [0.35, 1.18, 0.13], 0.023, P.wood)
        crystal(s, [0.35, 1.29, 0.13], 0.105)
        for (let i = 0; i < 3; i++) crystal(s, [-0.3 - i * 0.07, 0.69 + i * 0.1, 0.08], 0.038)
      } else {
        s.add(new THREE.TorusGeometry(oracle ? 0.43 : 0.23, 0.025, 6, 24), P.flag, [0, oracle ? 0.79 : 0.56, oracle ? -0.08 : 0.23], [0, 0, oracle ? 0 : Math.PI / 3])
        crystal(s, [0, 0.55, 0.25], oracle ? 0.12 : 0.09, P.magic, true)
      }
    }
    eyes(s, code === 'wisp' ? 0.55 : 0.865, code === 'wisp' ? 0.148 : 0.13, 0.055)
  } else if (code === 'forest_boss') {
    s.cylinder(0.22, 0.38, 0.73, [0, 0.43, 0], P.trunk, 10)
    for (let i = 0; i < 6; i++) {const a = i * Math.PI / 3;beam(s, [Math.sin(a) * 0.22, 0.24, Math.cos(a) * 0.22], [Math.sin(a) * 0.49, 0.02, Math.cos(a) * 0.49], 0.07, P.wood)}
    s.sphere(0.27, [0, 0.9, 0], P.trunk, [1, 1.1, 0.78]);eyes(s, 0.93, 0.21, 0.12, P.heal)
    for (const side of [-1, 1]) {
      const tip: [number, number, number] = [side * 0.68, strike ? 0.63 : 0.4, strike ? 0.36 : 0.1]
      beam(s, [side * 0.23, 0.7, 0], tip, 0.09, P.wood)
      for (let finger = 0; finger < 3; finger++) beam(s, tip, [tip[0] + side * 0.09, tip[1] - 0.12, tip[2] + (finger - 1) * 0.09], 0.024, P.trunk)
      beam(s, [side * 0.16, 1.03, 0], [side * 0.32, 1.46, -0.1], 0.05, P.wood)
      beam(s, [side * 0.23, 1.25, -0.06], [side * 0.5, 1.34, 0.02], 0.032, P.wood)
      s.sphere(0.25, [side * 0.25, 0.95, -0.19], P.foliage[side > 0 ? 1 : 2], [1, 0.6, 1])
      s.sphere(0.13, [side * 0.5, 1.38, 0.02], P.foliage[0], [1, 0.5, 0.9])
    }
    crystal(s, [0, 0.51, 0.31], 0.12, P.heal, cast)
  } else {
    const ice = code === 'ice_guard' || code === 'frost_boss', boss = code.endsWith('boss'), ruinBoss = code === 'ruin_boss'
    const stone = ice ? P.snow : P.stone, size = boss ? 1.34 : 1
    s.box([0.49 * size, 0.43 * size, 0.31 * size], [0, 0.59 * size, 0], stone, [0, 0, 0], 0.075)
    for (const side of [-1, 1]) {
      const raised = cast || victory
      s.sphere(0.17 * size, [side * 0.33 * size, 0.73 * size, 0], ice ? P.armor : P.cliff, [1.1, 0.83, 1])
      beam(s, [side * 0.34 * size, 0.64 * size, 0], [side * 0.43 * size, (raised ? 0.9 : 0.35) * size, strike ? 0.3 : 0.03], 0.09 * size, stone)
      s.box([0.22 * size, 0.22 * size, 0.23 * size], [side * 0.44 * size, (raised ? 0.96 : 0.29) * size, strike ? 0.37 : 0.055], stone, [0, 0, 0], 0.04)
      s.box([0.17 * size, 0.27 * size, 0.2 * size], [side * 0.14 * size, 0.2 * size, 0], P.cliff, [0, 0, 0], 0.025)
      s.box([0.21 * size, 0.13 * size, 0.29 * size], [side * 0.14 * size, 0.065 * size, 0.035], stone, [0, 0, 0], 0.025)
    }
    if (ruinBoss) {
      for (const x of [-0.17, 0.17]) s.box([0.12, 0.42, 0.27], [x, 1.25, 0], P.cliff, [0, 0, 0], 0.02)
      s.box([0.55, 0.11, 0.3], [0, 1.51, 0], P.stone, [0, 0, 0], 0.02)
      s.add(new THREE.TorusGeometry(0.26, 0.045, 6, 16), P.flag, [0, 0.91, 0.25])
      crystal(s, [0, 0.91, 0.25], 0.18, P.magic, true)
      eyes(s, 1.41, 0.148, 0.11)
    } else {
      s.box([0.28 * size, 0.28 * size, 0.28 * size], [0, 0.95 * size, 0.015], stone, [0, 0, 0], 0.05)
      eyes(s, 0.965 * size, 0.164 * size, 0.085 * size, ice ? P.magic : P.window)
      crystal(s, [0, 0.6 * size, 0.175 * size], boss ? 0.15 : 0.065, ice ? P.magic : P.window, cast)
    }
    if (ice) for (let i = 0; i < (boss ? 7 : 3); i++) crystal(s, [(i - (boss ? 3 : 1)) * 0.12, 0.96 * size, -0.12 - Math.abs(i - 2) * 0.025], boss ? 0.23 : 0.13)
    if (code === 'ice_guard') {
      beam(s, [0.48, 0.04, 0.12], [0.48, 1.33, 0.12], 0.02, P.timber)
      crystal(s, [0.48, 1.4, 0.12], 0.085)
      s.box([0.08, 0.43, 0.32], [-0.5, 0.52, 0.07], P.armor, [0, 0, 0], 0.03)
    }
    if (code === 'ruin_guard') {
      s.box([0.16, 0.57, 0.15], [0.48, 0.36, 0.19], P.cliff, [0, 0, -0.1], 0.02)
      s.box([0.34, 0.16, 0.23], [0.5, 0.67, 0.19], P.stone, [0, 0, 0], 0.02)
      for (const y of [0.44, 0.57, 0.7]) s.box([0.39, 0.025, 0.018], [0, y, 0.174], P.timber)
    }
  }
  const model = s.finish()
  const transform = new THREE.Matrix4()
  if (pose === 'defeat') transform.makeRotationZ(Math.PI / 2).setPosition(0.4, 0.18, 0)
  else if (pose === 'hit') transform.makeRotationX(-0.16)
  else if (pose === 'rest') transform.makeScale(1.05, 0.65, 1.05)
  model.body.applyMatrix4(transform);model.light.applyMatrix4(transform)
  if(pose==='defeat'||pose==='rest')groundModel(model)
  model.body.computeBoundingSphere();if (model.light.getAttribute('position')) model.light.computeBoundingSphere()
  return model
}
