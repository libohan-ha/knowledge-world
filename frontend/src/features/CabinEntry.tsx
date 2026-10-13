import {Link} from 'react-router-dom'
import {Armchair} from 'lucide-react'
import {useApi,type Schema} from '../shared/api/client'
import {formatDuration} from './world/LeisureRoom'

/** The reward in use, if any: running first, then paused. */
export function activeTicket(tickets:Schema<'LeisureTicket'>[]|undefined){return tickets?.find(t=>t.state==='running')||tickets?.find(t=>t.state==='paused')}

/** A doorway into the cabin while a reward is being used. */
export function CabinEntry({variant='banner'}:{variant?:'banner'|'pill'}){
  const tickets=useApi<Schema<'LeisureTicket'>[]>('/leisure',15000),ticket=activeTicket(tickets.data)
  if(!ticket)return null
  const label=ticket.state==='running'?'正在享受':'暂停中'
  if(variant==='pill')return <Link className="cabin-pill" to={'/leisure/'+ticket.id} title={`${label}：${ticket.snapshot.name}`}><Armchair size={15}/><span>小屋</span><small>{formatDuration(ticket.remaining_seconds)}</small></Link>
  return <Link className={'cabin-entry is-'+ticket.state} to={'/leisure/'+ticket.id}><span className="cabin-entry-icon"><Armchair size={22}/></span><span className="cabin-entry-copy"><small>{label} · 剩余 {formatDuration(ticket.remaining_seconds)}</small><strong>{ticket.snapshot.name}</strong></span><span className="button">进入小屋</span></Link>
}
