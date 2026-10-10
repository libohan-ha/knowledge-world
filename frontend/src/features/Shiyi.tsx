import {useEffect, useState} from 'react'
import {ExternalLink, RefreshCw, Save} from 'lucide-react'
import {displayTime, useApi, useCommand, type Schema} from '../shared/api/client'
import {Badge, Button, ErrorNotice, Field, Form, Notice, Panel} from '../shared/ui'
import {JobStatus} from './Agent'
type Connection = Schema<'ShiyiConnection'>
type ConnectionResult = Schema<'ShiyiConnectionResult'>
const base='/integrations/shiyi'
const errors:Record<string,string>={SHIYI_NOT_CONFIGURED:'尚未配置拾忆凭据',SHIYI_AUTH_FAILED:'凭据无效',SHIYI_SCOPE_MISSING:'凭据缺少 read 权限',SHIYI_UNAVAILABLE:'暂时无法连接源站',SHIYI_TIMEOUT:'读取超时',SHIYI_RATE_LIMITED:'源站暂时限流'}
function useConnection(){const query=useApi<ConnectionResult>(base);return {...query,connection:query.isError?null:query.data?.connection}}
function SiteLink({connection}:{connection:Connection}){return <a className="text-link" href={connection.api_url.replace(/\/api\/v1\/?$/,'/')} target="_blank" rel="noopener noreferrer">打开拾忆 <ExternalLink size={14}/></a>}
export function ShiyiSettings() {
  const data = useConnection()
  if (data.isLoading) return <Panel title="拾忆连接"><p role="status">正在读取连接设置…</p></Panel>
  return <><ErrorNotice error={data.error}/><ShiyiEditor connection={data.connection}/></>
}

function ShiyiEditor({connection}: {connection?: Connection | null}) {
  const [url, setUrl] = useState(connection?.api_url || '')
  const [mode, setMode] = useState('key'), [key, setKey] = useState(''), [env, setEnv] = useState('SHIYI_API_KEY')
  const [enabled, setEnabled] = useState(!!connection?.enabled), [newAccount, setNewAccount] = useState(false)
  const [job, setJob] = useState<string | null>(null), [saved, setSaved] = useState(false)
  const command = useCommand<ConnectionResult>()
  useEffect(() => {setEnabled(!!connection?.enabled)}, [connection?.enabled])
  return <Panel title="拾忆 · 外部只读 Skill" action={<Badge label={connection?.readable ? '拾忆可读取' : connection ? '未启用 / 待检查' : '尚未连接'}/>} className="shiyi-settings">
    <p>系统可以通过 Skill 按需查询拾忆，保留原始来源。题库和复习仍在拾忆完成。</p>
    <Form onSubmit={async () => {try {
      const result = await command.mutateAsync({path: base, method: 'PUT', body: {
        api_url: url, enabled, expected_version: connection?.version || 0, new_connection: newAccount,
        ...(mode === 'env' ? {secret_env: env} : key ? {api_key: key} : {}),
      }})
      setKey(''); setJob(result.job_id || null); setSaved(true); setNewAccount(false)
    } catch {}}}>
      <Field label="拾忆网站地址" hint="填写拾忆根地址或 /api/v1 地址，支持你配置的局域网 HTTP 服务。"><input type="url" value={url} onChange={e => {setUrl(e.target.value); setSaved(false)}} placeholder="http://127.0.0.1:8765/" maxLength={2048} required/></Field>
      <Field label="拾忆凭据保存方式"><select value={mode} onChange={e => setMode(e.target.value)}><option value="key">保存到本机系统凭据库</option><option value="env">引用服务端环境变量</option></select></Field>
      {mode === 'key' ? <Field label="拾忆 API Key" hint={connection?.has_key && !newAccount ? '已有凭据，留空保留。只需 read 权限；保存后不会回显。' : '在拾忆「偏好与连接 → API 连接」创建具有 read 权限的密钥。'}><input type="password" autoComplete="new-password" value={key} onChange={e => setKey(e.target.value)} placeholder={connection?.has_key && !newAccount ? '已保存 · 不回显' : '仅需读取权限'}/></Field> : <Field label="拾忆环境变量名称" hint="在运行 API 和 Worker 的服务端设置该变量；这里只保存名称。"><input value={env} onChange={e => setEnv(e.target.value)} pattern="SHIYI_[A-Z0-9_]+" required/></Field>}
      <label className="check-label"><input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)}/>启用拾忆读取（保存后检查连接）</label>
      {connection && <label className="check-label"><input type="checkbox" checked={newAccount} onChange={e => setNewAccount(e.target.checked)}/>这次连接到另一个拾忆账户</label>}
      {newAccount && <Notice>将为另一账户建立独立来源身份，请填写其凭据。同一账户只换 IP 时保持此项不选。</Notice>}
      <div className="actions"><Button type="submit" busy={command.isPending}><Save size={16}/>保存拾忆连接</Button>
        <Button type="button" kind="secondary" disabled={!connection} busy={command.isPending} onClick={async () => {try {
          const result = await command.mutateAsync({path: base + '/check', body: {expected_version: connection!.version}})
          setJob(result.job_id || null); setSaved(false)
        } catch {}}}><RefreshCw size={15}/>检查并启用</Button>{connection && <SiteLink connection={connection}/>}</div>
      {saved && <p role="status" className="success-text">{job ? '配置已保存，后台正在检查读取能力。' : '配置已保存。'}</p>}
      <ErrorNotice error={command.error}/>{job && <JobStatus id={job}/>}
    </Form>
    {connection && <dl className="diagnostic-list shiyi-diagnostics"><dt>最近检查</dt><dd>{displayTime(connection.checked_at)}</dd><dt>最近成功读取</dt><dd>{displayTime(connection.last_success_at)}</dd><dt>接口能力</dt><dd>{connection.capabilities.agent_api_version ? `Agent API v${connection.capabilities.agent_api_version} · read` : '等待检查'}</dd>{connection.last_error_code && <><dt>连接状态</dt><dd>{errors[connection.last_error_code] || '连接需要重新检查'}</dd></>}</dl>}
    <small className="muted">连接检查只读取健康与概况，不调用 AI。查询不改变拾忆评分、本站积分。<a href="/licenses/shiyi-api-LICENSE.txt" target="_blank" rel="noopener noreferrer">客户端许可</a></small>
  </Panel>
}
