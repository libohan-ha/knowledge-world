import {afterEach,expect,it,vi} from 'vitest'
import {cleanup,render,screen,within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {MemoryRouter} from 'react-router-dom'
import {AgentPanel,pendingCards} from './Agent'

const card=(id:string,entity:string,run='run-1',title='早睡早起 +10h学习')=>({id,tool_name:'propose_challenge',state:'proposed',action_hash:'h'+id,run_id:run,created_at:'',result:{id:entity,title,goal:'数学/408/英语三线开花',reward_points:80,penalty_points:20}})
const mocks=vi.hoisted(()=>({actions:[] as unknown[]}))
vi.mock('../shared/api/client',()=>({
  api:vi.fn(),displayTime:()=>'',queryClient:{invalidateQueries:vi.fn()},
  usePagedApi:()=>({data:{items:[{id:'synthetic-thread',title:'测试会话'}]}}),
  useApi:()=>({data:{messages:[{id:'m1',role:'user',content_md:'帮我定个约定',run_id:'run-1',created_at:''},{id:'m2',role:'assistant',content_md:'好的，条款如下。',run_id:'run-1',created_at:''}],runs:[],actions:mocks.actions}}),
  useCommand:()=>({mutateAsync:vi.fn(),mutate:vi.fn(),isPending:false,error:null}),
}))
vi.mock('../app-context',()=>({useApp:()=>({profile:{id:'synthetic-account'},threadId:'synthetic-thread',setThreadId:vi.fn(),setAgentOpen:vi.fn(),isTest:true})}))
afterEach(cleanup)

it('pendingCards keeps one card per proposal, newest first-class',()=>{
  const cards=pendingCards([card('a','c1'),card('b','c1'),card('c','c2')] as never)
  expect(cards.map(item=>item.id)).toEqual(['b','c'])
})
it('pending terms render once in the tray and only as a chip in chat',async()=>{
  mocks.actions=[card('a','c1'),card('b','c1')]
  render(<MemoryRouter><AgentPanel full/></MemoryRouter>)
  const tray=screen.getByRole('region',{name:'待确认条款'})
  expect(within(tray).getByText('1')).toBeInTheDocument()
  expect(screen.getAllByRole('button',{name:'核对并确认'})).toHaveLength(1)
  const chip=screen.getByRole('button',{name:/已放入下方待确认/})
  expect(chip.closest('.message')).not.toBeNull()
  expect(document.querySelector('.agent-messages .terms-tray-card')).toBeNull()
  await userEvent.setup().click(within(tray).getByRole('button',{name:/待确认条款/}))
  expect(screen.queryByRole('button',{name:'核对并确认'})).toBeNull()
})
it('no tray without pending terms',()=>{
  mocks.actions=[]
  render(<MemoryRouter><AgentPanel full/></MemoryRouter>)
  expect(screen.queryByRole('region',{name:'待确认条款'})).toBeNull()
})
