import tokens from '../../../../docs/contracts/design-tokens.json'
import type {SceneEffectKind, SceneSequence} from './scene-types'

const clamp = (n: number) => Math.max(0, Math.min(1, n))
export function effectDuration(kind: SceneEffectKind) {
  const m = tokens.motion_ms
  return ({system: m.system_result, penalty: m.system_result, checkin: m.checkin, wager: m.wager_result, reward: m.reward_reveal, leisure: m.leisure_enter, summon: m.summon, training: m.training, battle: m.battle_action, occupation: m.occupation, home: m.home_growth, history: m.history_transition})[kind]
}

export function sequenceFrame(sequence: SceneSequence, now: number, reduced = false) {
  const elapsed = Math.max(0, now - sequence.startedAt), progress = reduced ? 1 : clamp(elapsed / Math.max(1, sequence.duration))
  const major = sequence.kind === 'occupation', cues = tokens.world.presentation.landmark_cues_ms
  const buildStart = major ? cues.build : sequence.kind === 'summon' ? sequence.duration * 0.28 : 0
  const buildEnd = major ? cues.lights : sequence.duration * 0.72
  const build = reduced || sequence.correction ? 1 : clamp((elapsed - buildStart) / Math.max(1, buildEnd - buildStart))
  return {
    elapsed, progress, build, easedBuild: 1 - (1 - build) ** 3,
    fog: reduced || sequence.correction ? 0 : 1 - clamp((elapsed - (major ? cues.fog : 0)) / tokens.motion_ms.fog_reveal),
    lights: reduced || sequence.correction || elapsed >= (major ? cues.lights : buildEnd),
    companion: reduced || sequence.correction || elapsed >= (major ? cues.companion : sequence.duration * 0.75),
    receipt: reduced || sequence.correction || elapsed >= (major ? cues.receipt : sequence.duration * 0.82),
    finished: progress >= 1,
  }
}

export function sceneCue(sequence: SceneSequence, now: number, reduced = false) {
  if (sequence.correction) return '已按正式记录更正'
  const frame = sequenceFrame(sequence, now, reduced)
  if (sequence.kind === 'occupation') {
    const cues = tokens.world.presentation.landmark_cues_ms
    if (frame.receipt) return '这一片土地，记住了你的足迹'
    if (frame.companion) return '伙伴正在迎接你'
    if (frame.lights) return '旗帜升起，灯火点亮'
    if (frame.elapsed >= cues.build) return '新的地标正在落成'
    if (frame.elapsed >= cues.fog) return '前方的薄雾散开了'
    return '把目光交给这片新的领地'
  }
  return ({system: '系统回执已保存', penalty: '积分变化已有记录', checkin: '今天的第一份约定，完成了', wager: '约定有了正式结果', reward: '这份奖励，属于你了', leisure: '灯已经亮好，安心歇一会儿', summon: frame.build < 1 ? '新的伙伴，正在回应召唤' : '很高兴与你同行', training: frame.build < 1 ? '一点积累，成为新的力量' : '成长已留在身上', battle: '按保存的战报重现这一刻', occupation: '', home: frame.build < 1 ? '让这里，更像你的家' : '新的模样，已经留下', history: '回看这一次真实的变化'})[sequence.kind]
}
