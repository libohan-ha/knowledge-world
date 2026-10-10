import {useEffect, useMemo, useRef, useState} from 'react'
import {Link} from 'react-router-dom'
import {ChevronsLeft, ChevronsRight, Pause, Play, RotateCcw, Shield, Swords, Trophy} from 'lucide-react'
import tokens from '../../../../docs/contracts/design-tokens.json'
import type {Battle, Unit} from './game-view'
import {outpostObject} from './game-view'
import {battleEffect, battleEventText, battleObjects, battleStatesAt, validatePlayback, type CombatState} from './battle-timeline'
import {WorldMap} from './WorldMap'
import type {SceneBattleAction} from './scene-types'
import {usePresentationPreferences} from './presentation-preferences'
import './game-ui.css'

function UnitMeter({unit,state,active}:{unit:Unit;state:CombatState|undefined;active:boolean}) {
  if(!state)return <article className="battle-unit"><strong>{unit.name}</strong><small>这一刻的状态尚未记录</small></article>
  return <article className={`battle-unit ${active?'is-active':''} ${state.hp===0?'is-down':''}`} data-unit-id={unit.id} data-hp={state.hp}>
    <div><strong>{unit.name}</strong><small>阵位 {(unit.position??0)+1}</small></div>
    <div className="battle-hp" role="meter" aria-label={`${unit.name}生命`} aria-valuemin={0} aria-valuemax={unit.stats.hp} aria-valuenow={state.hp}><i style={{width:`${Math.max(0,Math.min(100,state.hp/Math.max(1,unit.stats.hp)*100))}%`}}/></div>
    <p><span>{state.hp} / {unit.stats.hp} <small>生命</small></span><span>{state.mp} <small>法力</small></span>{state.shield>0&&<span><Shield size={11}/>{state.shield}</span>}{state.hp===0&&<small>本场倒下</small>}</p>
  </article>
}

