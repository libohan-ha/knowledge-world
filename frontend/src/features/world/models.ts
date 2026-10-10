import * as THREE from 'three'
import tokens from '../../../../docs/contracts/design-tokens.json'
import rules from '../../../../docs/contracts/default-rules.json'
import coreRules from '../../../../docs/contracts/system-core-rules.target.json'
import {Sculpture, facade, frontDoor, planter} from './sculpture'
import {campHall, gameModelFactory} from './game-models'
import {groundHeight, riverCenter, stableHash, terrainSurface} from './coordinates'

const P = tokens.world.scene_palette
const G = tokens.world.geometry
export type Model = {body: THREE.BufferGeometry; light: THREE.BufferGeometry}

// Program models are authored here, with ground anchors at y=0 and their
// silhouettes in true 3D. Every face receives the same local pixel material.
// The finished geometry is shared by instanced scene objects.
export function knowledgeBuilding(theme: string, variant: number, stage: number): Model {
  const s = new Sculpture(), w = G.building_footprint, h = G.building_base_height + (stage - 1) * G.building_stage_height, d = w * 0.83
  const roof = theme === 'forest' ? P.roof_forest : theme === 'valley' ? P.roof_valley : theme === 'plaza' ? P.roof_plaza : P.roof_neutral
  if (theme === 'forest' || !['valley', 'plaza'].includes(theme)) {
    if (variant === 1) {
      // A round story tower with a conical tiled roof and a low book annex.
      s.cylinder(w * 0.38, w * 0.43, h + 0.09, [0, h / 2 + 0.045, 0], P.wall, 16)
      s.cylinder(0.015, w * 0.51, 0.37 + stage * 0.03, [0, h + 0.24, 0], roof, 16)
      s.cylinder(w * 0.47, w * 0.47, 0.045, [0, h + 0.04, 0], P.timber, 16)
      frontDoor(s, [0, 0.17, w * 0.435], 0.26)
      for (const sign of [-1, 1]) s.window([sign * w * 0.405, h * 0.65, 0], [0.13, 0.18, 0.025], [0, sign * Math.PI / 2, 0])
      s.window([0, h * 0.65, -w * 0.405], [0.13, 0.18, 0.025], [0, Math.PI, 0])
      if (stage > 1) {s.box([0.3, h * 0.6, 0.27], [0.24, h * 0.3, 0.16], P.wall_shade, [0, 0, 0], 0.03);s.gable([0.24, h * 0.6, 0.16], 0.35, 0.14, 0.31, roof)}
      if (stage > 2) {s.cylinder(0.14, 0.14, 0.045, [0, h * 0.5, 0.29], P.wood, 12);planter(s, -0.33, 0.18)}
    } else {
      facade(s, variant === 2 ? w * 0.73 : w, h, variant === 2 ? d * 1.15 : d, roof, stage)
      s.gable([0, h + 0.055, 0], variant === 2 ? w * 0.86 : w + 0.12, 0.26 + stage * 0.025, d + 0.13, roof)
      if (variant === 2) {
        s.box([0.31, h * 0.7, 0.35], [0.25, h * 0.35, -0.09], P.wall_shade, [0, 0, 0], 0.03)
        s.gable([0.25, h * 0.7, -0.09], 0.39, 0.22, 0.41, roof, Math.PI / 2)
        s.window([0.425, h * 0.48, -0.09], [0.13, 0.15, 0.015], [0, Math.PI / 2, 0])
        for (const x of [-0.24, 0.04]) s.box([0.025, 0.29, 0.025], [x, 0.15, 0.43], P.wood)
        s.box([0.33, 0.025, 0.14], [-0.1, 0.3, 0.4], P.timber)
      }
    }
  } else if (theme === 'valley') {
    if (variant === 1) {
      // Polygonal observatory: a stone drum, metal dome, and telescope.
      s.cylinder(w * 0.42, w * 0.47, h, [0, h / 2, 0], P.stone, 8)
      s.add(new THREE.SphereGeometry(w * 0.49, 12, 6, 0, Math.PI * 2, 0, Math.PI / 2), roof, [0, h, 0])
      s.cylinder(w * 0.5, w * 0.5, 0.06, [0, h, 0], P.metal, 12)
      frontDoor(s, [0, 0.17, w * 0.46], 0.28)
      for (const side of [-1, 1]) s.window([side * w * 0.435, h * 0.65, 0], [0.15, 0.13, 0.02], [0, side * Math.PI / 2, 0])
      if (stage > 1) {s.box([w * 1.05, 0.07, w * 1.05], [0, 0.035, 0], P.wall_shade, [0, 0, 0], 0.03);s.cylinder(0.05, 0.065, 0.36, [0.04, h + w * 0.36, 0.12], P.metal, 8, [Math.PI / 3, 0, 0])}
      if (stage > 2) {s.cylinder(0.17, 0.18, h * 0.6, [-0.27, h * 0.3, -0.16], P.wall, 8);s.cylinder(0.005, 0.21, 0.21, [-0.27, h * 0.6 + 0.105, -0.16], roof, 8)}
    } else if (variant === 0) {
      facade(s, w * 0.88, h, d, roof, stage)
      s.gable([0, h + 0.06, 0], w + 0.08, 0.25, d + 0.13, roof)
      // Fully modelled waterwheel, visible from either bank.
      s.add(new THREE.TorusGeometry(0.205, 0.035, 5, 12), P.wood, [-0.37, 0.24, 0.02], [0, Math.PI / 2, 0])
      for (let spoke = 0; spoke < 6; spoke++) s.box([0.045, 0.41, 0.027], [-0.37, 0.24, 0.02], P.timber, [spoke * Math.PI / 6, 0, 0])
      s.cylinder(0.05, 0.05, 0.14, [-0.37, 0.24, 0.02], P.wall_shade, 8, [0, 0, Math.PI / 2])
    } else {
      facade(s, w * 0.86, h * 0.72, d, roof, stage)
      s.gable([0, h * 0.72 + 0.06, 0], w, 0.2, d + 0.12, roof)
      s.box([0.25, h + 0.08, 0.29], [-0.22, h / 2 + 0.04, -0.08], P.stone, [0, 0, 0], 0.03)
      s.gable([-0.22, h + 0.08, -0.08], 0.34, 0.27, 0.37, roof)
      s.window([-0.22, h * 0.84, 0.076], [0.1, 0.15, 0.02])
      for (let step = 0; step < 3; step++) s.box([0.24, 0.04 * (3 - step), 0.09], [0.16, 0.02 * (3 - step), d / 2 + step * 0.08], P.stone)
    }
  } else {
    if (variant === 1) {
      // An archive bell tower, high body and open belfry instead of a house.
      facade(s, w * 0.68, h + 0.14, d * 0.8, roof, 1)
      s.box([w * 0.8, 0.07, d], [0, h + 0.26, 0], P.wall_shade)
      for (const x of [-0.18, 0.18]) for (const z of [-0.16, 0.16]) s.box([0.04, 0.19, 0.04], [x, h + 0.37, z], P.timber)
      s.gable([0, h + 0.46, 0], w * 0.92, 0.21, d + 0.09, roof)
      s.cylinder(0.025, 0.085, 0.1, [0, h + 0.37, 0], P.flag, 10)
      if (stage > 1) {s.box([0.28, 0.34, d], [0.25, 0.17, 0], P.wall_shade);s.gable([0.25, 0.34, 0], 0.35, 0.13, d + 0.08, roof)}
      if (stage > 2) for (const z of [-0.3, 0.3]) planter(s, -0.31, z)
    } else if (variant === 2) {
      // Reading pavilion: deep eaves, four stone columns, raised courtyard.
      s.box([w * 1.1, 0.1, d * 1.25], [0, 0.05, 0], P.stone, [0, 0, 0], 0.03)
      s.box([w * 0.58, h * 0.85, d * 0.65], [0, h * 0.43, -0.06], P.wall, [0, 0, 0], 0.02)
      for (const x of [-w * 0.43, w * 0.43]) for (const z of [-d * 0.4, d * 0.4]) s.cylinder(0.027, 0.036, h, [x, h / 2 + 0.1, z], P.wall_shade, 8)
      s.gable([0, h + 0.1, 0], w * 1.25, 0.21, d * 1.35, roof)
      s.window([0, h * 0.55, d * 0.27], [0.24, 0.22, 0.03])
      if (stage > 1) s.gable([0, h + 0.32, -0.08], w * 0.7, 0.21, d * 0.78, roof)
      if (stage > 2) for (const x of [-0.35, 0.35]) planter(s, x, 0.37)
    } else {
      facade(s, w, h, d, roof, 1)
      s.gable([0, h + 0.07, 0], w * 1.2, 0.23, d * 1.22, roof)
      for (const x of [-0.24, 0.24]) s.cylinder(0.035, 0.04, h * 0.75, [x, h * 0.375, d * 0.6], P.wall_shade, 10)
      s.gable([0, h * 0.77, d * 0.5], w, 0.16, 0.3, P.stone)
      if (stage > 1) {s.box([0.27, h * 0.75, 0.38], [-0.27, h * 0.375, -0.08], P.wall);s.gable([-0.27, h * 0.75, -0.08], 0.35, 0.18, 0.45, roof)}
      if (stage > 2) {s.cylinder(0.04, 0.04, 0.32, [0.2, h + 0.25, -0.12], P.flag, 6);s.box([0.18, 0.12, 0.02], [0.29, h + 0.36, -0.12], P.flag)}
    }
  }
  return s.finish()
}

