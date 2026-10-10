import {useEffect, useState} from 'react'
import {Link, useSearchParams} from 'react-router-dom'
import {Download, LogOut, RefreshCw, Save, ShieldCheck} from 'lucide-react'
import {useApi, usePagedApi, useCommand, queryClient, displayTime, type Schema, type RecordView, type Page} from '../shared/api/client'
import {number, record, string} from '../shared/json'
import {Badge, Button, ErrorNotice, Field, Form, Modal, Notice, PageTitle, Panel} from '../shared/ui'
import {LoadMore} from '../shared/LoadMore'
import {useApp} from '../app-context'
import {JobStatus} from './Agent'
import {ShiyiSettings} from './Shiyi'

function ProviderEditor({config}: {config?: Schema<'ProviderView'>}) {
  const [url,setUrl]=useState(config?.base_url||''),[model,setModel]=useState(config?.model||'')
  const [credential,setCredential]=useState('key'),[secret,setSecret]=useState(''),[envName,setEnvName]=useState('AI_CHAT_API_KEY')
  const [limit,setLimit]=useState(number(config?.capabilities.daily_request_limit,100)),[job,setJob]=useState<string|null>(null),[saved,setSaved]=useState(false)
  const [models,setModels]=useState<Schema<'ModelOption'>[]>([]),[loaded,setLoaded]=useState(false)
  const cmd=useCommand(),discovery=useCommand<Schema<'ModelList'>>()
  const busy=cmd.isPending||discovery.isPending
  function resetModels(){setModels([]);setLoaded(false);setModel('');setSaved(false);discovery.reset()}
  async function loadModels(){
    setLoaded(false);setModels([])
    try{
      const result=await discovery.mutateAsync({path:'/providers/chat/models',body:{base_url:url,expected_version:config?.version||0,
        ...(credential==='env'?{secret_env:envName}:secret?{api_key:secret}:{})}})
      setModels(result.models);setLoaded(true);setModel(result.models.some(item=>item.id===model)?model:'')
    }catch{}
  }
  return <Panel title="系统 Agent · 文本服务" action={<Badge label={config?.enabled?'服务测试已通过':config?'等待服务测试':'尚未配置'}/>}>
    <Form onSubmit={async()=>{try {
      await cmd.mutateAsync({path:'/providers/chat',method:'PUT',body:{base_url:url,model,expected_version:config?.version||0,
        ...(credential==='env'?{secret_env:envName}:secret?{api_key:secret}:{}),capabilities:{daily_request_limit:limit,structured_output:true}}})
      setSecret('');setSaved(true)
    } catch {}}}>
      <Field label="API Base URL" hint="服务商的 HTTP 或 HTTPS 接口根地址，通常以 /v1 结尾。"><input type="url" disabled={busy} value={url} onChange={e=>{setUrl(e.target.value);resetModels()}} placeholder="https://api.example.com/v1" required/></Field>
      <Field label="凭据保存方式"><select disabled={busy} value={credential} onChange={e=>{setCredential(e.target.value);resetModels()}}><option value="key">本机系统凭据库</option><option value="env">服务端环境变量</option></select></Field>
      {credential==='key'?<Field label="API Key" hint={config?.has_secret?'同一服务可留空使用已保存凭据；换地址时请填写新 Key。':'填写后拉取模型，保存配置后不回显。'}><input type="password" disabled={busy} autoComplete="new-password" value={secret} onChange={e=>{setSecret(e.target.value);resetModels()}}/></Field>:<Field label="环境变量名称" hint="在运行 API 和 Worker 的服务端配置变量值。"><input disabled={busy} value={envName} onChange={e=>{setEnvName(e.target.value);resetModels()}} pattern="AI_[A-Z0-9_]+" required/></Field>}
      <div><Button type="button" kind="secondary" busy={discovery.isPending} disabled={cmd.isPending||!url.trim()} onClick={()=>void loadModels()}><RefreshCw size={16}/>{loaded?'刷新模型列表':'拉取模型'}</Button></div>
      <Field label="选择模型" hint={loaded?`已读取 ${models.length} 个模型；选择后保存并测试能力。`:'先填写服务地址与凭据，再拉取模型列表。'}><select disabled={!loaded||busy} value={model} onChange={e=>{setModel(e.target.value);setSaved(false)}} required><option value="">请选择模型</option>{!loaded&&model&&<option value={model}>{model}（当前已保存）</option>}{models.map(item=><option key={item.id} value={item.id}>{item.id}</option>)}</select></Field>
      {loaded&&!models.length&&<Notice>该服务没有返回可用模型，请检查地址、凭据权限后重新拉取。</Notice>}
      <ErrorNotice error={discovery.error}/>
      <Field label="每日请求额度"><input type="number" min={1} max={10000} value={limit} onChange={e=>setLimit(Number(e.target.value))} required/></Field>
      <div className="core-actions"><Button type="submit" busy={cmd.isPending} disabled={discovery.isPending||!loaded||!models.some(item=>item.id===model)}><Save size={16}/>保存配置</Button><Button type="button" kind="secondary" disabled={!config?.has_secret||discovery.isPending} busy={cmd.isPending} onClick={async()=>{try {const result=await cmd.mutateAsync({path:'/providers/chat/test'});setJob(result.job_id)} catch {}}}>测试所配置的服务</Button></div>
      {saved&&<p role="status" className="success-text">配置已保存，测试通过后用于系统判定和对话。</p>}
      <small className="muted">服务测试会调用结构化回复、流式工具和续答，通常 3 次，格式修复最多再调用 1 次；可能使用服务商额度。</small>
      <ErrorNotice error={cmd.error}/>{job&&<JobStatus id={job}/>}
    </Form>
  </Panel>
}

