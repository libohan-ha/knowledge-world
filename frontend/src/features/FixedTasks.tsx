import {useRef,useState} from 'react'
import {Check,PenLine,Plus,Trash2} from 'lucide-react'
import {useApi,useCommand,type Schema} from '../shared/api/client'
import {Button,Empty,ErrorNotice,Field,Form,Modal,Panel} from '../shared/ui'

export default function FixedTasks(){
  const tasks=useApi<Schema<'FixedTask'>[]>('/system/fixed-tasks'),command=useCommand(),complete=useCommand<Schema<'FixedTaskReceipt'>>()
  const [editing,setEditing]=useState<Schema<'FixedTask'>|null|false>(false),[title,setTitle]=useState(''),[description,setDescription]=useState(''),[points,setPoints]=useState(10),[removing,setRemoving]=useState<Schema<'FixedTask'>|null>(null),[receipt,setReceipt]=useState<Schema<'FixedTaskReceipt'>|null>(null)
  const keys=useRef(new Map<string,string>()),busy=useRef(false)
  function edit(task?:Schema<'FixedTask'>){setEditing(task||null);setTitle(task?.title||'');setDescription(task?.description||'');setPoints(task?.reward_points??10)}
  async function report(task:Schema<'FixedTask'>){
    if(busy.current)return
    busy.current=true
    const storage='kw-fixed-completion:'+task.id
    const key=keys.current.get(task.id)||localStorage.getItem(storage)||crypto.randomUUID();keys.current.set(task.id,key);localStorage.setItem(storage,key)
    try{setReceipt(await complete.mutateAsync({path:`/system/fixed-tasks/${task.id}/complete`,body:{completion_id:key},key}));keys.current.delete(task.id);localStorage.removeItem(storage)}catch{}finally{busy.current=false}
  }
  return <><div className="core-header"><div><h2>固定任务</h2><p>保存常做的事情，完成后直接汇报。每次新的完成按保存的积分发奖。</p></div><Button onClick={()=>edit()}><Plus size={17}/>添加固定任务</Button></div>
    <div className="core-grid">{tasks.data?.map(task=><Panel key={task.id} className="core-card fixed-task" title={task.title}><p className="card-summary">{task.description||'完成一次，记录一次。'}</p><strong>+{task.reward_points} 积分 / 次</strong><div className="core-actions"><Button busy={complete.isPending} onClick={()=>void report(task)}><Check size={17}/>已完成，汇报</Button><Button kind="quiet" aria-label={'修改任务 '+task.title} onClick={()=>edit(task)}><PenLine size={16}/></Button><Button kind="quiet" aria-label={'删除任务 '+task.title} onClick={()=>setRemoving(task)}><Trash2 size={16}/></Button></div></Panel>)}</div>
    {tasks.data?.length===0&&<Panel><Empty title="把常做的事情留下来">复习错题、整理 A4 纸、背作文……名称与每次积分由你设定。</Empty></Panel>}
    <ErrorNotice error={tasks.error||complete.error||command.error}/>
    {receipt&&<Panel className="core-card" title="这次完成已记录"><p>{receipt.title} · +{receipt.awarded_points} 积分，当前可用 {receipt.wallet.available_points} 积分。</p><Button kind="quiet" onClick={()=>setReceipt(null)}>知道了</Button></Panel>}
    {editing!==false&&<Modal title={editing?'修改固定任务':'添加固定任务'} onClose={()=>setEditing(false)}><Form onSubmit={async()=>{try{await command.mutateAsync({path:'/system/fixed-tasks'+(editing?'/'+editing.id:''),method:editing?'PATCH':'POST',body:{title,description,reward_points:points,...(editing?{expected_version:editing.version}:{})}});setEditing(false)}catch{}}}><Field label="固定任务名称"><input required maxLength={200} value={title} onChange={e=>setTitle(e.target.value)}/></Field><Field label="完成标准"><textarea maxLength={4000} rows={3} value={description} onChange={e=>setDescription(e.target.value)}/></Field><Field label="每次完成积分"><input required type="number" min={0} max={200} value={points} onChange={e=>setPoints(Number(e.target.value))}/></Field><p>保存后，你的完成汇报会直接按此积分结算；请只汇报真实完成，已在此结算的同次行动无需重复向 AI 申请积分。</p><Button type="submit" busy={command.isPending}>保存任务与积分</Button><ErrorNotice error={command.error}/></Form></Modal>}
    {removing&&<Modal title="删除固定任务" onClose={()=>setRemoving(null)}><p>删除“{removing.title}”？已有完成记录和积分回执会保留。</p><div className="core-actions"><Button kind="secondary" onClick={()=>setRemoving(null)}>保留任务</Button><Button busy={command.isPending} onClick={async()=>{try{await command.mutateAsync({path:'/system/fixed-tasks/'+removing.id,method:'DELETE',body:{expected_version:removing.version}});setRemoving(null)}catch{}}}>确认删除</Button></div><ErrorNotice error={command.error}/></Modal>}
  </>
}