export function landmark(theme: string): Model {
  const s = new Sculpture()
  s.box([0.99, 0.14, 0.92], [0, 0.07, 0], P.stone, [0, 0, 0], 0.06)
  if (theme === 'forest') {
    // A tree library with a complete cylindrical stair tower and wrapping roots.
    s.cylinder(0.32, 0.4, 0.9, [0, 0.52, 0], P.wall, 16)
    s.cylinder(0.04, 0.49, 0.48, [0, 1.15, 0], P.roof_forest, 16)
    s.cylinder(0.46, 0.46, 0.08, [0, 0.93, 0], P.wood, 16)
    for (let i = 0; i < 6; i++) {const a = i * Math.PI / 3;s.window([Math.sin(a) * 0.345, 0.64, Math.cos(a) * 0.345], [0.16, 0.26, 0.025], [0, a, 0])}
    s.cylinder(0.14, 0.21, 1.07, [-0.37, 0.63, -0.08], P.trunk, 9)
    for (let i = 0; i < 5; i++) s.sphere(0.31, [-0.36 + Math.sin(i * 2.4) * 0.24, 1.2 + (i % 2) * 0.15, -0.06 + Math.cos(i * 2.4) * 0.2], P.foliage[i % P.foliage.length], [1, 0.8, 1])
  } else if (theme === 'valley') {
    // An astronomical bridge with twin stone towers, an open arch and armillary.
    for (const x of [-0.29, 0.29]) {s.box([0.26, 0.76, 0.53], [x, 0.51, 0], P.wall_shade, [0, 0, 0], 0.04);s.window([x, 0.66, 0.284], [0.13, 0.22, 0.025]);s.cylinder(0.01, 0.2, 0.32, [x, 1.05, 0], P.roof_valley, 8)}
    s.box([0.87, 0.13, 0.53], [0, 0.87, 0], P.stone, [0, 0, 0], 0.025)
    s.add(new THREE.TorusGeometry(0.24, 0.022, 6, 24), P.flag, [0, 1.2, 0], [0.3, 0.3, 0.4])
    s.add(new THREE.TorusGeometry(0.21, 0.018, 6, 24), P.flag, [0, 1.2, 0], [Math.PI / 2, 0.1, 0])
    s.sphere(0.06, [0, 1.2, 0], P.window)
    for (let i = 0; i < 4; i++) s.box([0.3, 0.035 * (4 - i), 0.09], [0, 0.02 * (4 - i), 0.25 + i * 0.08], P.stone)
  } else {
    // Archive hall: broad colonnade, central dome, side galleries and grand stairs.
    s.box([0.73, 0.65, 0.55], [0, 0.46, -0.06], P.wall, [0, 0, 0], 0.04)
    for (const x of [-0.32, -0.12, 0.12, 0.32]) {s.cylinder(0.036, 0.047, 0.65, [x, 0.465, 0.29], P.wall_shade, 10);s.cylinder(0.075, 0.075, 0.06, [x, 0.78, 0.29], P.stone, 8)}
    s.gable([0, 0.8, 0], 0.99, 0.21, 0.83, P.roof_plaza)
    s.cylinder(0.2, 0.22, 0.25, [0, 1.02, -0.13], P.wall, 12)
    s.add(new THREE.SphereGeometry(0.235, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2), P.roof_plaza, [0, 1.14, -0.13])
    for (const x of [-0.22, 0, 0.22]) s.window([x, 0.5, 0.223], [0.12, 0.25, 0.02])
    s.window([0, 0.5, -0.35], [0.27, 0.29, 0.02], [0, Math.PI, 0])
    for (let i = 0; i < 3; i++) s.box([0.71 - i * 0.1, 0.035, 0.12], [0, 0.1 - i * 0.03, 0.4 + i * 0.1], P.stone)
  }
  planter(s, -0.4, 0.38);planter(s, 0.4, 0.38)
  return s.finish()
}

