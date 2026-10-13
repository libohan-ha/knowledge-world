import {useEffect, useMemo, useRef, useState} from 'react'
import {Link} from 'react-router-dom'
import {ArrowRight, BookOpen, Clock3, Pause, Play, RefreshCw, RotateCcw} from 'lucide-react'
import tokens from '../../../../docs/contracts/design-tokens.json'
import {Button, ErrorNotice} from '../../shared/ui'
import {CountdownTimer} from '../../shared/CountdownTimer'
import {notify, playChime} from '../../shared/chime'
import type {Ticket, Unit} from './game-view'
import {gameStateLabels, unitObject} from './game-view'
import {WorldMap} from './WorldMap'
import type {SceneObject, SceneSequence} from './scene-types'
import {effectDuration} from './timeline'
import {usePresentationPreferences} from './presentation-preferences'
import './game-ui.css'

export type LeisureAction='start'|'pause'|'resume'|'cancel'
export type LeisureRoomProps={ticket:Ticket;accountId?:string;displayEpoch?:string;companion?:Unit;pending?:boolean;error?:unknown;syncError?:unknown;onAction:(action:LeisureAction)=>void;onRefresh?:()=>void;reducedMotion?:boolean}

/** A local display estimate anchored to the latest server response. It can
 * reach zero, but cannot complete, pause, extend or charge a ticket. */
export function ticketDisplaySeconds(ticket:Pick<Ticket,'state'|'remaining_seconds'>,receivedAt:number,now:number) {
  const elapsed=ticket.state==='running'?Math.max(0,now-receivedAt)/1000:0
  return Math.max(0,Math.ceil(ticket.remaining_seconds-elapsed))
}
export function formatDuration(seconds:number) {
  const total=Math.max(0,Math.floor(seconds)),h=Math.floor(total/3600),m=Math.floor(total%3600/60),s=total%60
  return `${h?`${h}:`:''}${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`
}

