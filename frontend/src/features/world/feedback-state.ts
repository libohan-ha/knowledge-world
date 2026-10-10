import tokens from '../../../../docs/contracts/design-tokens.json'
import type {SceneEffectKind, SceneObject} from './scene-types'

/** A display projection of an authoritative event, never a transport contract. */
export type VisualEvent = {
  id: string
  order: number
  kind: SceneEffectKind
  title: string
  description: string
  occurredAt: string
  source: {label: string; id: string; href?: string}
  ledgerIds: string[]
  tone: 'positive' | 'negative' | 'neutral' | 'correction'
  changes: {label: string; before?: string; after: string}[]
  economics?: {label: string; value: number; unit?: string}[]
  targetId?: string
  theme?: string
  beforeObjects?: SceneObject[] | null
  afterObjects?: SceneObject[] | null
  missing?: string[]
}

export type FeedbackBookmark = {watermark: number; ids: string[]}
export const emptyBookmark = (): FeedbackBookmark => ({watermark: 0, ids: []})
export function readBookmark(value: string | null): FeedbackBookmark {
  try {
    const raw = JSON.parse(value || '{}')
    if (!Number.isSafeInteger(raw.watermark) || raw.watermark < 0 || !Array.isArray(raw.ids)) return emptyBookmark()
    return {watermark: raw.watermark, ids: raw.ids.filter((id: unknown) => typeof id === 'string').slice(-tokens.world.presentation.seen_event_limit)}
  } catch {return emptyBookmark()}
}

/** Recovery only offers the newest bounded set. Live batches stay ordered.
 * A bookmark is a display acknowledgement, never a game settlement. */
export class FeedbackQueue {
  bookmark: FeedbackBookmark
  pending: VisualEvent[] = []
  initialized = false
  constructor(bookmark = emptyBookmark()) {this.bookmark = bookmark}
  ingest(events: readonly VisualEvent[]) {
    const returning = !this.initialized
    this.initialized = true
    const unique = new Map(events.filter(e => e.id && e.source.id && Number.isSafeInteger(e.order) && e.order > this.bookmark.watermark && !this.bookmark.ids.includes(e.id)).map(e => [e.id, e]))
    let fresh = [...unique.values()].sort((a, b) => a.order - b.order || a.id.localeCompare(b.id))
    if (!fresh.length) return
    if (returning) {
      const keep = tokens.world.presentation.max_auto_replay_on_return, skipped = fresh.slice(0, Math.max(0, fresh.length - keep))
      for (const event of skipped) this.consume(event)
      fresh = fresh.slice(-keep)
    }
    const queued = new Set(this.pending.map(e => e.id))
    this.pending.push(...fresh.filter(e => !queued.has(e.id)))
    this.pending.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id))
  }
  consume(event: VisualEvent) {
    this.bookmark = {watermark: Math.max(this.bookmark.watermark, event.order), ids: [...this.bookmark.ids.filter(id => id !== event.id), event.id].slice(-tokens.world.presentation.seen_event_limit)}
  }
  take(): VisualEvent | undefined {
    const event = this.pending.shift()
    if (event) this.consume(event)
    return event
  }
  mergeBookmark(bookmark: FeedbackBookmark) {
    this.bookmark = {watermark: Math.max(bookmark.watermark, this.bookmark.watermark), ids: [...new Set([...this.bookmark.ids, ...bookmark.ids])].slice(-tokens.world.presentation.seen_event_limit)}
    this.pending = this.pending.filter(e => e.order > this.bookmark.watermark && !this.bookmark.ids.includes(e.id))
  }
}
