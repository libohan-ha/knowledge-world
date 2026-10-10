import type {Schema} from './api/client'
import {displayTime, useCommand} from './api/client'
import {useApp} from '../app-context'
import {Button, ErrorNotice, Modal, Notice, Stat} from './ui'
import {record,number} from './json'

export function QuoteDialog({quote,onClose,onComplete}:{quote:Schema<'QuoteResult'>;onClose:()=>void;onComplete?:(receipt:Schema<'CommandReceipt'>)=>void}) {
  const {wallet}=useApp(),command=useCommand<Schema<'CommandReceipt'>>()
  const prefix=quote.operation==='leisure'?'/rewards':quote.operation.startsWith('home_')?'/world/home':'/roster'
  const stats=quote.after.attributes?['strength','agility','mana'] as const:[]
  return <Modal title="确认这次选择" onClose={onClose}><div className="form"><span className="eyebrow">YOUR NEXT LITTLE STEP</span><h3>{quote.name}</h3><div className="quote-price"><strong>{quote.price_points}</strong><span>积分</span></div><p>可用 {wallet.available_points} 积分 · 已预留 {wallet.held_points}</p>{quote.operation==='leisure'?<Notice>兑换后预留 {quote.price_points} 积分，首次开始时消费。未开始可原价退回；暂停保留剩余时长。</Notice>:<p>确认后完成这次{quote.operation==='monster_recruit'?'招募':quote.operation.includes('train')?'培养':'家园变更'}，并保存正式回执。</p>}{stats.length>0&&<div className="core-grid">{stats.map(k=><Stat key={k} label={{strength:'力量',agility:'敏捷',mana:'法力'}[k]} value={`${number(record(quote.before.attributes)[k])} → ${number(record(quote.after.attributes)[k])}`}/>)}</div>}{quote.before.level!==undefined&&<p>等级 {number(quote.before.level)} → {number(quote.after.level)}</p>}{quote.operation==='leisure'&&<p>本次权益 {number(quote.after.duration_seconds)/60} 分钟</p>}<small className="muted">报价有效至 {displayTime(quote.expires_at)}</small><Button busy={command.isPending} disabled={wallet.available_points<quote.price_points} onClick={async()=>{try{const result=await command.mutateAsync({path:prefix+'/orders',body:{quote_token:quote.quote_token},key:quote.quote_id});onComplete?.(result);onClose()}catch{}}}>{wallet.available_points<quote.price_points?'可用积分不足':`确认${quote.operation==='leisure'?'兑换':'执行'} · ${quote.price_points} 积分`}</Button><ErrorNotice error={command.error}/></div></Modal>
}
