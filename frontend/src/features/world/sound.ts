import {useCallback, useEffect, useRef} from 'react'
import tokens from '../../../../docs/contracts/design-tokens.json'
import type {ActiveSequence} from './presentation'
import type {SceneSequence} from './scene-types'

// No remote audio or autoplay. AudioContext is opened by a user gesture;
// missed sounds are never queued to play unexpectedly on a later page.
export function useWorldSound(enabled:boolean, sequence?:ActiveSequence|null, pose?:string, sceneSequence?:SceneSequence|null) {
  const context=useRef<AudioContext|null>(null), voices=useRef(new Set<OscillatorNode>()),previousPose=useRef(pose)
  const previousSequence=useRef('')
  const stop=useCallback(()=>{for(const voice of voices.current){try{voice.stop()}catch{}voice.disconnect()}voices.current.clear()},[])
  const unlock=useCallback(()=>{
    if(!context.current&&typeof AudioContext!=='undefined')context.current=new AudioContext()
    void context.current?.resume().catch(()=>{})
  },[])
  const play=useCallback(()=>{
    const audio=context.current
    if(!enabled||document.hidden||audio?.state!=='running')return
    const l=tokens.world.lighting
    l.sound_frequencies.forEach((frequency,index)=>{
      if(voices.current.size>=tokens.world.audio.max_simultaneous_effects)return
      const tone=audio.createOscillator(),gain=audio.createGain(),start=audio.currentTime+index*l.sound_seconds/3
      tone.type='sine';tone.frequency.value=frequency;gain.gain.setValueAtTime(0,start);gain.gain.linearRampToValueAtTime(l.sound_gain,start+0.015);gain.gain.exponentialRampToValueAtTime(0.0001,start+l.sound_seconds)
      tone.connect(gain);gain.connect(audio.destination);voices.current.add(tone)
      tone.onended=()=>{voices.current.delete(tone);tone.disconnect();gain.disconnect()}
      tone.start(start);tone.stop(start+l.sound_seconds)
    })
  },[enabled])
  useEffect(()=>{
    if(!enabled){stop();void context.current?.suspend();return}
    const gesture=()=>unlock()
    document.addEventListener('pointerdown',gesture);document.addEventListener('keydown',gesture)
    return()=>{document.removeEventListener('pointerdown',gesture);document.removeEventListener('keydown',gesture);stop()}
  },[enabled,stop,unlock])
  useEffect(()=>{
    const key=sceneSequence?.id||sequence?.event.id||''
    if(!key||previousSequence.current===key)return
    previousSequence.current=key
    if(!enabled||sceneSequence?.correction||sceneSequence?.kind==='penalty'||sequence?.event.is_correction)return
    const startedAt=sceneSequence?.startedAt??sequence!.startedAt,duration=sceneSequence?.duration??sequence!.duration
    const major=sceneSequence?.kind==='occupation'||sequence?.event.kind==='chapter_landmark'
    const wait=Math.max(0,(major?tokens.world.presentation.landmark_cues_ms.lights:0)-(performance.now()-startedAt))
    const timer=setTimeout(()=>{if(performance.now()-startedAt<=duration)play()},wait);return()=>clearTimeout(timer)
  },[sequence?.event.id,sceneSequence?.id,enabled,play])
  useEffect(()=>{if(pose!==previousPose.current&&!sequence&&(pose==='wave'||pose==='celebrate'))play();previousPose.current=pose},[pose,play,sequence])
  useEffect(()=>()=>{stop();void context.current?.close();context.current=null},[stop])
  return unlock
}
