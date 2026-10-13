import {useEffect,useRef,useState} from 'react'
import {Bell,BellOff,Pause,Play,RotateCcw} from 'lucide-react'
import {askNotificationPermission,notify,playChime} from './chime'

/** Persisted timer state. A running timer stores its wall-clock end, so a
 * refresh (or a closed tab) resumes at the right place. */
export type TimerState={duration:number;remaining:number;endsAt:number|null;finishedAt:number|null;label:string}
export const idleTimer=(minutes:number,label=''):TimerState=>({duration:minutes*60000,remaining:minutes*60000,endsAt:null,finishedAt:null,label})
export function timerRemaining(state:TimerState,now:number){return state.endsAt===null?state.remaining:Math.max(0,state.endsAt-now)}
export function startTimer(state:TimerState,now:number):TimerState{const remaining=state.remaining>0?state.remaining:state.duration;return {...state,remaining,endsAt:now+remaining,finishedAt:null}}
export function pauseTimer(state:TimerState,now:number):TimerState{return {...state,remaining:timerRemaining(state,now),endsAt:null}}
export function resetTimer(state:TimerState,minutes=state.duration/60000):TimerState{return idleTimer(minutes,state.label)}
export function finishTimer(state:TimerState,now:number):TimerState{return {...state,remaining:0,endsAt:null,finishedAt:state.endsAt??now}}
export function loadTimer(key:string,fallback:TimerState):TimerState{
  try{const value=JSON.parse(localStorage.getItem(key)||'null');if(value&&typeof value.duration==='number'&&typeof value.remaining==='number')return {...fallback,...value}}catch{/* corrupt value: start fresh */}
  return fallback
}
export const clock=(ms:number)=>{const total=Math.ceil(Math.max(0,ms)/1000),h=Math.floor(total/3600),m=Math.floor(total%3600/60),s=total%60;return `${h?`${h}:`:''}${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}

export type CountdownProps={storageKey:string;title?:string;presets?:{label:string;minutes:number}[];defaultMinutes?:number;label?:string;onFinish?:(state:TimerState)=>void;finishText?:string;className?:string;extraPreset?:{label:string;minutes:number}|null}
export function CountdownTimer({storageKey,title='计时器',presets=[{label:'5 分',minutes:5},{label:'15 分',minutes:15},{label:'25 分',minutes:25},{label:'45 分',minutes:45}],defaultMinutes=25,label='',onFinish,finishText='时间到了，慢慢收心。',className='',extraPreset}:CountdownProps){
  const [state,setState]=useState(()=>loadTimer(storageKey,idleTimer(defaultMinutes,label))),[now,setNow]=useState(()=>Date.now())
  const [sound,setSound]=useState(()=>localStorage.getItem('kw-timer-sound')!=='off'),[minutes,setMinutes]=useState(()=>Math.round(state.duration/60000)||defaultMinutes)
  const finish=useRef(onFinish);finish.current=onFinish
  const remaining=timerRemaining(state,now),running=state.endsAt!==null
  useEffect(()=>{localStorage.setItem(storageKey,JSON.stringify(state))},[state,storageKey])
  useEffect(()=>{if(!running)return;const timer=setInterval(()=>setNow(Date.now()),250);return()=>clearInterval(timer)},[running])
  useEffect(()=>{
    if(!running||remaining>0)return
    const ended=finishTimer(state,Date.now()),late=Date.now()-(state.endsAt||0)>60000
    setState(ended)
    // Ended while the page was closed for long: show it, but do not ring out of nowhere.
    if(!late){if(sound)playChime();notify(state.label||title,finishText)}
    finish.current?.(ended)
  },[running,remaining])
  function choose(value:number){const safe=Math.max(1,Math.min(600,Math.round(value)||1));setMinutes(safe);setState(resetTimer(state,safe))}
  const progress=state.duration?1-remaining/state.duration:0,radius=54,circumference=2*Math.PI*radius
  const status=state.finishedAt?'done':running?'running':remaining<state.duration?'paused':'idle'
  return <section className={'countdown '+className} data-state={status} aria-label={title}>
    <div className="countdown-ring" role="timer" aria-live="off" aria-label={`${title}剩余 ${clock(remaining)}`}>
      <svg viewBox="0 0 120 120" aria-hidden="true"><circle className="countdown-track" cx="60" cy="60" r={radius}/><circle className="countdown-progress" cx="60" cy="60" r={radius} strokeDasharray={circumference} strokeDashoffset={circumference*(1-progress)}/></svg>
      <div className="countdown-readout"><strong>{clock(remaining)}</strong><small>{status==='done'?'时间到':status==='running'?'进行中':status==='paused'?'已暂停':`${Math.round(state.duration/60000)} 分钟`}</small></div>
    </div>
    <div className="countdown-controls">
      <div className="countdown-presets" role="group" aria-label="快速设定">{[...presets,...(extraPreset?[extraPreset]:[])].map(preset=><button type="button" key={preset.label} className={!running&&Math.round(state.duration/60000)===preset.minutes?'active':''} disabled={running} onClick={()=>choose(preset.minutes)}>{preset.label}</button>)}
        <label className="countdown-minutes"><input type="number" min={1} max={600} value={minutes} disabled={running} aria-label="自定义分钟" onChange={e=>setMinutes(Number(e.target.value))} onBlur={()=>choose(minutes)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();choose(minutes)}}}/><span>分</span></label></div>
      <div className="countdown-actions">{running?<button type="button" className="button" onClick={()=>setState(pauseTimer(state,Date.now()))}><Pause size={16}/>暂停</button>:<button type="button" className="button" onClick={()=>{askNotificationPermission();setNow(Date.now());setState(startTimer(state,Date.now()))}}><Play size={16}/>{status==='paused'?'继续':'开始'}</button>}
        <button type="button" className="button secondary" onClick={()=>{setState(resetTimer(state));setNow(Date.now())}}><RotateCcw size={15}/>重置</button>
        <button type="button" className="icon-button countdown-sound" aria-pressed={sound} aria-label={sound?'结束提示音：开':'结束提示音：关'} onClick={()=>{const next=!sound;setSound(next);localStorage.setItem('kw-timer-sound',next?'on':'off');if(next)playChime(0.2)}}>{sound?<Bell size={17}/>:<BellOff size={17}/>}</button></div>
      {status==='done'&&<p className="countdown-done" role="status">{finishText}</p>}
    </div>
  </section>
}
