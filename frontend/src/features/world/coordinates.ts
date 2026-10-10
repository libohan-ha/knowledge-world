import tokens from '../../../../docs/contracts/design-tokens.json'

export type LegacyViewport = {x: number; y: number; zoom: number}
export type WorldFocus = {x: number; z: number; zoom: number}
const unit = tokens.world.world_units_per_grid_cell
const halfWidth = tokens.world.tile_art_width_px / 2
const halfHeight = tokens.world.tile_art_height_px / 2
// The original SVG projected (0,0) to (500,280), then scaled around
// (500,340), then translated by viewport x/y. Preserve that order.
const originToScaleCenter = 60
const finite = (value: number | undefined, fallback = 0) => Number.isFinite(value) ? value! : fallback
const safeZoom = (zoom: number) => Number.isFinite(zoom) && zoom > 0 ? Math.max(tokens.world.camera.min_zoom, Math.min(tokens.world.camera.max_zoom, zoom)) : tokens.world.camera.default_zoom

export function legacyViewportToFocus(view: LegacyViewport): WorldFocus {
  const zoom = safeZoom(view.zoom), difference = -finite(view.x) / zoom / halfWidth
  const sum = (originToScaleCenter - finite(view.y,originToScaleCenter*zoom) / zoom) / halfHeight
  return {x: (sum + difference) / 2 * unit, z: (sum - difference) / 2 * unit, zoom}
}

export function focusToLegacyViewport(focus: WorldFocus): LegacyViewport {
  const x=finite(focus.x),z=finite(focus.z),zoom=safeZoom(focus.zoom)
  return {
    x: -(x - z) / unit * halfWidth * zoom,
    y: (originToScaleCenter - (x + z) / unit * halfHeight) * zoom,
    zoom,
  }
}

export function placementToWorld(placement: {x?: number; y?: number}) {
  const difference = finite(placement.x) / halfWidth
  const sum = finite(placement.y) / halfHeight
  return {x: (sum + difference) / 2 * unit, z: (sum - difference) / 2 * unit}
}

export function worldToPlacement(position: {x: number; z: number}) {
  return {x: (finite(position.x) - finite(position.z)) / unit * halfWidth, y: (finite(position.x) + finite(position.z)) / unit * halfHeight}
}

export function stableHash(value: string) {
  let hash = 2166136261
  for (let i = 0; i < value.length; i++) hash = Math.imul(hash ^ value.charCodeAt(i), 16777619)
  return hash >>> 0
}

export function buildingVariant(pointId: string, seed: number | string) {
  return stableHash(`${seed}:${pointId}`) % tokens.world.assets.building_variants_per_theme
}

/** All new region names share the existing palette, geometry and light rigs. */
export function visualTheme(theme?: string) {
  if (theme === 'mist_forest' || theme === 'forest') return 'forest'
  if (theme === 'frost_ridge' || theme === 'valley') return 'valley'
  if (theme === 'ancient_ruins' || theme === 'plaza') return 'plaza'
  return 'neutral'
}

export const stageOrder = {unseen: 0, exploring: 1, understood: 2, applicable: 3, consolidated: 4} as const
export type Stage = keyof typeof stageOrder
export const stages = Object.keys(stageOrder) as Stage[]
export function knownStage(value: unknown): Stage | null {
  if (typeof value === 'number') return stages[value] || null
  return typeof value === 'string' && Object.hasOwn(stageOrder,value) ? value as Stage : null
}

export function groundHeight(x: number, z: number, theme: string, seed: number | string) {
  const phase = stableHash(String(seed)) % 100 / 10
  const hill = theme === 'valley' ? Math.max(0, Math.abs(x) - 1) * 0.035 : 0
  const height = Math.sin(x * 0.65 + phase) * 0.035 + Math.cos(z * 0.7 + phase) * 0.025 + hill
  // Continuous slopes meet at shared vertices. The river banks remain above
  // water, and integer plot anchors never sit inside the channel.
  return Math.abs(x - riverCenter(z)) < 0.8 ? Math.max(height, 0.025) : height
}

export function riverCenter(z: number) {
  return tokens.world.geometry.river_x + Math.sin(z * 0.72) * tokens.world.geometry.river_meander
}

export function terrainSurface(x: number, z: number, theme: string, seed: number | string) {
  const g = tokens.world.geometry, distance = Math.abs(x - riverCenter(z)) - g.river_width / 2
  const blend = Math.max(0, Math.min(1, distance / g.river_bank_width))
  return (g.river_level - 0.025) * (1 - blend) + groundHeight(x,z,theme,seed) * blend
}
