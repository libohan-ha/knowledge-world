import React, {Suspense, lazy, useEffect, useRef, useState} from 'react'
import ReactDOM from 'react-dom/client'
import {BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams} from 'react-router-dom'
import {QueryClientProvider} from '@tanstack/react-query'
import {Bell, Compass, Gift, Leaf, Menu, MessageCircle, Moon, Settings, ShieldCheck, Sparkles, Swords, Wallet, X} from 'lucide-react'
import '@fontsource/noto-sans-sc/400.css'
import '@fontsource/noto-sans-sc/500.css'
import '@fontsource/noto-serif-sc/500.css'
import '@fontsource/ibm-plex-mono/400.css'
import tokens from '../../docs/contracts/design-tokens.json'
import {ApiError, queryClient, useApi, useCommand, usePagedApi} from './shared/api/client'
import type {Schema} from './shared/api/client'
import {AppContext} from './app-context'
import {Button, ErrorNotice, Field, Form, Loading, Modal, Notice, useOverlayFocus} from './shared/ui'
import {AgentPanel} from './features/Agent'
import {BackgroundSync} from './shared/BackgroundSync'
import {GameFeedbackProvider} from './shared/GrowthNotice'
import {clearWorldDisplayState} from './shared/world-display-state'
import {LoadMore} from './shared/LoadMore'
import {savePresentationPreferences} from './features/world/presentation-preferences'
import './style.css'
import './finishing.css'
import './redesign.css'

const World = lazy(() => import('./features/World'))
const Roster = lazy(() => import('./features/Roster'))
const Rewards = lazy(() => import('./features/Rewards'))
const System = lazy(() => import('./features/System'))
const BattlePage = lazy(() => import('./features/Battle'))
const Ledger = lazy(() => import('./features/Ledger'))
const SettingsPage = lazy(() => import('./features/Settings'))

function applyTokens() {
  const root = document.documentElement
  for (const [k,v] of Object.entries(tokens.color)) root.style.setProperty('--'+k.replaceAll('_','-'),v)
  for (const [k,v] of Object.entries(tokens.chart)) root.style.setProperty('--chart-'+k,v)
  for (const [k,v] of Object.entries(tokens.font.size_px)) root.style.setProperty('--font-'+k.replaceAll('_','-'),v+'px')
  for (const [k,v] of Object.entries(tokens.font.line_height)) root.style.setProperty('--line-'+k,String(v))
  for (const [k,v] of Object.entries(tokens.radius_px)) root.style.setProperty('--radius-'+k,v+'px')
  for (const [k,v] of Object.entries(tokens.motion_ms)) root.style.setProperty('--motion-'+k.replaceAll('_','-'),v+'ms')
  for (const s of tokens.space_px) root.style.setProperty('--space-'+s,s+'px')
  root.style.setProperty('--font-body-size',tokens.font.size_px.body+'px')
  root.style.setProperty('--font-body',tokens.font.body); root.style.setProperty('--font-display',tokens.font.display)
  root.style.setProperty('--font-numeric',tokens.font.numeric); root.style.setProperty('--nav-width',tokens.layout_px.navigation_width+'px')
  root.style.setProperty('--agent-width',tokens.layout_px.agent_width+'px')
}
applyTokens()

function Welcome({initialized}: {initialized:boolean}) {
  const cmd = useCommand(), navigate = useNavigate()
  const [name,setName] = useState(''), [password,setPassword] = useState(''), [timezone,setTimezone] = useState('Asia/Shanghai')
  async function submit() {
    try {
      await cmd.mutateAsync({path:initialized?'/auth/login':'/setup',body:initialized?{password}:{display_name:name,password,timezone}})
      navigate('/world')
    } catch { /* Inline request error. */ }
  }
  return <main className="welcome-page"><div className="welcome-brand"><Leaf size={25}/><span>知识世界</span><small>YOUR OWN WORLD</small></div><div className="welcome-layout"><div className="welcome-story"><span className="eyebrow">THE SYSTEM IS WAITING</span><h1>今天的你，<br/>会点亮<br/><em>哪一片世界。</em></h1><p>行动被记住，努力成为力量。<br/>和伙伴走进迷雾，也给自己留一段好时光。</p><div className="welcome-illustration v2"><img src="/world-art/hero-island.webp" alt="夜色中亮着灯的营地"/></div></div><section className="welcome-form panel"><span className="eyebrow">{initialized?'WELCOME HOME':'A NEW ADVENTURE'}</span><h2>{initialized?'营地的灯还亮着。':'系统已就绪。'}</h2><p>{initialized?'输入密码，继续你的旅程。':'创建个人账户，领取角色、初始伙伴和你的家园。'}</p><Form onSubmit={submit}>{!initialized&&<Field label="怎么称呼你"><input value={name} onChange={e=>setName(e.target.value)} required maxLength={40} autoComplete="nickname"/></Field>}<Field label="账户密码" hint={initialized?undefined:'至少 8 位，用于保护你的世界与积分记录'}><input type="password" value={password} onChange={e=>setPassword(e.target.value)} required minLength={8} autoComplete={initialized?'current-password':'new-password'}/></Field>{!initialized&&<Field label="所在时区"><select value={timezone} onChange={e=>setTimezone(e.target.value)}>{['Asia/Shanghai','Asia/Tokyo','Europe/London','America/New_York'].map(t=><option key={t}>{t}</option>)}</select></Field>}<ErrorNotice error={cmd.error}/><Button busy={cmd.isPending} type="submit">{initialized?'回到我的世界':'点亮我的营地'}<Compass size={18}/></Button></Form><div className="welcome-note"><ShieldCheck size={18}/><span>AI 可以稍后配置 · 世界与玩法随时可用</span></div></section></div></main>
}

