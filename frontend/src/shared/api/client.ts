import {QueryClient, useMutation, useQuery, useQueryClient, useInfiniteQuery} from '@tanstack/react-query'
import type {components} from './schema'
import {clearWorldDisplayState} from '../world-display-state'
export type Wallet = components['schemas']['Wallet']
export type Schema<K extends keyof components['schemas']> = components['schemas'][K]
export type Receipt = Schema<'LedgerEntry'>
export type Page<T> = {items:T[]; next_cursor:string|null}
// Legacy maintenance views are flexible; every new game DTO comes from Pydantic.
export type RecordView = {id:string;version:number;[key:string]:any}
export class ApiError extends Error {code:string;status:number;details:Record<string,unknown>;constructor(data:any,status:number){super(data.message||'请求暂未完成');this.code=data.code;this.status=status;this.details=data.details||{}}}
export const queryClient=new QueryClient({defaultOptions:{queries:{staleTime:10000,refetchOnWindowFocus:'always',refetchOnReconnect:'always',retry:(n,e)=>!(e instanceof ApiError&&e.status<500)&&n<1},mutations:{retry:false}}})
const csrf=()=>decodeURIComponent(document.cookie.split('; ').find(c=>c.startsWith('kw_csrf='))?.slice(8)||'')
export async function api<T=RecordView>(path:string,method='GET',body?:unknown,key?:string):Promise<T>{
  const headers:Record<string,string>={}
  if(method!=='GET'){headers['Idempotency-Key']=key||crypto.randomUUID();headers['X-CSRF-Token']=csrf()}
  if(body!==undefined&&!(body instanceof FormData))headers['Content-Type']='application/json'
  const result=await fetch('/api/v1'+path,{method,headers,credentials:'same-origin',body:body instanceof FormData?body:body===undefined?undefined:JSON.stringify(body)})
  const value=await result.json()
  if(!result.ok){if(result.status===401)clearWorldDisplayState();throw new ApiError(value.error||{},result.status)}
  if(method!=='GET'&&(path==='/auth/logout'||path.includes('/restore')))clearWorldDisplayState()
  return value.data as T
}
export function useApi<T=RecordView>(path:string|null,interval?:number){return useQuery<T>({queryKey:[path],queryFn:()=>api<T>(path!),enabled:!!path,refetchInterval:interval})}
export function usePagedApi<T=RecordView>(path:string|null,interval?:number){
 const query=useInfiniteQuery({queryKey:['pages',path],enabled:!!path,initialPageParam:'',
  queryFn:({pageParam})=>api<Page<T>>(path!+(path!.includes('?')?'&':'?')+params({cursor:pageParam})),
  getNextPageParam:last=>last.next_cursor||undefined,refetchInterval:interval})
 return {...query,data:query.data?{items:query.data.pages.flatMap(p=>p.items),next_cursor:query.data.pages.at(-1)?.next_cursor||null}:undefined}
}
export function useCommand<T=RecordView>(){const cache=useQueryClient();return useMutation<T,Error,{path:string;method?:string;body?:unknown;key?:string}>({mutationFn:({path,method='POST',body={},key})=>api<T>(path,method,body,key),onSuccess:()=>{void cache.invalidateQueries({predicate: query => !['shiyi','world-history'].includes(String(query.queryKey[0]))})}})}
export const params=(values:Record<string,string|number|undefined|null>)=>new URLSearchParams(Object.entries(values).filter(([,v])=>v!==undefined&&v!==null&&v!=='').map(([k,v])=>[k,String(v)])).toString()
export const changeDay=(day:string,offset:number)=>{const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+offset);return d.toISOString().slice(0,10)}
export const displayTime=(time:string|null|undefined)=>time?new Date(time).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}):'—'
export const stageNames:Record<string,string>={unseen:'尚未探索',exploring:'开始探索',understood:'理解概念',applicable:'独立运用',consolidated:'稳定巩固'}
export const stateNames:Record<string,string>={ready:'准备好了',submitted:'等待判定',completed:'已完成',settled:'已结算',needs_review:'待核对',needs_configuration:'等待配置 AI',failed:'未完成',queued:'已排队',running:'进行中',retry_wait:'等待重试',succeeded:'已完成',cancelled:'已取消',reserved:'已预留',paused:'已暂停',active:'进行中',accepted:'已接受',pending_settlement:'等待判定结算',won:'挑战成功',lost:'未达成',voided:'异常退回押金',proposed:'待接受',unknown:'服务状态待核对，免罚',missed:'未签到',rest:'休息日',due:'等待签到',occupied:'已占领',available:'可进攻',locked:'未解锁',resolved:'已保存战报'}