export function LeisureRoom(props:LeisureRoomProps){return <Room key={`${props.accountId}:${props.displayEpoch}:${props.ticket.id}`} {...props}/>}
function Room({ticket,accountId,displayEpoch,companion,pending,error,syncError,onAction,onRefresh,reducedMotion=false}:LeisureRoomProps) {
  const options=usePresentationPreferences(accountId,displayEpoch),reduced=reducedMotion||options.reducedMotion||options.systemReduced
  const anchor=useMemo(()=>({at:performance.now(),ticket}),[ticket.id,ticket.version,ticket.server_time,ticket.remaining_seconds,ticket.state])
  const [now,setNow]=useState(()=>performance.now()),[sequence,setSequence]=useState<SceneSequence|null>(null),[announce,setAnnounce]=useState('')
  const previous=useRef(ticket.state),refresh=useRef(onRefresh),requested=useRef('');refresh.current=onRefresh
  useEffect(()=>{setNow(performance.now());const timer=setInterval(()=>setNow(performance.now()),1000);return()=>clearInterval(timer)},[anchor])
  const seconds=ticketDisplaySeconds(anchor.ticket,anchor.at,now)
  useEffect(()=>{
    const key=`${ticket.id}:${ticket.version}`
    if(ticket.state==='running'&&seconds===0&&requested.current!==key){requested.current=key;refresh.current?.()}
  },[seconds,ticket.id,ticket.version,ticket.state])
  useEffect(()=>{
    if(ticket.state===previous.current)return
    if(ticket.state==='running') {
      const eventId=ticket.game_event_ids.at(-1)
      if(eventId)setSequence({id:eventId,kind:'leisure',targetId:`room:${ticket.id}`,startedAt:performance.now(),duration:effectDuration('leisure')})
      setAnnounce(previous.current==='paused'?'余量已恢复，继续休息吧。':'休闲已开始，安心享受这段时间。')
    } else if(ticket.state==='completed'){setAnnounce('这段休息时光已结束。没有自动续费，可以慢慢收心。');if(previous.current==='running'){if(localStorage.getItem('kw-timer-sound')!=='off')playChime();notify(ticket.snapshot.name,'这段休息时光已结束，慢慢收心。')}}
    else if(ticket.state==='paused')setAnnounce('已经暂停，剩余时光已保存。')
    previous.current=ticket.state
  },[ticket.state,ticket.id,ticket.game_event_ids])
  useEffect(()=>{if(!sequence)return;const timer=setTimeout(()=>setSequence(null),sequence.duration);return()=>clearTimeout(timer)},[sequence])
  const objects=useMemo(()=>{
    const items:SceneObject[]=[{id:`room:${ticket.id}`,model:'room:reading',x:0,z:0,title:'暖灯休息小屋',selectable:false}]
    if(companion){const unit=unitObject(companion,0.58,0.36,ticket.state==='running'?'rest':'idle',-35);if(unit)items.push({...unit,scale:tokens.world.geometry.unit_scale*0.75,elevation:0.16,selectable:false})}
    return items
  },[ticket.id,ticket.state,companion])
  const stateText=ticket.state==='running'&&seconds===0?'正在核对结束状态':gameStateLabels[ticket.state]||ticket.state
  return <section className="leisure-room game-art-panel" data-ticket-id={ticket.id} data-ticket-state={ticket.state}>
    <div className="leisure-room-art"><WorldMap objects={objects} compact framing="room" accountId={accountId} displayEpoch={displayEpoch} regionId={`leisure:${ticket.id}`} reducedMotion={reduced} sceneSequence={sequence} initialFocus={{x:0,z:0}} sceneLabel="休息小屋：有书柜、沙发、暖灯的三维房间"/><div className="leisure-room-caption"><BookOpen size={17}/><span>一盏灯，一小段自己的时间。</span></div></div>
    <div className="leisure-ticket"><span className="game-eyebrow">REST & RETURN</span><h2>{ticket.snapshot.name}</h2><p>{ticket.snapshot.description}</p><span className="game-state-pill"><Clock3 size={14}/>{stateText}</span>
      <div className="leisure-clock" data-remaining={seconds}><span aria-hidden="true">{formatDuration(seconds)}</span><span className="sr-only">剩余 {Math.floor(seconds/60)} 分 {seconds%60} 秒</span><small>{ticket.state==='paused'?'余量已经收好':ticket.state==='reserved'?'准备好了，再开始':ticket.state==='completed'?'这段好时光，已经收好':syncError?'等待重新同步时间':'留给自己的时光'}</small></div>
      <div className="leisure-time-track" aria-hidden="true"><i style={{width:`${Math.max(0,Math.min(100,seconds/Math.max(1,ticket.duration_seconds)*100))}%`}}/></div>
      <div className="leisure-usage" aria-label="本券使用进度"><span>已用 <strong>{Math.floor(Math.max(0,ticket.duration_seconds-seconds)/60)} 分 {Math.max(0,ticket.duration_seconds-seconds)%60} 秒</strong></span><span>进度 <strong>{Math.round(Math.max(0,Math.min(1,1-seconds/Math.max(1,ticket.duration_seconds)))*100)}%</strong></span><span>共 <strong>{Math.ceil(ticket.duration_seconds/60)} 分钟</strong></span></div>
      <div className="leisure-snapshot"><span>本券时长 <strong>{Math.ceil(ticket.duration_seconds/60)} 分钟</strong></span><span>{ticket.first_started_at?'本券消费':'本券预留'} <strong>{ticket.price_points} 积分</strong></span></div>
      <div className="leisure-actions">{ticket.state==='reserved'&&<><Button busy={pending} onClick={()=>onAction('start')}><Play size={17}/>开始这段休闲</Button>{ticket.first_started_at===null&&<Button kind="secondary" disabled={pending} onClick={()=>onAction('cancel')}><RotateCcw size={15}/>未开始，原价退回</Button>}</>}{ticket.state==='running'&&seconds>0&&<Button busy={pending} onClick={()=>onAction('pause')}><Pause size={17}/>暂停，保留余量</Button>}{ticket.state==='paused'&&<Button busy={pending} onClick={()=>onAction('resume')}><Play size={17}/>继续休闲</Button>}{['completed','cancelled'].includes(ticket.state)&&<Link className="button secondary" to="/rewards">回到奖励工坊<ArrowRight size={15}/></Link>}{onRefresh&&<Button kind="quiet" disabled={pending} onClick={onRefresh}><RefreshCw size={14}/>同步时间</Button>}</div>
      <ErrorNotice error={error}/>{!!syncError&&<p className="notice" role="status">连接暂时中断。重新同步后会核对实际余量；请使用按钮重试。</p>}<p className="leisure-announcement" role="status" aria-live="polite">{announce}</p>
      <details className="cabin-timer" open={ticket.state==='running'||undefined}><summary>小屋计时器 · 给自己定个闹钟</summary><p className="micro-copy">独立于休闲券的本地计时，刷新页面也会继续；到点会轻轻响一声。休闲券本身的时间以服务端为准。</p><CountdownTimer storageKey={`kw-cabin-timer:${accountId||'local'}:${ticket.id}`} title="小屋计时器" label={ticket.snapshot.name} defaultMinutes={Math.min(25,Math.max(1,Math.ceil(ticket.duration_seconds/60)))} extraPreset={['running','paused'].includes(ticket.state)&&seconds>60?{label:'本券剩余',minutes:Math.ceil(seconds/60)}:null} finishText="计时结束。可以再续一会儿，也可以慢慢收心。"/></details>
      <div className="leisure-source"><p>本券的时长与价格已经保存，修改奖励目录不会改变它。</p>{ticket.ledger_entry_ids.map((id,index)=><Link className="text-link" key={id} to={`/ledger?receipt=${encodeURIComponent(id)}`}>积分回执{ticket.ledger_entry_ids.length>1?` ${index+1}`:''}</Link>)}<details><summary>休闲券记录</summary><p>券 · {ticket.id}<br/>规则 · {ticket.rule_version}<br/>最近同步 · {ticket.server_time}</p></details></div>
    </div>
  </section>
}
