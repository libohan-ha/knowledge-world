import {useEffect,useRef,useState} from 'react'
import {Link,useParams} from 'react-router-dom'
import {ArrowUp,ChevronDown,ClipboardCheck,Maximize2,Pin,Plus,Sparkles,X} from 'lucide-react'
import {api,useApi,usePagedApi,useCommand,queryClient,displayTime,type Schema} from '../shared/api/client'
import {Badge,Button,ErrorNotice,Markdown,Modal,Notice} from '../shared/ui'
import {useApp} from '../app-context'
import {number,string} from '../shared/json'

export function JobStatus({id,onComplete}:{id:string;onComplete?:()=>void}) {
  const job=useApi<Schema<'BackgroundJob'>>('/jobs/'+id,2000),done=useRef(''),command=useCommand()
  useEffect(()=>{if(job.data&&['succeeded','failed','needs_review','cancelled'].includes(job.data.state)&&done.current!==id+job.data.updated_at){done.current=id+job.data.updated_at;void queryClient.invalidateQueries({predicate:q=>q.queryKey[0]!=='shiyi'});onComplete?.()}},[id,job.data?.state,job.data?.updated_at])
  return <div className="job-status"><Badge state={job.data?.state||'queued'}/><span>{string(job.data?.last_error?.message)|| (job.data?.state==='succeeded'?'正式结果已保存。':'输入已保存，可离开页面后继续查看。')}</span>{job.data?.is_test_adapter&&<Badge label="测试适配器"/>}{job.data?.can_retry&&<Button kind="secondary" busy={command.isPending} onClick={()=>command.mutate({path:'/jobs/'+id+'/retry',body:{expected_state:job.data!.state}})}>{job.data.state==='needs_review'?'明确重发此请求':'重试'}</Button>}{job.data?.state==='needs_review'&&job.data.can_retry&&<small>上次外部请求结果不明。明确重发可能再次使用服务商额度。</small>}<ErrorNotice error={command.error||job.error}/></div>
}
function ToolTerms({card}:{card:Schema<'ToolCard'>}) {
  const result=card.result
  if(card.tool_name==='propose_quote')return <><h3>{string(result.name)}</h3><p>价格 {number(result.price_points)} 积分 · 有效至 {displayTime(string(result.expires_at))}</p><p>{result.operation==='leisure'?'兑换时预留，首次开始时消费，未开始可退回。':'确认后按此报价执行并消费积分。'}</p></>
  if(card.tool_name==='propose_challenge')return <><h3>{string(result.title)}</h3><p>{string(result.goal)}</p><p>奖励 {number(result.reward_points)} 积分 · 罚分 {number(result.penalty_points)} 积分</p>{!!result.penalty_condition&&<p>失败条件：{string(result.penalty_condition)}</p>}</>
  return <><h3>{string(result.title)}</h3><p>接受后新增 {number(result.target_points)} 合格积分，押金 {number(result.stake_points)} 积分，成功额外奖励 {number(result.bonus_points)} 积分。</p><p>截止 {displayTime(string(result.deadline_at))}。{card.tool_name==='abandon_wager'?'确认放弃将消费本合约押金。':'成功返还押金与奖金；失败只消费本合约押金。'}</p>{result.legacy_compatibility===true&&<Notice>这是存量合约，继续按接受时的学习口径结算。</Notice>}</>
}
/** One card per proposal: the same entity shown by several tool calls collapses to the newest. */
export function pendingCards(cards:Schema<'ToolCard'>[]|undefined){
  const byKey=new Map<string,Schema<'ToolCard'>>()
  for(const card of cards||[]){const key=card.tool_name+':'+(string(card.result.id)||string(card.result.quote_id)||card.id);byKey.delete(key);byKey.set(key,card)}
  return [...byKey.values()]
}
const cardTitle=(card:Schema<'ToolCard'>)=>string(card.result.title)||string(card.result.name)||'待确认条款'
function TermsTray({cards,open,setOpen,onConfirm,onDecline,busy}:{cards:Schema<'ToolCard'>[];open:boolean;setOpen:(open:boolean)=>void;onConfirm:(card:Schema<'ToolCard'>)=>void;onDecline:(card:Schema<'ToolCard'>)=>void;busy:boolean}){
  if(!cards.length)return null
  return <section className={'terms-tray'+(open?' open':'')} aria-label="待确认条款"><button type="button" className="terms-tray-toggle" aria-expanded={open} onClick={()=>setOpen(!open)}><ClipboardCheck size={16}/><span>待确认条款</span><b className="terms-count">{cards.length}</b>{!open&&<small>{cardTitle(cards.at(-1)!)}</small>}<ChevronDown size={16} className="terms-chevron"/></button>
    {open&&<div className="terms-tray-list">{cards.map(card=><article key={card.id} className="terms-tray-card"><div className="terms-tray-copy"><ToolTerms card={card}/></div><div className="core-actions"><Button kind="secondary" onClick={()=>onConfirm(card)}>核对并确认</Button><Button kind="quiet" busy={busy} onClick={()=>onDecline(card)}>不需要</Button></div></article>)}</div>}
  </section>
}
export function AgentPanel({full=false}:{full?:boolean}) {
  const {profile,threadId,setThreadId,setAgentOpen,isTest}=useApp(),route=useParams(),threads=usePagedApi<Schema<'AgentThread'>>('/system/threads')
  const id=full&&route.threadId?route.threadId:threadId||threads.data?.items[0]?.id
  const thread=useApi<Schema<'AgentThread'>>(id?'/system/threads/'+id:null,3000),command=useCommand<Schema<'MessageReceipt'>>()
  const storage='kw-system-draft:'+profile.id
  const [draft,setDraft]=useState(()=>localStorage.getItem(storage)||''),[error,setError]=useState<unknown>(null),[streamed,setStreamed]=useState(''),[confirm,setConfirm]=useState<Schema<'ToolCard'>|null>(null)
  const messageList=useRef<HTMLDivElement>(null),seen=useRef(new Set<string>()),submitting=useRef(false)
  const active=thread.data?.runs?.find(run=>['queued','running'].includes(run.state))
  useEffect(()=>{if(id&&id!==threadId)setThreadId(id)},[id])
  useEffect(()=>{
    if(!active?.job_id)return
    setStreamed('');seen.current.clear()
    const source=new EventSource('/api/v1/jobs/'+active.job_id+'/events')
    source.addEventListener('agent.text_delta',event=>{const e=event as MessageEvent;if(seen.current.has(e.lastEventId))return;seen.current.add(e.lastEventId);setStreamed(text=>text+string(JSON.parse(e.data).text))})
    for(const type of ['job.completed','job.failed'])source.addEventListener(type,()=>{setStreamed('');void queryClient.invalidateQueries();source.close()})
    return()=>source.close()
  },[active?.job_id])
  useEffect(()=>{
    const list=messageList.current
    if(!list)return
    if(!thread.data?.messages?.length){list.scrollTop=0;return}
    list.scrollTop=list.scrollHeight
  },[id,thread.data?.messages?.length,streamed,thread.data?.actions?.length])
  async function send(){if(!draft.trim()||active||command.isPending||submitting.current)return;submitting.current=true;setError(null);try{let identity=id;if(!identity){const created=await api<Schema<'AgentThread'>>('/system/threads','POST',{title:'与系统的对话',context:{}});identity=created.id;setThreadId(identity)}const key=localStorage.getItem(storage+':key')||crypto.randomUUID();localStorage.setItem(storage+':key',key);const result=await command.mutateAsync({path:'/system/threads/'+identity+'/messages',body:{content:draft,client_message_id:key},key});if(result.state==='needs_configuration')setError(new Error(result.message||'消息已保存，配置 AI 后可继续本次运行。'));setDraft('');localStorage.removeItem(storage);localStorage.removeItem(storage+':key')}catch(e){setError(e)}finally{submitting.current=false}}
  function editDraft(value:string){setDraft(value);localStorage.setItem(storage,value);localStorage.removeItem(storage+':key')}
  async function fresh(){try{const row=await api<Schema<'AgentThread'>>('/system/threads','POST',{title:'新的系统对话',context:{}});setThreadId(row.id);void queryClient.invalidateQueries()}catch(e){setError(e)}}
  const confirmCommand=useCommand(),declineCommand=useCommand()
  const cards=pendingCards(thread.data?.actions),[trayOpen,setTrayOpen]=useState(false),cardCount=useRef(0)
  useEffect(()=>{if(cards.length>cardCount.current)setTrayOpen(true);cardCount.current=cards.length},[cards.length])
  const lastByRun=new Map<string,string>()
  for(const message of thread.data?.messages||[])if(message.role==='assistant'&&message.run_id)lastByRun.set(message.run_id,message.id)
  const chips=(message:Schema<'AgentMessage'>)=>message.run_id&&lastByRun.get(message.run_id)===message.id?cards.filter(card=>card.run_id===message.run_id):[]
  return <div className={'agent-panel '+(full?'full':'')}><div className="agent-heading"><div className="agent-avatar system-avatar"><Sparkles size={24}/></div><div><strong>系统</strong><small><span className="live-dot"/>记录行动，见证每一步成长</small></div><div className="agent-heading-actions"><button className="icon-button" onClick={()=>void fresh()} aria-label="新建系统会话"><Plus size={17}/></button>{!full&&<Link className="icon-button" aria-label="展开系统" to="/system"><Maximize2 size={16}/></Link>}<button className="icon-button" aria-label="关闭系统对话" onClick={()=>setAgentOpen(false)}><X size={18}/></button></div></div>
    {full&&<select aria-label="选择系统会话" value={id||''} onChange={e=>setThreadId(e.target.value)}><option value="">新的对话</option>{threads.data?.items.map(item=><option key={item.id} value={item.id}>{item.title} · {displayTime(item.created_at)}</option>)}</select>}
    <div className="agent-messages" ref={messageList}>{!thread.data?.messages?.length&&<div className="agent-welcome"><span className="tiny-stars">✧　 ✦　 ✧</span><h3>今天，想向前走哪一步？</h3><p>说说已经完成的行动，<br/>或和系统约定下一次挑战。</p><div className="conversation-prompts">{['我今天完成了三公里晨跑和拉伸','帮我提出一个对赌目标','看看我的队伍适合进攻哪里'].map(text=><button key={text} onClick={()=>{setDraft(text);localStorage.setItem(storage,text);localStorage.removeItem(storage+':key')}}>{text}<ArrowUp size={13}/></button>)}</div><div className="agent-config-note"><Sparkles size={15}/><span>AI 未配置时，消息仍会保存。<Link to="/settings?tab=providers">配置服务</Link></span></div></div>}
      {thread.data?.messages?.map(message=><div key={message.id} className={'message '+message.role}><span className="message-author">{message.role==='user'?'我':'系统'} · {displayTime(message.created_at)}</span><Markdown>{message.content_md}</Markdown>{chips(message).map(card=><button type="button" key={card.id} className="terms-chip" onClick={()=>setTrayOpen(true)}><Pin size={13}/>条款「{cardTitle(card)}」已放入下方待确认</button>)}</div>)}
      {streamed&&<div className="message assistant streaming"><Markdown>{streamed}</Markdown></div>}
      {thread.data?.runs?.filter(run=>run.job_id&&!['succeeded','cancelled'].includes(run.state)).map(run=><JobStatus key={run.id} id={run.job_id!}/>)}
    </div><ErrorNotice error={error||thread.error||declineCommand.error}/><TermsTray cards={cards} open={trayOpen} setOpen={setTrayOpen} onConfirm={setConfirm} busy={declineCommand.isPending} onDecline={card=>declineCommand.mutate({path:'/system/actions/'+card.id+'/decline'})}/><form className="agent-composer" onSubmit={e=>{e.preventDefault();void send()}}><textarea aria-label="发送给系统" value={draft} onChange={e=>editDraft(e.target.value)} placeholder="记录行动，提出问题，或和系统约定一件事…" rows={3} onKeyDown={e=>{
      if(e.key!=='Enter'||e.nativeEvent.isComposing||e.nativeEvent.keyCode===229)return
      e.preventDefault()
      if(e.repeat)return
      if(e.ctrlKey||e.shiftKey){const input=e.currentTarget;input.setRangeText('\n',input.selectionStart,input.selectionEnd,'end');editDraft(input.value)}
      else void send()
    }}/><div><small>{isTest?'明确标记的测试适配器':'正式回执后，积分才算到账'}<br/>Enter 发送 · Shift / Ctrl+Enter 换行</small><Button type="submit" busy={command.isPending} disabled={!draft.trim()||!!active} aria-label="发送消息"><ArrowUp size={18}/></Button></div></form>
    {confirm&&<Modal title="核对具体条款" onClose={()=>setConfirm(null)}><div className="form"><ToolTerms card={confirm}/><Button busy={confirmCommand.isPending} onClick={async()=>{try{await confirmCommand.mutateAsync({path:'/system/actions/'+confirm.id+'/confirm',body:{action_hash:confirm.action_hash}});setConfirm(null)}catch{}}}>确认{confirm.tool_name==='abandon_wager'?'放弃并消费押金':confirm.tool_name==='propose_quote'?'此次兑换或培养':'接受条款'}</Button><ErrorNotice error={confirmCommand.error}/></div></Modal>}
  </div>
}
