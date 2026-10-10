import type {RecordView} from '../../shared/api/client'
import {knownStage, type Stage} from './coordinates'
import tokens from '../../../../docs/contracts/design-tokens.json'

// Render-only legacy state for preserved models. The retired API is not called.
export type PresentationState = {current_stage: Stage|null; best_stage: Stage|null; landmark_present: boolean|null}
export type GrowthEvent = {
  id: string; event_key: string; kind: 'learning' | 'chapter_landmark'; point_id: string | null;
  plot_id?: string | null; region_id?: string | null; chapter_id?: string | null;
  occurred_at: string; ledger_id: string | null; learning_business_date?: string | null;
  before: PresentationState; after: PresentationState; is_correction: boolean | null;
  source?: {kind: string; id: string; activity_id?: string | null} | null; coverage: 'complete' | 'partial'; missing_fields: string[];
}
export type ActiveSequence = {event: GrowthEvent; startedAt: number; duration: number; replay: boolean}
const emptyState: PresentationState = {current_stage: null, best_stage: null, landmark_present: null}

// Recent events keep their original API fields. Never infer missing historic
// best_stage from current_stage, or infer a reward from a wallet difference.
export function recentGrowthEvent(row: RecordView): GrowthEvent | null {
  if (row.kind !== 'learning' && row.kind !== 'chapter_landmark') return null
  const payload = row.payload || {}, presentation = payload.presentation
  const state = (value: Record<string,unknown> | undefined): PresentationState => ({current_stage:knownStage(value?.current_stage),best_stage:knownStage(value?.best_stage),landmark_present:typeof value?.landmark_present==='boolean'?value.landmark_present:null})
  const before = presentation ? state(presentation.before) : {...emptyState, current_stage: knownStage(payload.before_stage)}
  const after = presentation ? state(presentation.after) : {...emptyState, current_stage: knownStage(payload.stage), best_stage: knownStage(payload.best_stage)}
  const missing_fields:string[]=[]
  if(presentation?.version!==1)missing_fields.push('presentation.version')
  if(typeof presentation?.is_correction!=='boolean')missing_fields.push('is_correction')
  for(const [name,value] of [['before',before],['after',after]] as const) {
    if(row.kind==='chapter_landmark'){if(value.landmark_present===null)missing_fields.push(`${name}.landmark_present`)}
    else {if(!value.current_stage)missing_fields.push(`${name}.current_stage`);if(!value.best_stage)missing_fields.push(`${name}.best_stage`)}
  }
  return {
    id: row.id, event_key: row.event_key, kind: row.kind, point_id: row.point_id || null,
    occurred_at: row.created_at, ledger_id: row.ledger_id || null,
    before, after, is_correction: presentation?.is_correction ?? null,
    coverage: missing_fields.length ? 'partial' : 'complete', missing_fields,
    source: row.kind === 'chapter_landmark' && payload.achievement_id ? {kind: 'achievement', id: payload.achievement_id} : null,
    chapter_id: payload.chapter_id || null,
  }
}

export function presentationKey(event: GrowthEvent) {
  // A stable event key identifies a distinct authoritative revision. Receipt ID
  // alone would hide a real correction without a coin change.
  return event.event_key || event.id
}

export function unseenEvents(events: GrowthEvent[], seen: ReadonlySet<string>) {
  const unique = new Map<string, GrowthEvent>()
  for (const event of events) if (!seen.has(presentationKey(event))) unique.set(presentationKey(event), event)
  return [...unique.values()].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at) || a.id.localeCompare(b.id))
}

export function sequenceDuration(event: GrowthEvent) {
  if (event.is_correction) return tokens.motion_ms.world_growth
  if (event.kind === 'chapter_landmark') return tokens.motion_ms.landmark_reveal
  return event.before.best_stage && event.before.best_stage !== event.after.best_stage ? tokens.motion_ms.building_growth : tokens.motion_ms.fog_reveal
}

export function sequenceCue(sequence: ActiveSequence, elapsed: number) {
  if (sequence.event.is_correction) return '更正记录已生效'
  if (sequence.event.kind !== 'chapter_landmark') return elapsed < tokens.motion_ms.world_growth ? '这份理解，正在成为小镇的一部分' : '成长已保存'
  const cues = tokens.world.presentation.landmark_cues_ms
  if (elapsed >= cues.receipt) return '这一章节，留下了一座地标'
  if (elapsed >= cues.companion) return '苔苔也为你高兴'
  if (elapsed >= cues.lights) return '为新的地标，亮起灯'
  if (elapsed >= cues.build) return '把这份积累，建成看得见的模样'
  if (elapsed >= cues.fog) return '薄雾正在散开'
  return '让我们看看这片成长'
}
