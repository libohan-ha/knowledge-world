import {createContext, useContext, useEffect, useMemo, useState, type ReactNode} from 'react'
import {useLocation} from 'react-router-dom'
import {useApi, type Schema} from './api/client'
import {useApp} from '../app-context'
import {GameFeedback, useGameFeedback, type PlayingFeedback} from '../features/world/GameFeedback'
import {eventToVisual} from '../features/world/game-view'

const FeedbackContext=createContext<PlayingFeedback|null>(null)
export const useWorldFeedback=()=>useContext(FeedbackContext)
export function GameFeedbackProvider({children}:{children:ReactNode}) {
  const {profile}=useApp(),location=useLocation(),namespace=profile.id+':'+profile.display_epoch
  const [position,setPosition]=useState<{namespace:string;sequence:number}|null>(null)
  const [received,setReceived]=useState<{namespace:string;events:Schema<'HistoryEvent'>[]}>({namespace,events:[]})
  const [hidden,setHidden]=useState(document.hidden)
  const feed=useApi<Schema<'EventFeed'>>('/world/events'+(position?.namespace===namespace?'?after_sequence='+position.sequence:''),2500)
  const map=useApi<Schema<'WorldMap'>>('/world/map')
  useEffect(()=>{const change=()=>setHidden(document.hidden);document.addEventListener('visibilitychange',change);return()=>document.removeEventListener('visibilitychange',change)},[])
  useEffect(()=>{
    if(!feed.data||feed.data.display_epoch!==profile.display_epoch)return
    setReceived(previous=>({namespace,events:[...new Map([...(previous.namespace===namespace?previous.events:[]),...feed.data!.items].map(event=>[event.id,event])).values()].slice(-200)}))
    setPosition({namespace,sequence:feed.data.last_sequence})
  },[feed.data,namespace])
  const events=useMemo(()=>received.namespace===namespace?received.events.map(event=>eventToVisual(event,{map:map.data})):[],[received,namespace,map.data])
  const {playing,finish}=useGameFeedback(events,namespace,hidden||location.pathname.includes('/battles/'),position?.namespace===namespace&&received.namespace===namespace)
  return <FeedbackContext.Provider value={playing}>{children}{playing&&<GameFeedback key={playing.event.id} playing={playing} onFinish={finish} accountId={profile.id} displayEpoch={profile.display_epoch} reducedMotion={profile.preferences.reduced_motion}/>}</FeedbackContext.Provider>
}