export function campModel(): Model {
  return campHall(1)
}

export function treeModel(pine = false, variant = 0): Model {
  const s = new Sculpture()
  s.cylinder(0.044, 0.075, 0.48, [0, 0.24, 0], P.trunk, 7)
  if (pine) for (let layer = 0; layer < 4; layer++) s.cylinder(0, 0.3 - layer * 0.045, 0.45, [0, 0.44 + layer * 0.2, 0], P.foliage[(layer + 2) % 4], 9)
  else {
    for (let branch = 0; branch < 3; branch++) {
      const angle = branch * 2.1
      s.cylinder(0.02, 0.034, 0.38, [Math.sin(angle) * 0.065, 0.43, Math.cos(angle) * 0.065], P.trunk, 6, [0.35 * Math.sin(angle), 0, 0.35 * Math.cos(angle)])
    }
    for (let i = 0; i < 9; i++) s.sphere(variant === 1 ? 0.19 : 0.24, [Math.sin(i * 2.4 + variant) * (i ? 0.22 : 0), 0.64 + (i % 3) * (variant === 1 ? 0.19 : 0.12), Math.cos(i * 2.4 + variant) * (i ? 0.2 : 0)], P.foliage[(i + variant) % 4], [1, variant === 1 ? 1.08 : 0.8, 1])
  }
  return s.finish()
}

