import * as THREE from 'three'
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js'
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js'
import tokens from '../../../../docs/contracts/design-tokens.json'
import type {Model} from './models'
const P = tokens.world.scene_palette
type V3 = [number, number, number]

/** Keep a fallen body's actual lowest vertex on the ground after rotating it. */
export function groundModel(model: Model) {
  model.body.computeBoundingBox()
  const bottom=model.body.boundingBox?.min.y
  if(bottom!==undefined&&Number.isFinite(bottom)) {
    model.body.translate(0,-bottom,0)
    if(model.light.getAttribute('position'))model.light.translate(0,-bottom,0)
  }
  model.body.computeBoundingSphere()
  if(model.light.getAttribute('position'))model.light.computeBoundingSphere()
  return model
}

export function beam(s: Sculpture, a: V3, b: V3, radius: number, color: string) {
  const from = new THREE.Vector3(...a), to = new THREE.Vector3(...b), direction = to.clone().sub(from)
  const rotation = new THREE.Euler().setFromQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.clone().normalize()))
  s.cylinder(radius, radius, direction.length(), from.add(to).multiplyScalar(0.5).toArray() as V3, color, 7, [rotation.x, rotation.y, rotation.z])
}

export class Sculpture {
  body: THREE.BufferGeometry[] = []
  lights: THREE.BufferGeometry[] = []
  add(geometry: THREE.BufferGeometry, color: string, at: V3 = [0, 0, 0], rotation: V3 = [0, 0, 0], scale: V3 = [1, 1, 1], light = false) {
    const shape = geometry.index ? geometry.toNonIndexed() : geometry
    if (geometry !== shape) geometry.dispose()
    const matrix = new THREE.Matrix4().compose(new THREE.Vector3(...at), new THREE.Quaternion().setFromEuler(new THREE.Euler(...rotation)), new THREE.Vector3(...scale))
    shape.applyMatrix4(matrix)
    const colors = new Float32Array(shape.getAttribute('position').count * 3), shade = new THREE.Color(color)
    for (let i = 0; i < colors.length; i += 3) {colors[i] = shade.r; colors[i + 1] = shade.g; colors[i + 2] = shade.b}
    shape.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    if (!shape.getAttribute('normal')) shape.computeVertexNormals()
    const positions = shape.getAttribute('position'), normals = shape.getAttribute('normal'), uv = new Float32Array(positions.count * 2)
    for (let i = 0; i < positions.count; i++) {
      const nx = Math.abs(normals.getX(i)), ny = Math.abs(normals.getY(i)), nz = Math.abs(normals.getZ(i))
      uv[i * 2] = nx > ny && nx > nz ? positions.getZ(i) : positions.getX(i)
      uv[i * 2 + 1] = ny > nx && ny > nz ? positions.getZ(i) : positions.getY(i)
    }
    shape.setAttribute('uv', new THREE.BufferAttribute(uv,2))
    // Different primitive constructors may attach unused tangent attributes.
    for (const name of Object.keys(shape.attributes)) if (!['position', 'normal', 'color', 'uv'].includes(name)) shape.deleteAttribute(name)
    ;(light ? this.lights : this.body).push(shape)
  }
  box(size: V3, at: V3, color: string, rotation: V3 = [0, 0, 0], bevel = 0) {
    this.add(bevel ? new RoundedBoxGeometry(...size, 1, Math.min(bevel, ...size.map(v => v / 3))) : new THREE.BoxGeometry(...size), color, at, rotation)
  }
  cylinder(top: number, bottom: number, height: number, at: V3, color: string, sides = 12, rotation: V3 = [0, 0, 0]) {
    this.add(new THREE.CylinderGeometry(top, bottom, height, sides), color, at, rotation)
  }
  sphere(radius: number, at: V3, color: string, scale: V3 = [1, 1, 1]) {
    this.add(new THREE.IcosahedronGeometry(radius, 1), color, at, [0, 0, 0], scale)
  }
  window(at: V3, size: V3, rotation: V3 = [0, 0, 0]) {
    this.box([size[0] + 0.035, size[1] + 0.035, size[2] + 0.02], at, P.window_frame, rotation)
    const outward = new THREE.Vector3(0, 0, 0.015).applyEuler(new THREE.Euler(...rotation))
    this.add(new THREE.BoxGeometry(...size), '#FFFFFF', [at[0] + outward.x, at[1], at[2] + outward.z], rotation, [1, 1, 1], true)
    this.box([0.014, size[1], size[2] + 0.04], at, P.window_frame, rotation)
    this.box([size[0], 0.014, size[2] + 0.04], at, P.window_frame, rotation)
  }
  gable(at: V3, width: number, rise: number, depth: number, color: string, angle = 0) {
    const roof = new THREE.BufferGeometry()
    const w = width / 2, d = depth / 2
    roof.setAttribute('position', new THREE.Float32BufferAttribute([-w,0,d,w,0,d,0,rise,d,-w,0,-d,0,rise,-d,w,0,-d,-w,0,d,0,rise,d,0,rise,-d,-w,0,d,0,rise,-d,-w,0,-d,w,0,d,w,0,-d,0,rise,-d,w,0,d,0,rise,-d,0,rise,d,-w,0,d,-w,0,-d,w,0,-d,-w,0,d,w,0,-d,w,0,d], 3))
    const pos = roof.getAttribute('position'), uvs = new Float32Array(pos.count * 2)
    for (let i = 0; i < pos.count; i++) {uvs[i * 2] = pos.getX(i) + pos.getY(i); uvs[i * 2 + 1] = pos.getZ(i)}
    roof.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));roof.computeVertexNormals()
    this.add(roof, color, at, [0, angle, 0])
    const slope = Math.atan2(rise, w), length = Math.hypot(w, rise)
    for (const sign of [-1, 1]) {
      const offset = new THREE.Vector3(sign * w / 2, rise / 2 + 0.012, 0).applyAxisAngle(new THREE.Vector3(0, 1, 0), angle)
      this.box([length + 0.025, 0.03, depth + 0.04], [at[0] + offset.x, at[1] + offset.y, at[2] + offset.z], color, [0, angle, -sign * slope], 0.008)
    }
    this.box([0.05, 0.04, depth + 0.075], [at[0], at[1] + rise + 0.015, at[2]], P.wall_shade, [0, angle, 0], 0.01)
  }
  finish(): Model {
    const join = (parts: THREE.BufferGeometry[]) => {
      if (!parts.length) return new THREE.BufferGeometry()
      const merged = mergeGeometries(parts, false)!
      parts.forEach(g => g.dispose());merged.computeBoundingSphere();return merged
    }
    return {body: join(this.body), light: join(this.lights)}
  }
}

