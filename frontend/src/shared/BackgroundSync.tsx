import {useEffect,useRef} from 'react'
import {useQueryClient} from '@tanstack/react-query'
import {useApi,type Page,type Schema} from './api/client'
export function BackgroundSync(){const path='/jobs?limit=100',jobs=useApi<Page<Schema<'BackgroundJob'>>>(path,3000),cache=useQueryClient(),previous=useRef<string|null>(null),signature=jobs.data?.items.map(j=>`${j.id}:${j.state}:${j.updated_at}`).join('|');useEffect(()=>{if(signature===undefined)return;if(previous.current!==null&&previous.current!==signature)void cache.invalidateQueries({predicate:q=>q.queryKey[0]!==path&&!['shiyi','world-history'].includes(String(q.queryKey[0]))});previous.current=signature},[signature,cache]);return null}