export type BattleReplayProps={battle:Battle;accountId?:string;displayEpoch?:string;reducedMotion?:boolean;autoPlay?:boolean;onComplete?:()=>void}
export function BattleReplay(props:BattleReplayProps) {return <Playback key={props.battle.id} {...props}/>}
function Playback({battle,accountId,displayEpoch,reducedMotion=false,autoPlay=true,onComplete}:BattleReplayProps) {
  const settings=usePresentationPreferences(accountId,displayEpoch),reduced=reducedMotion||settings.reducedMotion||settings.systemReduced
  const problem=useMemo(()=>validatePlayback(battle),[battle]),events=battle.result?.events||[],count=events.length
  const [cursor,setCursor]=useState(0),[playing,setPlaying]=useState(false),[speed,setSpeed]=useState(1),[seekVersion,setSeekVersion]=useState(0)
  const exact=useRef(0),frameId=useRef(0),completedOnce=useRef(false),complete=useRef(onComplete);complete.current=onComplete
  useEffect(()=>{if(battle.result&&!problem){exact.current=0;setCursor(0);setPlaying(autoPlay&&!reduced&&!document.hidden)}},[battle.id,!!battle.result,problem])
  useEffect(()=>{if(reduced){setPlaying(false);setCursor(Math.floor(exact.current))}},[reduced])
  useEffect(()=>{const visibility=()=>{if(document.hidden)setPlaying(false)};document.addEventListener('visibilitychange',visibility);return()=>document.removeEventListener('visibilitychange',visibility)},[])
  useEffect(()=>{
    if(!playing||problem||reduced)return
    const start=performance.now(),from=exact.current;let last=start
    const tick=(now:number)=>{
      const next=Math.min(count,from+(now-start)/tokens.motion_ms.battle_action*speed);exact.current=next
      if(now-last>=tokens.world.presentation.cue_poll_ms||next===count){setCursor(next);last=now}
      if(next>=count){setPlaying(false);if(!completedOnce.current){completedOnce.current=true;complete.current?.()}}
      else frameId.current=requestAnimationFrame(tick)
    }
    frameId.current=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frameId.current)
  },[playing,problem,reduced,speed,seekVersion,count])
  const seek=(next:number)=>{const at=Math.max(0,Math.min(count,next));exact.current=at;setCursor(at);setPlaying(false);setSeekVersion(v=>v+1)}
  const index=Math.floor(cursor),fraction=cursor-index,active=events[index],shown=problem&&battle.result?count:Math.min(count,index+(fraction>=tokens.world.presentation.battle_impact_ratio?1:0))
  const states=useMemo(()=>battleStatesAt(battle,shown),[battle,shown])
  const objects=useMemo(()=>{
    const units=battleObjects(battle,shown,active,fraction>=tokens.world.presentation.battle_impact_ratio?1:0,reduced||!!problem)
    const site=outpostObject(battle.snapshot.outpost)
    return [...units,{...site,x:0,z:-3.5,scale:tokens.world.geometry.outpost_scale,selectable:false,state:undefined}]
  },[battle,shown,active,fraction>=tokens.world.presentation.battle_impact_ratio,reduced,problem])
  const action=useMemo<SceneBattleAction|null>(()=>active&&!problem?{id:`${battle.id}:${active.sequence}:${seekVersion}`,actorId:active.actor_id,targetId:active.target_id,effect:battleEffect(active),startedAt:performance.now()-fraction*tokens.motion_ms.battle_action/speed,duration:tokens.motion_ms.battle_action/speed,frozenProgress:playing?undefined:fraction}:null,[battle.id,active,playing,speed,seekVersion,problem])
  const finished=!!battle.result&&(cursor>=count||!!problem),log=useMemo(()=>events.map(event=>battleEventText(event,battle)),[battle])
  return <section className="battle-replay" aria-label="保存战报的三维回放" data-battle-id={battle.id} data-playback-index={shown} data-reduced-motion={reduced}>
    <div className="game-stage battle-stage"><WorldMap objects={objects} theme={battle.snapshot.outpost.theme} seed={battle.id} accountId={accountId} displayEpoch={displayEpoch} regionId={`battle:${battle.id}`} reducedMotion={reduced} battleAction={action} initialFocus={{x:0,z:0}} sceneLabel="远征战报三维回放；伤害与结果来自保存的战报" statusText={battle.snapshot.outpost.name}/>
      <div className="battle-round" aria-live="off"><Swords size={16}/>{battle.result?finished?'战报结果':`第 ${active?.round||battle.result.rounds} 回合`:'等待服务端战报'}</div>
      {finished&&battle.result&&<div className={`battle-outcome ${battle.result.outcome}`}><Trophy size={26}/><strong>{battle.result.outcome==='won'?'归途，有了新的灯火':'休整之后，再次出发'}</strong><span>{battle.result.outcome==='won'?(battle.result.first_clear?'首次胜利 · 已永久占领':'胜利 · 该据点首胜奖励已领取'):'本场失利；自有角色和伙伴仍然保留'}</span>{battle.result.reward_points>0&&<b>+{battle.result.reward_points} <small>首胜积分 · 已结算</small></b>}</div>}
    </div>
    <div className="battle-controls">
      <div className="battle-transport"><button className="button secondary" aria-label="上一个战报动作" disabled={!count||cursor<=0||!!problem} onClick={()=>seek(Math.max(0,Math.ceil(cursor)-1))}><ChevronsLeft size={17}/></button><button className="button" disabled={!battle.result||!!problem||reduced||!count} onClick={()=>{if(playing){setPlaying(false);setCursor(exact.current)}else{if(cursor>=count){exact.current=0;setCursor(0);setSeekVersion(v=>v+1)}setPlaying(true)}}}>{playing?<Pause size={17}/>:cursor>=count?<RotateCcw size={17}/>:<Play size={17}/>}<span>{playing?'暂停':cursor>=count?'重播战报':'播放战报'}</span></button><button className="button secondary" aria-label="下一个战报动作" disabled={!count||cursor>=count||!!problem} onClick={()=>seek(Math.min(count,Math.floor(cursor)+1))}><ChevronsRight size={17}/></button></div>
      <label className="battle-speed">速度<select value={speed} disabled={reduced} onChange={e=>{setSpeed(Number(e.target.value));setSeekVersion(v=>v+1)}}>{tokens.world.presentation.battle_replay_speeds.map(value=><option key={value} value={value}>{value}×</option>)}</select></label>
      <button className="text-link" disabled={!battle.result} onClick={()=>{seek(count);if(!completedOnce.current){completedOnce.current=true;complete.current?.()}}}>直接查看结果<ChevronsRight size={15}/></button>
      <div className="battle-scrub"><label htmlFor={`replay-${battle.id}`}>动作 {shown} / {count}</label><input id={`replay-${battle.id}`} type="range" min={0} max={Math.max(1,count)} step={1} value={Math.min(count,cursor)} aria-label="回放进度" disabled={!count||!!problem} onChange={e=>seek(Number(e.target.value))}/></div>
    </div>
    {(problem||reduced)&&<p className="battle-playback-note" role="status">{problem||'低动效已启用。可以逐条查看状态变化，或直接查看已保存的结果。'}</p>}
    <p className="battle-current-action" role="status" aria-live={playing?'off':'polite'}>{active?log[index]:battle.result?'所有动作已读完。':'队伍快照已保存，正在等待完整动作记录。'}</p>
    <div className="battle-teams">{[battle.snapshot.allies,battle.snapshot.enemies].map((team,side)=><div key={side}><h3>{side===0?'我们的队伍':'敌方阵容'} <small>本场快照</small></h3>{team.map(unit=><UnitMeter key={unit.id} unit={unit} state={states[unit.id]} active={active?.actor_id===unit.id&&!finished}/>)}</div>)}</div>
    <details className="battle-log"><summary>完整动作记录 · {count} 条</summary><ol>{events.map((event,i)=><li key={event.sequence} className={i===index?'is-current':''}><span>R{event.round} · {event.sequence}</span>{log[i]}</li>)}</ol></details>
    <div className="battle-provenance"><p>这里只回放本场保存的状态。战后的临时生命与法力恢复，播放速度与跳过不会改变战果。</p>{battle.result?.ledger_entry_ids.map(id=><Link className="text-link" key={id} to={`/ledger?receipt=${encodeURIComponent(id)}`}>查看首胜积分回执</Link>)}<details><summary>战报来源与版本</summary><p>战报 · {battle.id}<br/>引擎 · {battle.engine_version}<br/>规则 · {battle.rule_version}<br/>队伍快照 · v{battle.snapshot.team_version}<br/>创建 · {battle.created_at}</p></details></div>
  </section>
}