const editableRules={
  'system.daily_positive_action_cap':'每天行动奖励总上限','system.max_award_per_action':'单项行动奖励上限',
  'system.daily_penalty_cap':'每天扣罚总上限','system.max_penalty_per_action':'单项行动扣罚上限',
}
function RulesEditor(){
  const data=useApi<Schema<'RulesView'>>('/rules'),cmd=useCommand(),[changes,setChanges]=useState<Record<string,number>>({}),[saved,setSaved]=useState(false)
  return <Panel title="积分规则" action={<Badge label={string(data.data?.rules.version,'读取中')}/>}>
    <p>发布后使用新规则。已接受的任务、合约和订单继续引用原版本；签到条款在系统的签到卡中设置。</p>
    <Form onSubmit={async()=>{try {await cmd.mutateAsync({path:'/rules/versions',body:{based_on_version:data.data?.rules.version,changes}});setChanges({});setSaved(true)} catch {}}}>
      <div className="two-columns">{Object.entries(editableRules).map(([path,label])=><Field key={path} label={label}><input type="number" min={0} max={10000} value={changes[path]??number(record(data.data?.rules.system)[path.split('.')[1]])} onChange={e=>{setChanges({...changes,[path]:Number(e.target.value)});setSaved(false)}} required/></Field>)}</div>
      <Button type="submit" busy={cmd.isPending} disabled={!Object.keys(changes).length}>发布新的规则版本</Button>{saved&&<p className="success-text" role="status">规则已发布。</p>}<ErrorNotice error={data.error||cmd.error}/>
    </Form><details><summary>完整生效规则</summary><pre className="code-block">{JSON.stringify(data.data?.rules,null,2)}</pre></details>
  </Panel>
}
function PenaltyRules(){
  const data=useApi<Schema<'PenaltyRule'>[]>('/system/penalty-rules'),cmd=useCommand(),[title,setTitle]=useState(''),[condition,setCondition]=useState(''),[points,setPoints]=useState(10)
  return <Panel title="我授权的扣罚规则"><p>启用后从下一业务日生效。只有能核对到具体事实时才可判罚，余额与每日上限仍由系统检查。</p>
    <div className="record-list">{data.data?.map(rule=><article key={rule.id}><div><strong>{rule.title} · 最多 {rule.points} 积分</strong><p>{rule.condition}</p><small>{rule.effective_date} 生效</small></div>{rule.disabled_at?<Badge label="已关闭"/>:<Button kind="quiet" busy={cmd.isPending} onClick={()=>cmd.mutate({path:'/system/penalty-rules/'+rule.id,method:'DELETE'})}>关闭此规则</Button>}</article>)}</div>
    <details><summary>授权一条新的具体罚则</summary><Form onSubmit={async()=>{try {await cmd.mutateAsync({path:'/system/penalty-rules',body:{title,condition,points}});setTitle('');setCondition('')} catch {}}}>
      <Field label="规则名称"><input value={title} onChange={e=>setTitle(e.target.value)} required maxLength={200}/></Field><Field label="触发条件" hint="明确写出什么行为、满足哪些事实才扣罚。"><textarea value={condition} onChange={e=>setCondition(e.target.value)} required maxLength={2000}/></Field><Field label="每次最多扣罚积分"><input type="number" min={0} max={100} value={points} onChange={e=>setPoints(Number(e.target.value))} required/></Field><Button type="submit" busy={cmd.isPending}>授权此规则，明日起生效</Button></Form></details><ErrorNotice error={data.error||cmd.error}/>
  </Panel>
}
function Adjustments(){
  const cmd=useCommand<Schema<'AdjustmentReceipt'>>(),[points,setPoints]=useState(0),[reason,setReason]=useState(''),[pending,setPending]=useState<{points:number;reason:string;command_key:string}|null>(null),[receipt,setReceipt]=useState<Schema<'AdjustmentReceipt'>|null>(null)
  return <Panel title="明确调整积分"><p>用于用户确认的补记或纠错，保留理由和独立流水。直接调整不计入对赌进度，也不作为系统自动判定。</p>
    <Form onSubmit={()=>setPending({points,reason,command_key:crypto.randomUUID()})}><div className="two-columns"><Field label="调整积分（负数为扣减）"><input type="number" min={-10000} max={10000} value={points} onChange={e=>setPoints(Number(e.target.value))} required/></Field><Field label="调整原因"><input value={reason} onChange={e=>setReason(e.target.value)} minLength={3} maxLength={1000} required/></Field></div><Button type="submit" kind="secondary" disabled={!points}>核对这笔调整</Button></Form>
    {receipt&&<p role="status">调整已入账。<Link to={'/ledger?receipt='+receipt.ledger_entry_ids[0]}>查看正式回执</Link></p>}
    {pending&&<Modal title="确认手动调整" onClose={()=>setPending(null)}><div className="form"><p>{pending.points>0?'增加':'扣减'} {Math.abs(pending.points)} 积分</p><p>{pending.reason}</p><Button busy={cmd.isPending} onClick={async()=>{try {setReceipt(await cmd.mutateAsync({path:'/system/adjustments',body:pending,key:pending.command_key}));setPending(null);setReason('');setPoints(0)} catch {}}}>确认这笔积分调整</Button><ErrorNotice error={cmd.error}/></div></Modal>}
  </Panel>
}
function Skills(){
  const data=useApi<Schema<'SkillDirectory'>>('/settings/skills'),cmd=useCommand()
  const statusText:Record<Schema<'SkillView'>['status'],string>={ready:'已就绪，可在系统对话中调用',disabled:'已关闭；已有对赌合约继续履行',not_configured:'尚未配置连接，请在下方填写拾忆地址和 Key',missing_credentials:'尚无可用凭据，请在下方补充',needs_check:'连接尚未通过检查，请在下方检查并启用',connection_error:'连接检查失败，请查看下方原因并重试'}
  return <><Panel title="系统的能力"><div className="preference-list">{data.data?.skills.map(skill=><label key={skill.skill}><div><strong>{skill.skill==='wager'?'对赌 Skill':'拾忆只读 Skill'}</strong><small>{skill.skill==='wager'?'关闭后不再提出或接受新对赌，已有合约继续履行和结算。':'按需查询外部学习事实，来源保留；读取本身不发积分。'}</small><small role="status">{statusText[skill.status]}</small></div><input type="checkbox" checked={skill.enabled} disabled={cmd.isPending} onChange={e=>cmd.mutate({path:'/settings/skills',method:'PATCH',body:{skill:skill.skill,enabled:e.target.checked,expected_version:skill.version}})}/></label>)}</div><ErrorNotice error={cmd.error||data.error}/></Panel><ShiyiSettings/></>
}
function LegacyOrders(){
  const data=usePagedApi<Schema<'LegacyOrder'>>('/maintenance/legacy-orders'),cmd=useCommand(),[closing,setClosing]=useState<Schema<'LegacyOrder'>|null>(null),[reason,setReason]=useState('')
  if(!data.data?.items.length&&!data.error)return null
  return <Panel title="旧订单与收藏"><p>已交付的作品可以下载。结果不明的外部请求保持原预留，核对后可明确结束尝试并退回站内积分。</p><div className="record-list">{data.data?.items.map(order=><article key={order.id}><div><strong>{order.name}</strong><small>{displayTime(order.created_at)} · {order.price_points} 积分 · {order.rule_version}</small></div><Badge state={order.state}/>{order.asset_id&&<a className="button secondary" href={'/api/v1/assets/'+order.asset_id+'/file'}>下载原作品</a>}{order.ledger_entry_ids[0]&&<Link to={'/ledger?receipt='+order.ledger_entry_ids[0]}>原始流水</Link>}{order.can_close&&<Button kind="secondary" onClick={()=>{setClosing(order);setReason('')}}>核对并结束尝试</Button>}</article>)}</div><LoadMore query={data}/><ErrorNotice error={data.error}/>
    {closing&&<Modal title="结束旧订单的这次尝试" onClose={()=>setClosing(null)}><Form onSubmit={async()=>{try {await cmd.mutateAsync({path:'/maintenance/legacy-orders/'+closing.id+'/close',body:{expected_version:closing.version,reason}});setClosing(null)} catch {}}}><p>将退回此订单预留的 {closing.price_points} 积分。服务商侧费用和结果需要另行核对，此操作不表示服务商退款。</p><Field label="核对说明"><textarea value={reason} onChange={e=>setReason(e.target.value)} minLength={3} required maxLength={1000}/></Field><Button type="submit" busy={cmd.isPending}>结束尝试并退回站内积分</Button><ErrorNotice error={cmd.error}/></Form></Modal>}
  </Panel>
}
function Maintenance(){
  const backups=useApi<Page<RecordView>>('/backups',5000),diagnostics=useApi('/diagnostics'),jobs=usePagedApi<Schema<'BackgroundJob'>>('/jobs',5000),cmd=useCommand()
  const [job,setJob]=useState<string|null>(null),[preview,setPreview]=useState<RecordView|null>(null),[restoreQueued,setRestoreQueued]=useState(false)
  async function preflight(file:File){const form=new FormData();form.append('file',file);try {setPreview(await cmd.mutateAsync({path:'/restore-previews',body:form}))} catch {}}
  return <><Panel title="我的数据与历史"><p>导出积分流水、系统与游戏记录，或保留完整历史资料。迁移整个家园请使用备份。</p><div className="core-actions"><a className="button secondary" href="/api/v1/exports?format=csv&scope=ledger"><Download size={16}/>账本 CSV</a><a className="button secondary" href="/api/v1/exports?format=json&scope=all"><Download size={16}/>全部数据 JSON</a><a className="text-link" href="/api/v1/exports?format=md&scope=learning">旧资料 Markdown</a></div></Panel>
    <Panel title="备份与恢复" action={<Button busy={cmd.isPending} onClick={async()=>{try {const result=await cmd.mutateAsync({path:'/backups'});setJob(result.job_id)} catch {}}}><ShieldCheck size={16}/>创建完整备份</Button>}><p>包含世界、系统、原历史与附件，并校验内容哈希；登录会话和 AI 凭据不进入备份。</p>{job&&<JobStatus id={job}/>}
      <div className="record-list">{backups.data?.items.map(b=><article key={b.id}><div><strong>{displayTime(b.created_at)}</strong><small>{b.size_bytes?(b.size_bytes/1024/1024).toFixed(2)+' MB':'正在保存'}</small></div><Badge state={b.state}/>{b.state==='ready'&&<a className="button secondary" href={'/api/v1/backups/'+b.id+'/file'}><Download size={16}/>下载</a>}</article>)}</div>
      <Field label="从备份包恢复" hint="先校验文件和账本，再显示备份内容供你确认。"><input type="file" accept=".zip" disabled={cmd.isPending} onChange={e=>{const file=e.target.files?.[0];if(file)void preflight(file);e.target.value=''}}/></Field>{restoreQueued&&<Notice>恢复任务已提交。完成后请刷新并用备份中的账户密码登录，AI 凭据需要重新配置。</Notice>}
    </Panel><LegacyOrders/><Panel title="后台任务与恢复"><div className="core-records">{jobs.data?.items.map(j=><article key={j.id} className="core-record"><strong>{({agent_turn:'系统对话',system_assess:'行动判定',battle:'远征战斗',assess:'原合约事实评估',grade:'原合约回答判定',backup:'备份',restore:'恢复',shiyi_check:'拾忆连接检查',provider_test:'服务测试'} as Record<string,string>)[j.kind]||'历史任务'}</strong><small>{displayTime(j.created_at)}</small><JobStatus id={j.id}/></article>)}</div><LoadMore query={jobs}/></Panel>
    <Panel title="运行诊断" action={<Button kind="quiet" onClick={()=>void diagnostics.refetch()}><RefreshCw size={15}/>重新核对</Button>}><dl className="diagnostic-list"><dt>SQLite</dt><dd>{diagnostics.data?.sqlite_version}</dd><dt>数据库日志</dt><dd>{diagnostics.data?.journal_mode}</dd><dt>迁移版本</dt><dd>{diagnostics.data?.schema_version}</dd></dl><pre className="code-block">{JSON.stringify(diagnostics.data?.reconciliation,null,2)}</pre></Panel><ErrorNotice error={cmd.error||backups.error||jobs.error||diagnostics.error}/>
    {preview&&<Modal title="确认恢复这份备份" onClose={()=>setPreview(null)}><div className="form"><Notice>将用此备份替换当前世界。系统先保留当前数据库用于故障回退，所有设备需要重新登录。</Notice><dl className="diagnostic-list"><dt>备份时间</dt><dd>{displayTime(preview.manifest.created_at)}</dd><dt>附件</dt><dd>{preview.manifest.files.length} 个</dd><dt>版本</dt><dd>{preview.manifest.schema_version}</dd><dt>预检</dt><dd>内容哈希、数据库完整性与外键已核对</dd></dl><Button kind="danger-button" busy={cmd.isPending} onClick={async()=>{try {await cmd.mutateAsync({path:'/restores',body:{preview_token:preview.preview_token}});setPreview(null);setRestoreQueued(true)} catch {}}}>使用此备份恢复当前世界</Button><ErrorNotice error={cmd.error}/></div></Modal>}
  </>
}
const preferences=[
  ['reduced_motion','减少动态效果','用简短淡入与静态前后对照呈现结果。'],['sound_enabled','演出声音','奖励、召唤与战斗的轻声提示。'],
  ['auto_camera','自动运镜','收到结果后允许镜头缓缓靠近；可随时手动接管。'],['world_daylight','默认日光漫游','打开家园时使用日光。'],['notifications','站内通知','接收结算、到点和待处理提醒。'],
] as const
export default function SettingsPage(){
  const {profile,isTest}=useApp(),data=useApi<Schema<'AppSettings'>>('/settings',5000),cmd=useCommand(),[search,setSearch]=useSearchParams(),tab=search.get('tab')||'account'
  const [name,setName]=useState(profile.display_name),[timezone,setTimezone]=useState(profile.pending_timezone||profile.timezone),[saved,setSaved]=useState(false)
  useEffect(()=>{setName(profile.display_name);setTimezone(profile.pending_timezone||profile.timezone)},[profile.id,profile.version])
  return <div className="core-page"><PageTitle eyebrow="MAKE THIS WORLD YOURS" title="把世界，调成喜欢的样子。" description="账户、系统能力与每一份记录，都在这里。"/>
    <div className="core-tabs">{[['account','账户与偏好'],['providers','AI 服务'],['integrations','Skill'],['rules','规则与积分'],['maintenance','数据与运行']].map(([value,label])=><button key={value} className={tab===value?'active':''} onClick={()=>setSearch({tab:value})}>{label}</button>)}</div>
    {tab==='account'&&<><Panel title="个人账户"><Form onSubmit={async()=>{try {await cmd.mutateAsync({path:'/me',method:'PATCH',body:{display_name:name,...(timezone!==profile.timezone?{timezone}:{}),expected_version:profile.version}});setSaved(true)} catch {}}}><div className="two-columns"><Field label="你的称呼"><input value={name} onChange={e=>{setName(e.target.value);setSaved(false)}} required maxLength={40}/></Field><Field label="账户时区" hint="更改从原时区的下一业务日生效；签到、合约和历史日期保留原条款。"><input value={timezone} onChange={e=>{setTimezone(e.target.value);setSaved(false)}} required list="timezones"/><datalist id="timezones">{['Asia/Shanghai','Asia/Tokyo','Europe/London','America/New_York'].map(t=><option key={t}>{t}</option>)}</datalist></Field></div>{profile.pending_timezone&&<Notice>{profile.pending_timezone} 将从 {profile.timezone_effective_date} 生效。</Notice>}<Button type="submit" busy={cmd.isPending}>保存账户设置</Button>{saved&&<p role="status" className="success-text">设置已保存。</p>}</Form></Panel>
      <Panel title="舒服地留在这里"><div className="preference-list">{preferences.map(([key,title,note])=><label key={key}><div><strong>{title}</strong><small>{note}</small></div><input type="checkbox" checked={profile.preferences[key]} disabled={cmd.isPending} onChange={e=>cmd.mutate({path:'/settings',method:'PATCH',body:{[key]:e.target.checked,expected_version:profile.version}})}/></label>)}</div><Field label="场景画质"><select value={profile.preferences.graphics_quality??''} onChange={e=>cmd.mutate({path:'/settings',method:'PATCH',body:{graphics_quality:e.target.value,expected_version:profile.version}})}><option value="" disabled>按设备自动选择</option><option value="high">精细</option><option value="medium">均衡</option><option value="low">节能</option></select></Field></Panel>
      <Panel title="登录会话"><div className="core-actions"><Button kind="secondary" busy={cmd.isPending} onClick={()=>cmd.mutate({path:'/auth/revoke-others'})}><ShieldCheck size={16}/>撤销其他设备会话</Button><Button kind="quiet" onClick={async()=>{try {await cmd.mutateAsync({path:'/auth/logout'});queryClient.clear();window.location.assign('/')} catch {}}}><LogOut size={16}/>退出登录</Button></div></Panel></>}
    {tab==='providers'&&<>{isTest&&<Notice>当前是隔离开发测试适配器，输出不是正式 AI 接入证据。</Notice>}<ProviderEditor key={data.data?.providers.find(p=>p.role==='chat')?.id||'new'} config={data.data?.providers.find(p=>p.role==='chat')}/></>}
    {tab==='integrations'&&<Skills/>}{tab==='rules'&&<><RulesEditor/><PenaltyRules/><Adjustments/></>}{tab==='maintenance'&&<Maintenance/>}<ErrorNotice error={data.error||cmd.error}/>
  </div>
}
