import {useEffect,useRef} from 'react'
import {Link,useParams} from 'react-router-dom'
import {useApi,type Schema} from '../shared/api/client'
import {ErrorNotice,Loading,PageTitle,Panel} from '../shared/ui'
import {useApp} from '../app-context'
import {JobStatus} from './Agent'
import {BattleReplay} from './world/BattleReplay'

export default function BattlePage(){const {id}=useParams(),{profile}=useApp(),query=useApi<Schema<'Battle'>>(id?'/world/battles/'+id:null,2000);const key=`kw-world-seen:battle:${profile.id}:${profile.display_epoch}:${id}`,autoPlay=useRef(localStorage.getItem(key)!=='1');useEffect(()=>{if(query.data?.result)localStorage.setItem(key,'1')},[query.data?.state]);return <div className="core-page"><PageTitle eyebrow="EXPEDITION REPORT" title={query.data?.snapshot.outpost.name||'远征战报'} description="队伍已经出发，每一个动作都保存在这份战报中。" action={<Link className="button secondary" to="/world?tab=map">回到远征地图</Link>}/>{query.isLoading&&<Loading/>}{query.data&&<>{query.data.state!=='resolved'&&<Panel title="队伍快照已保存"><JobStatus id={query.data.job_id}/></Panel>}<BattleReplay battle={query.data} accountId={profile.id} displayEpoch={profile.display_epoch} reducedMotion={profile.preferences.reduced_motion} autoPlay={autoPlay.current}/></>}<ErrorNotice error={query.error}/></div>}