const navigation = [['/world','世界',Compass],['/roster','角色与魔兽',Swords],['/rewards','奖励',Gift],['/system','系统',Sparkles]] as const
function OldWagerLink(){const {id}=useParams();return <Navigate replace to={'/system?tab=wagers'+(id?'&wager='+encodeURIComponent(id):'')}/>}
function RetiredPage(){return <div className="core-page"><h1>旅程有了新的入口。</h1><Notice>站内学习管理、屏幕时间与独立创作已退出。签到与对赌继续保留在系统，原记录仍可从账本来源和数据导出查看。</Notice><div className="core-actions"><Link className="button" to="/world">回到家园</Link><Link className="button secondary" to="/system?tab=wagers">签到与对赌</Link><Link className="button secondary" to="/ledger">查看原始流水</Link></div></div>}
function Shell({me}:{me:Schema<'CurrentUser'>}) {
  const profile=me.profile, location=useLocation(), cmd=useCommand()
  const [threadId,setThread]=useState<string|null>(()=>localStorage.getItem('kw-thread:'+profile.id)),[agentOpen,setAgentOpen]=useState(false),[mobileNav,setMobileNav]=useState(false),[showNotifications,setShowNotifications]=useState(false)
  const [width,setWidth]=useState(window.innerWidth), navRef=useRef<HTMLElement>(null), agentRef=useRef<HTMLElement>(null)
  const notifications=usePagedApi<Schema<'Notification'>>('/notifications?unread_only=true',10000)
  const fullSystem=location.pathname.startsWith('/system'), navModal=width<=760&&mobileNav, agentModal=width<=1100&&agentOpen&&!fullSystem
  useOverlayFocus(navRef,navModal,()=>setMobileNav(false));useOverlayFocus(agentRef,agentModal,()=>setAgentOpen(false))
  useEffect(()=>{setMobileNav(false)},[location.pathname])
  useEffect(()=>{const resize=()=>setWidth(window.innerWidth);window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize)},[])
  const epoch=useRef(me.display_epoch)
  useEffect(()=>{if(epoch.current!==me.display_epoch){clearWorldDisplayState();epoch.current=me.display_epoch}},[me.display_epoch])
  useEffect(()=>{
    const p=profile.preferences
    document.documentElement.dataset.reducedMotion=p.reduced_motion?'true':'false'
    savePresentationPreferences(profile.id,me.display_epoch,{reducedMotion:!!p.reduced_motion,sound:!!p.sound_enabled,autoCamera:p.auto_camera!==false})
  },[profile.id,profile.version,me.display_epoch])
  useEffect(()=>{
    const p=profile.preferences
    if(p.graphics_quality) savePresentationPreferences(profile.id,me.display_epoch,{
      reducedMotion:!!p.reduced_motion,sound:!!p.sound_enabled,autoCamera:p.auto_camera!==false,
      quality:({high:'desktop',medium:'mobile',low:'low'} as const)[p.graphics_quality],
    })
  },[profile.id,profile.preferences.graphics_quality,me.display_epoch])
  const setThreadId=(id:string)=>{setThread(id);try{localStorage.setItem('kw-thread:'+profile.id,id)}catch{}}
  return <AppContext.Provider value={{profile:{...profile,display_epoch:me.display_epoch},wallet:me.wallet,today:me.business_date,isTest:me.is_test_adapter,threadId,setThreadId,agentOpen,setAgentOpen}}><GameFeedbackProvider><BackgroundSync/><div className={'app-shell core-shell '+(agentOpen&&!fullSystem?'with-agent':'')}>
    <aside ref={navRef} className={'navigation '+(mobileNav?'open':'')} role={navModal?'dialog':undefined} aria-modal={navModal||undefined} aria-label="世界导航" inert={width<=760&&!mobileNav||agentModal} tabIndex={-1}>{navModal&&<button className="icon-button" aria-label="关闭导航" onClick={()=>setMobileNav(false)}><X/></button>}<Link className="brand" to="/world" onClick={()=>setMobileNav(false)}><span className="brand-mark"><Leaf size={26}/></span><span>知识世界<small>YOUR OWN WORLD</small></span></Link><div className="nav-intro">让今天，留下可见的变化。</div><nav aria-label="主要导航" onClick={event=>{if(event.target instanceof Element&&event.target.closest("a"))setMobileNav(false)}}>{navigation.map(([path,label,Icon])=><NavLink key={path} to={path}><Icon size={19}/><span>{label}</span></NavLink>)}<div className="nav-section">旅程记录</div><NavLink to="/ledger"><Wallet size={18}/>积分账本</NavLink><NavLink to="/settings"><Settings size={18}/>设置</NavLink></nav><div className="nav-bottom"><img src="/world-art/fox-3d.png" alt=""/><div><strong>{profile.display_name}</strong><small>你的同行伙伴已在营地</small></div></div></aside>
    <div className="app-main" inert={navModal||agentModal}><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-only" aria-label="打开导航" onClick={()=>setMobileNav(true)}><Menu size={21}/></button><span>知识世界</span><span>/</span><strong>{navigation.find(([path])=>location.pathname.startsWith(path))?.[1]||(location.pathname.startsWith('/leisure/')?'休息小屋':location.pathname.startsWith('/ledger')?'积分账本':'设置')}</strong></div><div className="topbar-right"><Link className="balance-pill" to="/ledger"><Sparkles size={16}/>{me.wallet.available_points}<small>积分</small>{me.wallet.held_points>0&&<small>· 预留 {me.wallet.held_points}</small>}</Link><span className="top-date"><Moon size={15}/>{me.business_date}</span><button className="icon-button" aria-label="通知中心" onClick={()=>setShowNotifications(true)}><Bell size={18}/>{!!notifications.data?.items.length&&<i/>}</button>{!fullSystem&&<button className="icon-button" aria-label={agentOpen?'收起系统对话':'打开系统对话'} onClick={()=>setAgentOpen(!agentOpen)}><MessageCircle size={19}/></button>}</div></header>
      {me.is_test_adapter&&<div className="test-banner">隔离开发 · 测试适配器已启用，AI 输出不能作为真实接入证据</div>}
      <main className="content" id="main-content"><Suspense fallback={<Loading/>}><Routes><Route path="/world" element={<World/>}/><Route path="/world/battles/:id" element={<BattlePage/>}/><Route path="/roster" element={<Roster/>}/><Route path="/rewards" element={<Rewards/>}/><Route path="/leisure/:id" element={<Rewards/>}/><Route path="/system" element={<System/>}/><Route path="/system/threads/:threadId" element={<System/>}/><Route path="/ledger" element={<Ledger/>}/><Route path="/settings" element={<SettingsPage/>}/><Route path="/commitments" element={<OldWagerLink/>}/><Route path="/commitments/:id" element={<OldWagerLink/>}/><Route path="/habits" element={<Navigate to="/system?tab=checkin" replace/>}/><Route path="/workshop" element={<Navigate to="/rewards" replace/>}/><Route path="/agent/*" element={<Navigate to="/system" replace/>}/><Route path="/" element={<Navigate to="/world" replace/>}/><Route path="*" element={<RetiredPage/>}/></Routes></Suspense><footer className="page-footer"><Leaf size={13}/><span>每一次行动，都有自己的回响。</span></footer></main>
    </div>{agentOpen&&!fullSystem&&<aside ref={agentRef} className="agent-dock" role={agentModal?'dialog':undefined} aria-modal={agentModal||undefined} aria-label="系统对话" tabIndex={-1}><AgentPanel/></aside>}{!fullSystem&&<button className="mobile-agent-fab" inert={navModal||agentModal} aria-label="打开系统对话" onClick={()=>setAgentOpen(!agentOpen)}><MessageCircle size={22}/></button>}{mobileNav&&<button className="nav-backdrop" aria-label="关闭导航遮罩" onClick={()=>setMobileNav(false)}/>}
    {showNotifications&&<Modal title="系统通知" onClose={()=>setShowNotifications(false)}><div className="notification-list">{notifications.data?.items.map(n=><article key={n.id}><strong>{n.title}</strong><p>{n.body}</p><div className="actions"><Link to={n.target_path} onClick={()=>setShowNotifications(false)}>查看详情</Link><Button kind="secondary" onClick={()=>cmd.mutate({path:'/notifications/'+n.id+'/read'})}>标为已读</Button></div></article>)}<LoadMore query={notifications} label="更多通知"/>{!notifications.data?.items.length&&<p>所有消息都读过了。</p>}</div></Modal>}
  </div></GameFeedbackProvider></AppContext.Provider>
}
export function App(){const status=useApi('/setup/status'),me=useApi<Schema<'CurrentUser'>>('/me');if(status.isLoading||me.isLoading)return <Loading/>;if(status.error)return <ErrorNotice error={status.error}/>;if(!status.data?.initialized||me.error instanceof ApiError&&me.error.status===401)return <Welcome initialized={!!status.data?.initialized}/>;if(me.error)return <div className="connection-error"><ErrorNotice error={me.error}/><Button onClick={()=>void queryClient.invalidateQueries()}>重新连接</Button></div>;return me.data?<Shell me={me.data}/>:<Loading/>}
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><QueryClientProvider client={queryClient}><BrowserRouter><a className="skip-link" href="#main-content">跳到主要内容</a><App/></BrowserRouter></QueryClientProvider></React.StrictMode>)
