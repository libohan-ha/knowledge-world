import {useState} from 'react'
import {Feather, Play, RotateCcw} from 'lucide-react'
import type {VisualEvent} from './feedback-state'
import {WorldMap} from './WorldMap'
import {EventChanges, EventSource, feedbackSequence, GameFeedback, type PlayingFeedback} from './GameFeedback'
import {usePresentationPreferences} from './presentation-preferences'
import './game-ui.css'

export function HistoryComparison({event,accountId,displayEpoch,reducedMotion=false}:{event:VisualEvent;accountId?:string;displayEpoch?:string;reducedMotion?:boolean}) {
  const [playing,setPlaying]=useState<PlayingFeedback|null>(null),options=usePresentationPreferences(accountId,displayEpoch),reduced=reducedMotion||options.reducedMotion||options.systemReduced
  const canCompare=event.beforeObjects!==null&&event.beforeObjects!==undefined&&event.afterObjects!==null&&event.afterObjects!==undefined
  return <section className="game-history-comparison" data-event-id={event.id}>
    <p className="game-history-scope">回看这一次保存的对象变化。造型采用当前美术版本；这里没有补画当时整片世界。</p>
    {playing&&event.afterObjects?<div className="game-stage history-sequence-stage"><WorldMap objects={event.afterObjects} compact showControls theme={event.theme} accountId={accountId} displayEpoch={displayEpoch} regionId={`history:${event.id}`} selected={event.targetId} sceneSequence={playing.sequence} reducedMotion={reduced}/><GameFeedback playing={playing} accountId={accountId} displayEpoch={displayEpoch} reducedMotion={reduced} onFinish={()=>setPlaying(null)}/></div>:<div className="game-history-pair">{[{label:'变化之前',objects:event.beforeObjects},{label:'变化之后',objects:event.afterObjects}].map(({label,objects})=><article key={label}>
      <header><span>{label}</span><small>{objects?.length?'保存的对象状态':objects?'明确记录为空':'这部分尚未记录'}</small></header>
      {objects?.length?<WorldMap objects={objects} compact theme={event.theme} accountId={accountId} displayEpoch={displayEpoch} regionId={`history:${event.id}:${label}`} reducedMotion/>:<div className="game-empty"><Feather size={28}/><p>{objects?'当时还没有这件物件。':'缺少当时的模型状态，无法可靠还原。'}</p></div>}
    </article>)}</div>}
    {!canCompare&&<p className="notice" role="status">这条记录的三维前后态尚未齐全。下面保留了有来源的实际变化。</p>}
    <EventChanges event={event}/><p className="game-history-reason">{event.description}</p>
    {canCompare&&<button className="button secondary" onClick={()=>setPlaying({event,sequence:feedbackSequence(event,true)})}>{playing?<RotateCcw size={16}/>:<Play size={16}/>}重播这次变化</button>}
    <EventSource event={event}/>
  </section>
}
