import {Button, ErrorNotice} from './ui'

export function LoadMore({query, label='加载更多'}:{query:{hasNextPage?:boolean;isFetchingNextPage:boolean;fetchNextPage:()=>Promise<unknown>;error:unknown};label?:string}){
 return <><ErrorNotice error={query.error}/>{query.hasNextPage&&<div className="load-more"><Button kind="secondary" busy={query.isFetchingNextPage} onClick={()=>void query.fetchNextPage()}>{label}</Button></div>}</>
}