export function plantModel(stage: number): Model {
  const s = new Sculpture(), phase = Math.max(0, Math.min(rules.world.plant_stage_count - 1, stage))
  s.cylinder(0.095, 0.08, 0.06, [0, 0.03, 0], P.soil, 9)
  s.cylinder(0.008, 0.013, 0.1 + phase * 0.11, [0, 0.08 + phase * 0.055, 0], P.foliage[2], 6)
  for (let i = 0; i < 2 + phase * 2; i++) {const a = i * 2.4;s.sphere(0.062, [Math.sin(a) * 0.055, 0.09 + i * 0.032, Math.cos(a) * 0.055], P.foliage[i % 3], [0.5, 0.35, 1])}
  if (phase === rules.world.plant_stage_count - 1) for (let flower = 0; flower < 3; flower++) {
    const x = Math.sin(flower * 2.4) * 0.065, z = Math.cos(flower * 2.4) * 0.065, y = 0.31 - flower * 0.035
    for (let i = 0; i < 5; i++) s.sphere(0.035, [x + Math.sin(i * 1.256) * 0.039, y, z + Math.cos(i * 1.256) * 0.039], P.flower[0], [1, 0.5, 1])
    s.sphere(0.023, [x, y + 0.007, z], P.flag)
  }
  return s.finish()
}

export function lanternModel(): Model {
  const s = new Sculpture()
  s.cylinder(0.03, 0.05, 0.61, [0, 0.305, 0], P.metal, 8)
  s.box([0.15, 0.026, 0.15], [0, 0.57, 0], P.metal)
  s.add(new THREE.BoxGeometry(0.09, 0.12, 0.09), '#FFFFFF', [0, 0.655, 0], [0, 0, 0], [1, 1, 1], true)
  for (const x of [-0.06, 0.06]) for (const z of [-0.06, 0.06]) s.box([0.012, 0.15, 0.012], [x, 0.655, z], P.metal)
  s.cylinder(0.014, 0.12, 0.1, [0, 0.775, 0], P.metal, 4, [0, Math.PI / 4, 0])
  s.cylinder(0.1, 0.12, 0.06, [0, 0.03, 0], P.stone, 8)
  return s.finish()
}

