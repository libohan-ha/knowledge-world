import {useEffect,useMemo,useRef,useState} from 'react'
import {Link} from 'react-router-dom'
import {Coffee,CloudRain,Flame,Pause,Play,Sparkles,Volume2,Waves,Wind} from 'lucide-react'
import tokens from '../../../docs/contracts/design-tokens.json'
import {useApi,type Schema} from '../shared/api/client'
import {PageTitle} from '../shared/ui'
import {useApp} from '../app-context'
import {CountdownTimer,type TimerState} from '../shared/CountdownTimer'
import {AMBIENT_PRESETS,AMBIENT_SOUNDS,AmbientMixer,DEFAULT_MIX,loadMix,type AmbientId,type AmbientMix} from '../shared/ambient'
import {WorldMap} from './world/WorldMap'
import {unitObject} from './world/game-view'
import type {SceneObject} from './world/scene-types'
import './world/game-ui.css'

const icons:Record<AmbientId,typeof Wind>={rain:CloudRain,cafe:Coffee,fireplace:Flame,brown:Waves,white:Wind}
const FOCUS=[{label:'专注 25',minutes:25},{label:'专注 50',minutes:50},{label:'短休 5',minutes:5},{label:'长休 15',minutes:15}]
const today=()=>new Date().toLocaleDateString('sv')

/** Today's finished focus sessions, kept on this device only. */
function useFocusCount(key:string){
  const read=()=>{try{const value=JSON.parse(localStorage.getItem(key)||'null');return value?.day===today()?Number(value.count)||0:0}catch{return 0}}
  const [count,setCount]=useState(read)
  return [count,()=>{const next=read()+1;localStorage.setItem(key,JSON.stringify({day:today(),count:next}));setCount(next)}] as const
}

export function AmbientPanel({storageKey}:{storageKey:string}){
  const mixer=useRef<AmbientMixer|null>(null),[mix,setMix]=useState<AmbientMix>(()=>loadMix(storageKey)),[playing,setPlaying]=useState(false),[unsupported,setUnsupported]=useState(false)
  useEffect(()=>{localStorage.setItem(storageKey,JSON.stringify(mix));if(playing)mixer.current?.apply(mix)},[mix,playing,storageKey])
  useEffect(()=>()=>mixer.current?.stop(),[])
  function toggle(){
    if(playing){mixer.current?.stop();setPlaying(false);return}
    mixer.current=mixer.current||new AmbientMixer()
    const active=Object.values(mix.layers).some(level=>level>0)?mix:{...mix,layers:{...DEFAULT_MIX.layers}}
    if(!mixer.current.start(active)){setUnsupported(true);return}
    setMix(active);setPlaying(true)
  }
  const setLayer=(id:AmbientId,level:number)=>setMix(value=>({...value,layers:{...value.layers,[id]:level}}))
  return <section className="ambient-panel" aria-label="白噪音与环境声">
    <header className="ambient-heading"><div><span className="game-eyebrow">AMBIENT · 环境声</span><h3>给耳朵一间安静的房间</h3></div><button type="button" className={'button ambient-play'+(playing?' is-playing':'')} aria-pressed={playing} onClick={toggle}>{playing?<><Pause size={16}/>暂停声音</>:<><Play size={16}/>播放声音</>}</button></header>
    <div className="ambient-presets" role="group" aria-label="混音预设">{AMBIENT_PRESETS.map(preset=><button type="button" key={preset.name} onClick={()=>setMix(value=>({...value,layers:{...Object.fromEntries(AMBIENT_SOUNDS.map(({id})=>[id,0])) as Record<AmbientId,number>,...preset.mix}}))}>{preset.name}</button>)}</div>
    <ul className="ambient-layers">{AMBIENT_SOUNDS.map(sound=>{const Icon=icons[sound.id],level=mix.layers[sound.id];return <li key={sound.id} className={level>0?'is-on':''}>
      <button type="button" className="ambient-toggle" aria-pressed={level>0} aria-label={(level>0?'关闭 ':'打开 ')+sound.name} onClick={()=>setLayer(sound.id,level>0?0:0.5)}><Icon size={18}/></button>
      <label><span>{sound.name}<small>{sound.hint}</small></span><input type="range" min={0} max={1} step={0.01} value={level} aria-label={sound.name+' 音量'} onChange={e=>setLayer(sound.id,Number(e.target.value))}/></label>
    </li>})}</ul>
    <label className="ambient-master"><Volume2 size={17}/><span>总音量</span><input type="range" min={0} max={1} step={0.01} value={mix.master} aria-label="总音量" onChange={e=>setMix(value=>({...value,master:Number(e.target.value)}))}/></label>
    <p className="micro-copy">声音由浏览器实时合成，不下载任何音频文件；你的混音会记在这台设备上。{unsupported&&' 当前浏览器不支持 Web Audio。'}</p>
  </section>
}

export default function StudyCabin(){
  const {profile}=useApp(),roster=useApi<Schema<'Roster'>>('/roster'),[count,addSession]=useFocusCount('kw-study-focus:'+profile.id),[note,setNote]=useState('')
  const companion=roster.data?.monsters?.[0]
  const objects=useMemo(()=>{
    const items:SceneObject[]=[{id:'room:study',model:'room:study',x:0,z:0,title:'学习小屋',selectable:false}]
    if(companion){const unit=unitObject(companion,0.66,0.42,'rest',-40);if(unit)items.push({...unit,scale:tokens.world.geometry.unit_scale*0.7,elevation:0.16,selectable:false})}
    return items
  },[companion?.id])
  function finished(state:TimerState){if(state.duration>=20*60000){addSession();setNote('这一段专注完成了。起来走走、喝口水，再回来。')}else setNote('休息结束，回到书桌吧。')}
  return <div className="core-page study-page"><PageTitle eyebrow="STUDY CABIN · 陪你学习" title="学习小屋，灯一直亮着。" description="点一盏灯，放一点雨声。专注一段，休息一段，系统和伙伴都在。"/>
    <section className="study-room game-art-panel">
      <div className="study-room-art"><WorldMap objects={objects} compact framing="room" accountId={profile.id} displayEpoch={profile.display_epoch} regionId="study-cabin" reducedMotion={profile.preferences.reduced_motion} initialFocus={{x:0,z:0}} sceneLabel="学习小屋：窗边的书桌、暖色台灯、摊开的书和书架"/><div className="leisure-room-caption"><Sparkles size={16}/><span>{companion?`${companion.name} 趴在一旁，安静地陪你。`:'窗外很安静，书桌刚刚好。'}</span></div></div>
      <div className="study-side">
        <section className="study-focus"><header><span className="game-eyebrow">FOCUS · 番茄钟（可选）</span><h3>今天已专注 <b>{count}</b> 段</h3></header>
          <CountdownTimer storageKey={'kw-study-timer:'+profile.id} title="专注计时" label="学习小屋" presets={FOCUS} defaultMinutes={25} onFinish={finished} finishText={note||'时间到了。'}/>
          <p className="micro-copy">计时只在本机记录，不会自动加分。学完了，<Link className="text-link" to="/system?tab=actions">把真实完成的事交给系统</Link>。</p>
        </section>
        <AmbientPanel storageKey={'kw-study-ambient:'+profile.id}/>
      </div>
    </section>
  </div>
}
