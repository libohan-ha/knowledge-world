import {useCallback, useEffect, useRef, useState} from 'react'
import {Link} from 'react-router-dom'
import {ArrowRight, Check, CircleMinus, Feather, History, SkipForward, Sparkles} from 'lucide-react'
import tokens from '../../../../docs/contracts/design-tokens.json'
import type {SceneSequence} from './scene-types'
import {effectDuration, sceneCue, sequenceFrame} from './timeline'
import {FeedbackQueue, readBookmark, type VisualEvent} from './feedback-state'
import {usePresentationPreferences} from './presentation-preferences'
import './game-ui.css'

export type PlayingFeedback = {event: VisualEvent; sequence: SceneSequence}
export function feedbackSequence(event: VisualEvent, replay = false): SceneSequence {
  return {id: event.id, kind: event.kind, targetId: event.targetId, startedAt: performance.now(), duration: effectDuration(event.kind), correction: event.tone === 'correction', replay,
    beforeModel: event.beforeObjects?.find(object => object.id === event.targetId)?.model ?? null,
    afterModel: event.afterObjects?.find(object => object.id === event.targetId)?.model ?? null}
}

/** Mount once per account/epoch in a business container. Only reads display state. */
export function useGameFeedback(events: readonly VisualEvent[], namespace: string, blocked = false, ready = true) {
  const key = `kw-world-seen:game:${tokens.version}:${namespace}`
  const queue = useRef<{key: string; value: FeedbackQueue} | null>(null)
  const [playing, setPlaying] = useState<(PlayingFeedback & {key: string}) | null>(null), [pending, setPending] = useState(0)
  const [inputActive, setInputActive] = useState(false)
  if (queue.current?.key !== key) {
    let value: string | null = null;try {value = localStorage.getItem(key)} catch { /* Private storage. */ }
    queue.current = {key, value: new FeedbackQueue(readBookmark(value))}
  }
  const persist = useCallback(() => {try {localStorage.setItem(key, JSON.stringify(queue.current!.value.bookmark))} catch { /* Replaying affects display only. */ }}, [key])
  useEffect(() => {
    const update = () => setInputActive(!!document.activeElement?.matches('input,textarea,select,[contenteditable="true"]') || !!document.querySelector('dialog[open],[role="dialog"][aria-modal="true"]'))
    update();document.addEventListener('focusin', update);document.addEventListener('focusout', update)
    const observer = new MutationObserver(update);observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['open', 'aria-modal']})
    return () => {document.removeEventListener('focusin', update);document.removeEventListener('focusout', update);observer.disconnect()}
  }, [])
  useEffect(() => {
    if (!ready) return
    queue.current!.value.ingest(events);persist();setPending(queue.current!.value.pending.length)
  }, [events, key, persist, ready])
  useEffect(() => {
    const storage = (event: StorageEvent) => {if (event.key === key) {queue.current!.value.mergeBookmark(readBookmark(event.newValue));setPending(queue.current!.value.pending.length)}}
    window.addEventListener('storage', storage);return () => window.removeEventListener('storage', storage)
  }, [key])
  useEffect(() => {
    if (blocked || inputActive || playing?.key === key || !pending) return
    const event = queue.current!.value.take()
    if (event) {persist();setPlaying({key, event, sequence: feedbackSequence(event)})}
    setPending(queue.current!.value.pending.length)
  }, [blocked, inputActive, key, pending, playing, persist])
  const finish = useCallback(() => setPlaying(null), [])
  return {playing: playing?.key === key ? playing : null, pending, finish, inputActive}
}

export function EventChanges({event}: {event: VisualEvent}) {
  return <>
    {!!event.changes.length && <dl className="game-change-list">{event.changes.map((change, index) => <div key={`${change.label}:${index}`}><dt>{change.label}</dt><dd>{change.before !== undefined && <><span>{change.before}</span><ArrowRight size={13} aria-label="变为"/></>}<strong>{change.after}</strong></dd></div>)}</dl>}
    {!!event.economics?.length && <div className="game-economics">{event.economics.map((line, index) => <span key={`${line.label}:${index}`}><small>{line.label}</small><b className={line.value < 0 ? 'is-negative' : line.value > 0 ? 'is-positive' : ''}>{line.value > 0 ? '+' : ''}{line.value.toLocaleString('zh-CN')}<em>{line.unit || '积分'}</em></b></span>)}</div>}
  </>
}

export function EventSource({event}: {event: VisualEvent}) {
  return <div className="game-event-source">
    {event.source.href && <Link className="text-link" to={event.source.href}>查看{event.source.label}<ArrowRight size={14}/></Link>}
    {event.ledgerIds.map((id, index) => <Link key={id} className="text-link" to={`/ledger?receipt=${encodeURIComponent(id)}`}>积分回执{event.ledgerIds.length > 1 ? ` ${index + 1}` : ''}<ArrowRight size={14}/></Link>)}
    <details><summary>来源与事件</summary><p>{event.source.label} · {event.source.id}<br/>事件 · {event.id}<br/><time dateTime={event.occurredAt}>{event.occurredAt.replace('T', ' ')}</time></p></details>
  </div>
}

export function GameFeedback({playing, onFinish, onSkip = onFinish, accountId, displayEpoch, reducedMotion = false, inline = false}: {playing: PlayingFeedback; onFinish: () => void; onSkip?: () => void; accountId?: string; displayEpoch?: string; reducedMotion?: boolean; inline?: boolean}) {
  const {event, sequence} = playing, preferences = usePresentationPreferences(accountId, displayEpoch), reduced = reducedMotion || preferences.reducedMotion || preferences.systemReduced
  const [now, setNow] = useState(() => performance.now()), root = useRef<HTMLElement>(null), done = useRef(''), callback = useRef(onFinish);callback.current = onFinish
  useEffect(() => {
    done.current = ''
    const tick = () => {
      const time = performance.now();setNow(time)
      // Do not remove the focused receipt link/skip button while it is in use.
      if (time - sequence.startedAt >= sequence.duration && !root.current?.contains(document.activeElement) && done.current !== sequence.id) {done.current = sequence.id;callback.current()}
    }
    tick();const timer = window.setInterval(tick, tokens.world.presentation.cue_poll_ms);return () => clearInterval(timer)
  }, [sequence])
  const frame = sequenceFrame(sequence, now, reduced), cue = sceneCue(sequence, now, reduced), Icon = event.tone === 'negative' ? CircleMinus : event.tone === 'correction' ? History : event.tone === 'neutral' ? Feather : frame.finished ? Check : Sparkles
  return <section ref={root} className={`game-feedback ${inline ? 'is-inline' : ''} tone-${event.tone}`} aria-label="世界变化回执" data-event-id={event.id} data-cue={cue} data-replay={sequence.replay || false} data-reduced-motion={reduced}>
    <div className="game-feedback-emblem" aria-hidden="true"><Icon size={24}/></div>
    <div className="game-feedback-copy"><span className="game-eyebrow">{sequence.replay ? '这一次真实的变化 · 回放' : '世界有了回应'}</span><h3>{event.title}</h3><p role="status" aria-live="polite">{event.tone === 'negative' || event.tone === 'neutral' || event.tone === 'correction' ? event.description : cue}</p><EventChanges event={event}/><EventSource event={event}/></div>
    <button className="button quiet game-skip" onClick={onSkip}><SkipForward size={15}/>{frame.finished ? '收好回执' : '跳过演出'}</button>
    <div className="game-sequence-progress" aria-hidden="true"><i style={{transform: `scaleX(${frame.progress})`}}/></div>
  </section>
}