export function gardenModel(): Model {
  const s = new Sculpture()
  for (const x of [-0.14, 0.14]) {s.box([0.025, 0.45, 0.025], [x, 0.225, 0], P.wood);planter(s, x, 0.03)}
  for (let r = 0; r < 5; r++) s.box([0.34, 0.018, 0.02], [0, 0.1 + r * 0.08, 0], P.timber)
  s.gable([0, 0.45, 0], 0.4, 0.07, 0.16, P.roof_forest)
  for (let i = 0; i < 5; i++) s.sphere(0.055, [Math.sin(i * 2.2) * 0.13, 0.17 + i * 0.068, 0.022], P.foliage[i % 3])
  return s.finish()
}

export function foxModel(pose: 'idle' | 'wave' | 'celebrate' | 'rest', outfit = false): Model {
  const s = new Sculpture(), rest = pose === 'rest'
  s.sphere(0.27, [0, rest ? 0.19 : 0.29, 0], P.fox, [0.78, rest ? 0.55 : 1, 0.68])
  s.sphere(0.21, [0, rest ? 0.24 : 0.61, 0.08], P.fox, [1, 0.87, 0.82])
  s.sphere(0.17, [0, rest ? 0.2 : 0.53, 0.17], P.fox_light, [0.87, 0.65, 0.5])
  for (const x of [-0.14, 0.14]) {
    s.cylinder(0, 0.08, 0.23, [x, rest ? 0.41 : 0.8, 0.025], P.fox, 3, [0.08, 0, -x * 1.1])
    s.cylinder(0, 0.037, 0.12, [x, rest ? 0.41 : 0.81, 0.07], P.fox_dark, 3, [0.12, 0, -x * 1.1])
    s.sphere(0.025, [x * 0.62, rest ? 0.255 : 0.61, 0.237], P.fox_dark, [1, rest ? 0.25 : 1.25, 0.4])
    s.sphere(0.08, [x * 0.64, 0.07, 0.09], P.fox_dark, [0.65, 0.72, 1.1])
    const raised = pose === 'celebrate' || pose === 'wave' && x > 0
    s.sphere(0.095, [x * (raised ? 1.6 : 1.1), raised ? 0.61 : 0.31, 0.035], P.fox, [0.5, 1.2, 0.65])
  }
  s.sphere(0.024, [0, rest ? 0.19 : 0.545, 0.277], P.fox_dark)
  s.sphere(0.19, [0.18, rest ? 0.13 : 0.21, -0.21], P.fox, [1.1, 0.6, 1.5])
  s.sphere(0.12, [0.24, rest ? 0.12 : 0.22, -0.4], P.fox_light, [0.95, 0.6, 1.3])
  if (outfit) {s.cylinder(0.155, 0.17, 0.055, [0, rest ? 0.19 : 0.445, 0.01], P.scarf, 10);s.box([0.075, 0.17, 0.04], [0.095, rest ? 0.15 : 0.36, 0.19], P.scarf, [0, 0, 0.15], 0.015)}
  return s.finish()
}

