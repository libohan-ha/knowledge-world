import type {components} from '../../shared/api/schema'
import tokens from '../../../../docs/contracts/design-tokens.json'
import type {Battle} from './game-view'
import {skillLabels, unitObject} from './game-view'
import type {SceneObject, SceneBattleAction} from './scene-types'
import type {UnitPose} from './game-models'

export type CombatState = components['schemas']['CombatState']
export type BattleEvent = components['schemas']['BattleEvent']
const equal=(a:CombatState|undefined,b:CombatState|undefined)=>!!a&&!!b&&a.hp===b.hp&&a.mp===b.mp&&a.shield===b.shield
const valid=(state:CombatState|undefined)=>!!state&&[state.hp,state.mp,state.shield].every(n=>Number.isFinite(n)&&n>=0)
export function initialBattleStates(battle:Battle):Record<string,CombatState> {
  return Object.fromEntries([...battle.snapshot.allies,...battle.snapshot.enemies].map(unit=>[unit.id,{hp:unit.stats.hp,mp:unit.stats.mp,shield:0}]))
}

/** Check the saved trajectory for missing records. This never recalculates
 * combat, RNG, damage, recovery, rewards or ownership. */
export function validatePlayback(battle:Battle):string|null {
  if(!battle.result)return '战报仍在生成，结果尚未就绪。'
  const states=initialBattleStates(battle)
  for(const [index,event] of battle.result.events.entries()) {
    if(event.sequence!==index+1)return '动作序号不连续，完整回放尚未就绪。'
    if(!states[event.actor_id]||!states[event.target_id])return '动作中的单位快照缺失，完整回放尚未就绪。'
    if(![event.actor_before,event.actor_after,event.target_before,event.target_after].every(valid))return '动作状态不完整，完整回放尚未就绪。'
    if(!equal(states[event.actor_id],event.actor_before)||!equal(states[event.target_id],event.target_before))return '动作前后态存在缺口，完整回放尚未就绪。'
    states[event.actor_id]={...event.actor_after};states[event.target_id]={...event.target_after}
  }
  for(const id of Object.keys(states))if(!valid(battle.result.final_states[id])||!equal(states[id],battle.result.final_states[id]))return '最终状态与动作记录尚未对应，完整回放尚未就绪。'
  return null
}

export function battleStatesAt(battle:Battle,completed:number):Record<string,CombatState> {
  const events=battle.result?.events||[],count=Math.max(0,Math.min(events.length,Math.floor(completed)))
  if(battle.result&&count===events.length)return Object.fromEntries(Object.entries(battle.result.final_states).map(([id,state])=>[id,{...state}]))
  const states=initialBattleStates(battle)
  for(const event of events.slice(0,count)){states[event.actor_id]={...event.actor_after};states[event.target_id]={...event.target_after}}
  return states
}

export function battleEffect(event:BattleEvent):SceneBattleAction['effect'] {
  return event.dodged?'dodge':event.effect==='heal'?'heal':event.effect==='shield'?'shield':event.damage_type==='magic'?'magic':'physical'
}
export function battleObjects(battle:Battle,completed:number,active:BattleEvent|undefined,progress:number,reduced=false):SceneObject[] {
  const states=battleStatesAt(battle,completed), G=tokens.world.geometry
  return [battle.snapshot.allies,battle.snapshot.enemies].flatMap((team,side)=>team.map((unit,index)=>{
    let pose:UnitPose=states[unit.id]?.hp===0?'defeat':'idle'
    if(!reduced&&pose!=='defeat'&&active) {
      if(unit.id===active.actor_id)pose=active.action==='attack'?'attack':'cast'
      else if(unit.id===active.target_id&&progress>=tokens.world.presentation.battle_impact_ratio&&active.damage>0)pose='hit'
    }
    if(battle.result&&!active&&completed===battle.result.events.length&&states[unit.id]?.hp>0&&battle.result.outcome===(side===0?'won':'lost'))pose='victory'
    return unitObject(unit,(side===0?-1:1)*G.battle_team_distance/2,(index-(team.length-1)/2)*G.battle_spacing,pose,side===0?90:-90)
  }).filter((unit):unit is SceneObject=>!!unit))
}

export function battleEventText(event:BattleEvent,battle:Battle) {
  const units=[...battle.snapshot.allies,...battle.snapshot.enemies],actor=units.find(u=>u.id===event.actor_id)?.name||'未记录的单位',target=units.find(u=>u.id===event.target_id)?.name||'未记录的目标',action=skillLabels[event.action]||skillLabels[event.effect]||event.action
  const result=event.dodged?'被闪避':event.healing?`恢复 ${event.healing} 生命`:event.shield_gain?`获得 ${event.shield_gain} 护盾`:`造成 ${event.damage} ${event.damage_type==='magic'?'法术':'物理'}伤害${event.absorbed?`，护盾吸收 ${event.absorbed}`:''}${event.died?'，目标倒下':''}`
  return `${actor} → ${target} · ${action} · ${result}`
}