export function planter(s: Sculpture, x: number, z: number, color = P.foliage[1]) {
  s.cylinder(0.052, 0.035, 0.09, [x, 0.045, z], P.wood, 8)
  s.sphere(0.065, [x, 0.14, z], color, [1, 0.75, 1])
  s.sphere(0.025, [x, 0.19, z], P.flower[0])
}
export function frontDoor(s: Sculpture, at: V3, height: number) {
  s.box([0.135, height, 0.04], at, P.timber, [0, 0, 0], 0.025)
  s.box([0.03, 0.018, 0.025], [at[0] + 0.033, at[1] - 0.008, at[2] + 0.032], P.flag)
  s.box([0.23, 0.045, 0.13], [at[0], 0.025, at[2] + 0.02], P.stone, [0, 0, 0], 0.015)
}
export function facade(s: Sculpture, width: number, height: number, depth: number, roof: string, stage: number) {
  const front = depth / 2 + 0.019
  s.box([width + 0.055, 0.08, depth + 0.04], [0, 0.04, 0], P.stone, [0, 0, 0], 0.02)
  s.box([width, height, depth], [0, height / 2 + 0.055, 0], P.wall, [0, 0, 0], 0.025)
  frontDoor(s, [0, 0.19, front], 0.26)
  for (const sign of [-1, 1]) {
    s.window([sign * width * 0.32, height * 0.64, front], [0.11, 0.16, 0.022])
    s.window([sign * (width / 2 + 0.015), height * 0.65, -0.05], [0.14, 0.17, 0.022], [0, sign * Math.PI / 2, 0])
    s.box([0.035, height, 0.035], [sign * (width / 2 - 0.01), height / 2 + 0.06, front], P.timber)
    planter(s, sign * (width / 2 + 0.045), depth / 2 - 0.08)
  }
  s.window([0, height * 0.6, -depth / 2 - 0.018], [0.19, 0.17, 0.018], [0, Math.PI, 0])
  s.box([width + 0.03, 0.045, depth + 0.03], [0, height * 0.58, 0], P.wood)
  if (stage > 1) {
    s.box([width * 0.78, 0.045, 0.2], [0, height * 0.1, front + 0.1], P.wood)
    for (const x of [-0.2, 0.2]) s.box([0.035, height * 0.6, 0.035], [x, height * 0.33, front + 0.17], P.timber)
    s.gable([0, height * 0.63, front + 0.08], width * 0.87, 0.12, 0.28, roof)
  }
  if (stage > 2) {
    // Dormer and chimney add a third-stage silhouette, front and back.
    s.box([0.17, 0.16, 0.18], [0.1, height + 0.18, 0.15], P.wall)
    s.gable([0.1, height + 0.26, 0.15], 0.23, 0.1, 0.23, roof)
    s.window([0.1, height + 0.17, 0.25], [0.085, 0.09, 0.015])
    s.box([0.09, 0.29, 0.1], [-0.17, height + 0.22, -0.13], P.stone)
    s.box([0.13, 0.045, 0.14], [-0.17, height + 0.37, -0.13], P.wall_shade)
  }
}