export function environmentGeometry(cells: {x: number; z: number; y: number; occupied: boolean}[], theme: string, seed: string | number, compact = false): Model {
  const s = new Sculpture(), lookup = new Set(cells.map(c=>`${c.x},${c.z}`)), positions: number[] = [], colors: number[] = [], uvs: number[] = []
  const grass = new THREE.Color(P.grass[0]), alternate = new THREE.Color(P.grass[1]), stone = new THREE.Color(P.stone), path = new THREE.Color(P.path)
  const height = (x:number,z:number) => compact ? groundHeight(x,z,theme,seed) : terrainSurface(x,z,theme,seed)
  const vertex = (x:number,z:number) => {
    const bank = !compact && Math.abs(x-riverCenter(z)) < G.river_width / 2 + G.river_bank_width
    const road = (Math.abs(x)<G.path_width/2 || Math.abs(z)<G.path_width/2) && !bank
    const tint = road ? path : bank ? stone : grass.clone().lerp(alternate, 0.2 + Math.sin(x*1.3+z*0.8)*0.15)
    positions.push(x,height(x,z),z);colors.push(tint.r,tint.g,tint.b);uvs.push(x,z)
  }
  for (const cell of cells) {
    const {x,z,y,occupied} = cell, hash = stableHash(`${seed}:ground:${x}:${z}`), n = G.terrain_subdivisions
    for (let ix=0;ix<n;ix++) for (let iz=0;iz<n;iz++) {
      const x0=x-0.5+ix/n,z0=z-0.5+iz/n,x1=x0+1/n,z1=z0+1/n
      vertex(x0,z0);vertex(x0,z1);vertex(x1,z0);vertex(x1,z0);vertex(x0,z1);vertex(x1,z1)
    }
    for (const [dx,dz] of [[-1,0],[1,0],[0,-1],[0,1]]) if (!lookup.has(`${x+dx},${z+dz}`)) {
      // Only the island perimeter is exposed rock; neighbouring cells share
      // the top surface instead of drawing a bevel around every grid square.
      const edge = new THREE.BufferGeometry(), a:[number,number]=dx?[x+dx/2,z-0.5]:[x-0.5,z+dz/2], b:[number,number]=dx?[x+dx/2,z+0.5]:[x+0.5,z+dz/2]
      const ay=height(...a),by=height(...b),bottom=Math.min(ay,by)-G.base_thickness
      const edgeVertices = [a[0],ay,a[1],b[0],by,b[1],a[0],bottom,a[1],a[0],bottom,a[1],b[0],by,b[1],b[0],bottom,b[1]]
      // Winding follows the exterior normal on all four sides. The earlier
      // same-order quads disappeared on half the island when viewed behind.
      if (dx < 0 || dz > 0) for (let i = 0; i < edgeVertices.length; i += 9) for (let axis = 0; axis < 3; axis++) [edgeVertices[i + 3 + axis], edgeVertices[i + 6 + axis]] = [edgeVertices[i + 6 + axis], edgeVertices[i + 3 + axis]]
      edge.setAttribute('position',new THREE.Float32BufferAttribute(edgeVertices,3))
      edge.computeVertexNormals();s.add(edge,P.cliff)
      if (!occupied&&hash%2===0) s.sphere(0.18,[x+dx*0.38,y+0.02,z+dz*0.38],P.stone,[1,0.45,0.8])
    }
    if (!occupied && hash % 3 === 0) {
      for (let i = 0; i < 3; i++) s.sphere(0.06 + i * 0.018, [x - 0.25 + i * 0.11, y + 0.067, z + 0.26], theme === 'valley' ? P.stone : P.foliage[(hash + i) % 4], [1, 0.45, 0.8])
    }
    if (!occupied && hash % 4 === 1) for (let i = 0; i < 3; i++) {
      s.cylinder(0.006, 0.008, 0.085, [x + i * 0.07 - 0.14, y + 0.068, z + 0.29], P.foliage[2], 5)
      s.sphere(0.018, [x + i * 0.07 - 0.14, y + 0.12, z + 0.29], P.flower[hash % 3])
    }
    if (!compact && !occupied) {
      const nearShore = Math.abs(x - riverCenter(z)) < 0.8
      for (let tuft = 0; tuft < G.grass_tufts_per_cell; tuft++) {
        const noise = stableHash(`${seed}:tuft:${x}:${z}:${tuft}`), tx = x + ((noise >>> 8) % 80 - 40) / 100, tz = z + ((noise >>> 18) % 80 - 40) / 100
        if (Math.abs(tx) < G.path_width || Math.abs(tz) < G.path_width || Math.abs(tx - riverCenter(tz)) < G.river_width / 2) continue
        const ty = height(tx, tz), bladeHeight = 0.07 + (noise >>> 3) % 6 / 100
        s.add(new THREE.ConeGeometry(0.017, bladeHeight, 3), P.foliage[(noise >>> 14) % 4], [tx, ty + bladeHeight / 2, tz], [0.1, noise % 6, 0.15])
        s.add(new THREE.ConeGeometry(0.011, bladeHeight * 0.8, 3), P.grass[(noise >>> 7) % 3], [tx + 0.026, ty + bladeHeight * 0.4, tz + 0.017], [-0.2, noise % 6, -0.15])
      }
      if (nearShore) for (let i = 0; i < G.shore_stones_per_cell; i++) {
        const rz = z - 0.4 + i * 0.24, rx = riverCenter(rz) + (x < riverCenter(z) ? -1 : 1) * (G.river_width / 2 + G.river_bank_width * 0.75)
        s.sphere(0.067, [rx, height(rx, rz) + 0.017, rz], i % 2 ? P.stone : P.cliff, [1.3, 0.48, 0.9])
      }
    }
  }
  const top=new THREE.BufferGeometry();top.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));top.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));top.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2));top.computeVertexNormals();s.body.push(top)
  return s.finish()
}

