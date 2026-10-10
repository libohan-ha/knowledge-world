/** View-only scene inputs, not transport DTOs. Containers map generated API
 * types to these display values; the renderer never decides ownership/results. */
export type SceneObject = {
  id: string
  model: string
  x: number
  z: number
  title: string
  subtitle?: string
  rotation?: number
  scale?: number
  elevation?: number
  /** Authoritative occupied width, used only to leave scenery clear. */
  footprint?: number
  state?: 'owned' | 'available' | 'locked'
  motion?: 'unit' | 'tree'
  selectable?: boolean
}

export type SceneEffectKind = 'system' | 'penalty' | 'checkin' | 'wager' | 'reward' | 'leisure' | 'summon' | 'training' | 'battle' | 'occupation' | 'home' | 'history'

/** All sequence state is expendable. Only a successful receipt/event may start
 * one. Changing/finishing a sequence must never submit a game command. */
export type SceneSequence = {
  id: string
  kind: SceneEffectKind
  targetId?: string
  startedAt: number
  duration: number
  beforeModel?: string | null
  afterModel?: string | null
  correction?: boolean
  replay?: boolean
}

export type CameraTarget = {x: number; z: number}

export type SceneBattleAction = {
  id: string
  actorId: string
  targetId: string
  effect: 'physical' | 'magic' | 'heal' | 'shield' | 'dodge'
  startedAt: number
  duration: number
  frozenProgress?: number
}
