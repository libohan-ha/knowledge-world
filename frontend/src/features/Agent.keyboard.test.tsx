import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {MemoryRouter} from 'react-router-dom'
import {AgentPanel} from './Agent'

const mocks=vi.hoisted(()=>({send:vi.fn(),api:vi.fn(),hasThread:true,active:false,pending:false}))
vi.mock('../shared/api/client',()=>({
  api:mocks.api,displayTime:()=>'',queryClient:{invalidateQueries:vi.fn()},
  usePagedApi:()=>({data:{items:mocks.hasThread?[{id:'synthetic-thread',title:'测试会话'}]:[]}}),
  useApi:()=>({data:{messages:[],runs:mocks.active?[{id:'synthetic-run',state:'running',job_id:null}]:[]}}),
  useCommand:()=>({mutateAsync:mocks.send,isPending:mocks.pending}),
}))
vi.mock('../app-context',()=>({useApp:()=>({profile:{id:'synthetic-account'},threadId:mocks.hasThread?'synthetic-thread':null,setThreadId:vi.fn(),setAgentOpen:vi.fn(),isTest:true})}))
beforeEach(()=>{vi.resetAllMocks();localStorage.clear();mocks.hasThread=true;mocks.active=false;mocks.pending=false;mocks.send.mockResolvedValue({state:'queued'})})
afterEach(cleanup)
function composer(){render(<MemoryRouter><AgentPanel full/></MemoryRouter>);return screen.getByRole('textbox',{name:'发送给系统'})}

it('Enter sends the draft and clears it after acknowledgement',async()=>{
  const user=userEvent.setup(),input=composer()
  await user.type(input,'今天完成了晨跑{Enter}')
  expect(mocks.send).toHaveBeenCalledTimes(1)
  expect(mocks.send.mock.calls[0][0].body.content).toBe('今天完成了晨跑')
  expect(input).toHaveValue('')
})
it('Ctrl+Enter inserts a newline without sending',async()=>{
  const user=userEvent.setup(),input=composer()
  await user.type(input,'第一行');await user.keyboard('{Control>}{Enter}{/Control}');await user.type(input,'第二行')
  expect(input).toHaveValue('第一行\n第二行');expect(mocks.send).not.toHaveBeenCalled()
})
it('Shift+Enter inserts a newline without sending',async()=>{
  const user=userEvent.setup(),input=composer()
  await user.type(input,'第一行');await user.keyboard('{Shift>}{Enter}{/Shift}');await user.type(input,'第二行')
  expect(input).toHaveValue('第一行\n第二行');expect(mocks.send).not.toHaveBeenCalled()
})
it.each([{isComposing:true},{keyCode:229}])('IME confirmation does not send (%j)',async native=>{
  const input=composer();fireEvent.change(input,{target:{value:'中文输入'}})
  await act(async()=>fireEvent.keyDown(input,{key:'Enter',...native}))
  expect(mocks.send).not.toHaveBeenCalled();expect(input).toHaveValue('中文输入')
})
it('holding Enter does not send repeated keydown events',async()=>{
  const input=composer();fireEvent.change(input,{target:{value:'保持草稿'}})
  await act(async()=>fireEvent.keyDown(input,{key:'Enter',repeat:true}))
  expect(mocks.send).not.toHaveBeenCalled();expect(input).toHaveValue('保持草稿')
})
it('rapid Enter presses create only one first thread and one message',async()=>{
  mocks.hasThread=false;mocks.api.mockResolvedValue({id:'synthetic-created-thread'})
  let finish!:(value:unknown)=>void;mocks.send.mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
  const input=composer();fireEvent.change(input,{target:{value:'只发一次'}})
  await act(async()=>{fireEvent.keyDown(input,{key:'Enter'});fireEvent.keyDown(input,{key:'Enter'})})
  expect(mocks.api).toHaveBeenCalledTimes(1);expect(mocks.send).toHaveBeenCalledTimes(1)
  await act(async()=>finish({state:'queued'}))
})
it.each(['empty','active','pending'])('Enter respects the %s send guard',async mode=>{
  mocks.active=mode==='active';mocks.pending=mode==='pending'
  const input=composer();fireEvent.change(input,{target:{value:mode==='empty'?'   ':'等待回复'}})
  await act(async()=>fireEvent.keyDown(input,{key:'Enter'}))
  expect(mocks.send).not.toHaveBeenCalled()
})
it('a failed Enter submission preserves the draft and reuses its request key',async()=>{
  mocks.send.mockRejectedValueOnce(new Error('SYNTHETIC 网络失败')).mockResolvedValueOnce({state:'queued'})
  const user=userEvent.setup(),input=composer();await user.type(input,'重试同一消息{Enter}')
  expect(input).toHaveValue('重试同一消息')
  await user.keyboard('{Enter}')
  expect(mocks.send).toHaveBeenCalledTimes(2)
  expect(mocks.send.mock.calls[0][0].key).toBe(mocks.send.mock.calls[1][0].key)
})
it('Ctrl+Enter replaces the selection with a newline and keeps the caret there',async()=>{
  const user=userEvent.setup(),input=composer() as HTMLTextAreaElement
  await user.type(input,'abXYcd');input.setSelectionRange(2,4)
  await user.keyboard('{Control>}{Enter}{/Control}')
  expect(input).toHaveValue('ab\ncd');expect(input.selectionStart).toBe(3);expect(input.selectionEnd).toBe(3)
  await user.type(input,'中',{skipClick:true})
  expect(input).toHaveValue('ab\n中cd');expect(mocks.send).not.toHaveBeenCalled()
})