export function creekGeometry(cells: {x:number;z:number}[]) {
  const positions:number[]=[], points=new Set(cells.map(c=>`${c.x},${c.z}`)), zs=cells.filter(c=>Math.abs(c.x-G.river_x)<1).map(c=>c.z)
  if (zs.length) for (let z=Math.min(...zs)-0.5;z<Math.max(...zs)+0.5;z+=0.25) {
    const cx=riverCenter(z+0.125)
    if (!points.has(`${Math.round(cx)},${Math.round(z+0.125)}`)) continue
    const half=G.river_width/2, x0=riverCenter(z),x1=riverCenter(z+0.25),y=G.river_level
    positions.push(x0-half,y,z,x0+half,y,z,x1-half,y,z+0.25,x1-half,y,z+0.25,x0+half,y,z,x1+half,y,z+0.25)
  }
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));geometry.computeVertexNormals();return geometry
}

export function bridgeModel(): Model {
  const s = new Sculpture()
  // Solid planks, side rails and piers, including an inspectable underside.
  for (let i = 0; i < 9; i++) {const x = (i - 4) * 0.084, h = 0.07 + Math.sin(i / 8 * Math.PI) * 0.045;s.box([0.083, 0.055, 0.42], [x, h, 0], i % 2 ? P.wood : P.path, [0, 0, 0], 0.005)}
  for (const z of [-0.23, 0.23]) {
    s.box([0.83, 0.035, 0.035], [0, 0.3, z], P.timber, [0, 0, 0], 0.01)
    for (const x of [-0.37, 0, 0.37]) {s.box([0.042, 0.26, 0.042], [x, 0.19, z], P.wood);s.sphere(0.034, [x, 0.335, z], P.flag)}
    for (const x of [-0.3, 0.3]) s.box([0.08, 0.19, 0.075], [x, -0.015, z], P.stone)
  }
  return s.finish()
}

export function disposeModel(model: Model) {model.body.dispose();model.light.dispose()}

export function pixelTexture(): THREE.DataTexture {
  const size = tokens.world.texels_per_world_unit, data = new Uint8Array(size * size * 4)
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const index = (y * size + x) * 4, noise = ((x * 73 + y * 37 + (x ^ y) * 17) % G.texture_pixel_levels)
    data[index] = data[index + 1] = data[index + 2] = 255 - noise * 2;data[index + 3] = 255
  }
  const texture = new THREE.DataTexture(data, size, size)
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping
  texture.magFilter = THREE.NearestFilter;texture.minFilter = THREE.NearestMipmapNearestFilter
  texture.generateMipmaps = true;texture.colorSpace = THREE.SRGBColorSpace;texture.needsUpdate = true
  return texture
}

export function createModelLibrary(activeTheme='forest') {
  const models = new Map<string, Model>()
  const factories = new Map<string, () => Model>()
  for (const theme of [activeTheme]) {
    for (let variant = 0; variant < tokens.world.assets.building_variants_per_theme; variant++)
      for (let stage = 1; stage <= coreRules.home.max_building_level; stage++) factories.set(`building:${theme}:${variant}:${stage}`, () => knowledgeBuilding(theme, variant, stage))
    factories.set(`landmark:${theme}`, () => landmark(theme))
  }
  factories.set('camp', campModel);factories.set('tree', () => treeModel());factories.set('tree:1', () => treeModel(false, 1));factories.set('pine', () => treeModel(true));factories.set('lamp', lanternModel);factories.set('decor:lantern', lanternModel);factories.set('garden', gardenModel);factories.set('bridge', bridgeModel)
  for (let stage = 0; stage < rules.world.plant_stage_count; stage++) factories.set(`plant:${stage}`, () => plantModel(stage))
  for (const pose of ['idle', 'wave', 'celebrate', 'rest'] as const) for (const outfit of [false, true]) factories.set(`fox:${pose}:${outfit}`, () => foxModel(pose, outfit))
  // Geometry is compiled only for models actually shown, including the new
  // units. A closed roster card does not allocate every pose and growth stage.
  return {models: {
    has: (key: string) => factories.has(key) || !!gameModelFactory(key),
    get: (key: string) => {
      if (!models.has(key)) {const factory = factories.get(key) || gameModelFactory(key);if (factory) models.set(key, factory())}
      return models.get(key)
    },
  }, dispose: () => {models.forEach(disposeModel);models.clear()}}
}
