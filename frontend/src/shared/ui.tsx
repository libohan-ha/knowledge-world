import type {ReactNode,FormEvent,RefObject} from 'react'
import {Children,cloneElement,isValidElement,useEffect,useId,useRef} from 'react'
import {Link} from 'react-router-dom'
import {AlertCircle,ArrowRight,LoaderCircle,Plus,X,Check,LockKeyhole} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {stateNames} from './api/client'

export function Button({children,busy=false,kind='',...props}:React.ButtonHTMLAttributes<HTMLButtonElement>&{busy?:boolean;kind?:string}){return <button {...props} disabled={props.disabled||busy} className={'button '+kind+' '+(props.className||'')}>{busy&&<LoaderCircle size={16} className="spin"/>}{children}</button>}
export function Empty({title,children,action,to}:{title:string;children?:ReactNode;action?:string;to?:string}){return <div className="empty"><div className="empty-sprout"><span>✦</span></div><h3>{title}</h3><p>{children}</p>{to&&<Link className="button" to={to}>{action}<ArrowRight size={16}/></Link>}</div>}
export function ErrorNotice({error}:{error:unknown}){return error?<div className="notice danger" role="alert"><AlertCircle size={18}/><span>{error instanceof Error?error.message:String(error)}</span></div>:null}
export function Notice({children}:{children:ReactNode}){return <div className="notice"><AlertCircle size={17}/><span>{children}</span></div>}
export function Loading(){return <div className="loading" role="status"><LoaderCircle className="spin" size={20}/>正在打开这一页…</div>}
export function useOverlayFocus(ref:RefObject<HTMLElement|null>,active:boolean,onClose:()=>void){
 const close=useRef(onClose);close.current=onClose
 useEffect(()=>{
  if(!active||!ref.current)return
  const previous=document.activeElement as HTMLElement,overflow=document.body.style.overflow
  const focusable=()=>Array.from(ref.current!.querySelectorAll<HTMLElement>('a[href],button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]')).filter(node=>node.getClientRects().length)
  ;(focusable()[0]||ref.current).focus();document.body.style.overflow='hidden'
  const keydown=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();close.current()}else if(event.key==='Tab'){const nodes=focusable(),first=nodes[0],last=nodes.at(-1);if(!first){event.preventDefault();ref.current?.focus()}else if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}}}
  document.addEventListener('keydown',keydown)
  return()=>{document.removeEventListener('keydown',keydown);document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus()}
 },[active,ref])
}
export function Badge({state,label}:{state?:string;label?:string}){return <span className={'badge '+(state||'')}>{state==='unlocked'?<Check size={12}/>:state==='locked'?<LockKeyhole size={12}/>:null}{label||(state==='locked'?'未解锁':state==='unlocked'?'已解锁':stateNames[state||'']||state)}</span>}
export function PageTitle({eyebrow,title,description,action}:{eyebrow:string;title:string;description?:string;action?:ReactNode}){return <header className="page-title"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{description&&<p>{description}</p>}</div>{action}</header>}
export function Field({label,children,hint}:{label:string;children:ReactNode;hint?:string}){
 const id=useId(),description=id+'-hint'
 const connect=(node:ReactNode):ReactNode=>{
  if(!isValidElement<{children?:ReactNode;id?:string;'aria-describedby'?:string}>(node))return node
  if(typeof node.type==='string'&&['input','select','textarea'].includes(node.type))return cloneElement(node,{id,'aria-describedby':hint?description:node.props['aria-describedby']})
  return node.props.children?cloneElement(node,{},Children.map(node.props.children,connect)):node
 }
 return <div className="field"><label htmlFor={id}>{label}</label>{Children.map(children,connect)}{hint&&<small id={description}>{hint}</small>}</div>
}
export function Markdown({children}:{children:string}){return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{children}</ReactMarkdown></div>}
export function Panel({title,children,action,className=''}:{title?:string;children:ReactNode;action?:ReactNode;className?:string}){return <section className={'panel '+className}>{title&&<div className="panel-heading"><h2>{title}</h2>{action}</div>}{children}</section>}
export function Modal({title,children,onClose}:{title:string;children:ReactNode;onClose:()=>void}){
 const ref=useRef<HTMLDialogElement>(null)
 useEffect(()=>{const previous=document.activeElement as HTMLElement;ref.current?.showModal();return()=>{ref.current?.close();previous?.focus()}},[])
 return <dialog ref={ref} className="dialog" aria-label={title} onCancel={onClose} onClick={e=>{if(e.target===ref.current)onClose()}}><div className="dialog-heading"><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label="关闭"><X size={20}/></button></div>{children}</dialog>
}
export function Form({onSubmit,children}:{onSubmit:(event:FormEvent<HTMLFormElement>)=>void;children:ReactNode}){return <form className="form" onSubmit={e=>{e.preventDefault();onSubmit(e)}}>{children}</form>}
export function AddButton({children,onClick}:{children:ReactNode;onClick:()=>void}){return <Button onClick={onClick}><Plus size={17}/>{children}</Button>}
export function Stat({label,value,unit,detail}:{label:string;value:ReactNode;unit?:string;detail?:string}){return <div className="stat"><span>{label}</span><strong>{value}<small>{unit}</small></strong>{detail&&<small>{detail}</small>}</div>}
