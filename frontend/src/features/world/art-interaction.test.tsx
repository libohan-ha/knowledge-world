import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {act,cleanup,fireEvent,render,screen} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {LeisureRoom} from './LeisureRoom'
import {GameFeedback,feedbackSequence,useGameFeedback} from './GameFeedback'
import {syntheticTicket,syntheticVisual} from './art-fixtures'
import type {VisualEvent} from './feedback-state'
import {savePresentationPreferences,usePresentationPreferences} from './presentation-preferences'

vi.mock('./WorldMap',()=>({WorldMap:()=> <div data-testid="isolated-scene">synthetic · 场景单独验证</div>}))

beforeEach(()=>{
  localStorage.clear()
  vi.stubGlobal('matchMedia',vi.fn(()=>({matches:false,addEventListener:vi.fn(),removeEventListener:vi.fn()})))
})
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals()})

function PreferenceView({account='synthetic-account',epoch='epoch1'}:{account?:string;epoch?:string}) {
  const preferences=usePresentationPreferences(account,epoch)
  return <output aria-label="显示画质">{preferences.quality||'按设备默认'}</output>
}

describe('同账户跨场景的显示偏好',()=>{
  it('没有选择时保留设备默认；全局画质立即生效，音效同步不清空它；新账户或恢复世代隔离',()=>{
    const view=render(<PreferenceView/>)
    expect(screen.getByLabelText('显示画质')).toHaveTextContent('按设备默认')
    act(()=>savePresentationPreferences('synthetic-account','epoch1',{reducedMotion:false,autoCamera:true,sound:false,quality:'low'}))
    expect(screen.getByLabelText('显示画质')).toHaveTextContent('low')
    act(()=>savePresentationPreferences('synthetic-account','epoch1',{reducedMotion:true,autoCamera:false,sound:false}))
    expect(screen.getByLabelText('显示画质')).toHaveTextContent('low')
    view.rerender(<PreferenceView account="synthetic-other"/>);expect(screen.getByLabelText('显示画质')).toHaveTextContent('按设备默认')
    view.rerender(<PreferenceView epoch="restored"/>);expect(screen.getByLabelText('显示画质')).toHaveTextContent('按设备默认')
    view.rerender(<PreferenceView/>);expect(screen.getByLabelText('显示画质')).toHaveTextContent('low')
  })
})

function QueueView({events,ready=true,namespace='synthetic-account:epoch1'}:{events:VisualEvent[];ready?:boolean;namespace?:string}) {
  const {playing,pending,finish}=useGameFeedback(events,namespace,false,ready)
  return <><input aria-label="正在填写的汇报"/><output aria-label="正在展示">{playing?.event.order||'无'}</output><output aria-label="等待展示">{pending}</output><button onClick={finish}>完成本次展示</button></>
}

describe('恢复与输入期间的真实显示队列',()=>{
  it('等待首个已处理 feed 才初始化；恢复仅播最后一项，随后实时事件逐项出现',()=>{
    const empty:VisualEvent[]=[],past=[syntheticVisual(1),syntheticVisual(2),syntheticVisual(3)]
    const view=render(<QueueView events={empty} ready={false}/>)
    expect(screen.getByLabelText('正在展示')).toHaveTextContent('无')
    view.rerender(<QueueView events={past} ready/>)
    expect(screen.getByLabelText('正在展示')).toHaveTextContent('3')
    view.rerender(<QueueView events={[...past,syntheticVisual(4),syntheticVisual(5)]} ready/>)
    fireEvent.click(screen.getByText('完成本次展示'));expect(screen.getByLabelText('正在展示')).toHaveTextContent('4')
    fireEvent.click(screen.getByText('完成本次展示'));expect(screen.getByLabelText('正在展示')).toHaveTextContent('5')
  })
  it('输入焦点仍在原处；失焦后才开始成长，切换账户不复用旧播放与书签',()=>{
    const events:VisualEvent[]=[],view=render(<QueueView events={events}/>)
    const input=screen.getByLabelText('正在填写的汇报');act(()=>input.focus())
    view.rerender(<QueueView events={[syntheticVisual(1)]}/>)
    expect(input).toHaveFocus();expect(screen.getByLabelText('正在展示')).toHaveTextContent('无')
    act(()=>input.blur());expect(screen.getByLabelText('正在展示')).toHaveTextContent('1')
    view.rerender(<QueueView events={events} namespace="synthetic-second-account:epoch2"/>)
    expect(screen.getByLabelText('正在展示')).toHaveTextContent('无')
    view.rerender(<QueueView events={[syntheticVisual(1)]} namespace="synthetic-second-account:epoch2"/>)
    expect(screen.getByLabelText('正在展示')).toHaveTextContent('1')
  })
  it('回执中的按钮获得焦点时不会因演出到期消失；移开后正常收起',()=>{
    vi.useFakeTimers({toFake:['setInterval','clearInterval','performance']})
    const event=syntheticVisual(1),sequence=feedbackSequence(event),finish=vi.fn()
    render(<MemoryRouter><GameFeedback playing={{event,sequence}} onFinish={finish}/></MemoryRouter>)
    act(()=>screen.getByRole('button',{name:'跳过演出'}).focus())
    act(()=>vi.advanceTimersByTime(sequence.duration+1000));expect(finish).not.toHaveBeenCalled()
    act(()=>screen.getByRole('button',{name:'收好回执'}).blur())
    act(()=>vi.advanceTimersByTime(1000));expect(finish).toHaveBeenCalledTimes(1)
  })
})

describe('休息小屋只按服务端快照显示权益',()=>{
  it('到零只请求一次同步，不发完成、补时或扣款命令；新快照恢复显示',()=>{
    vi.useFakeTimers({toFake:['setInterval','clearInterval','performance']})
    const ticket=syntheticTicket(),action=vi.fn(),refresh=vi.fn()
    const view=render(<MemoryRouter><LeisureRoom ticket={ticket} onAction={action} onRefresh={refresh}/></MemoryRouter>)
    act(()=>vi.advanceTimersByTime(5000));expect(refresh).toHaveBeenCalledTimes(1);expect(action).not.toHaveBeenCalled()
    expect(screen.getByText('正在核对结束状态')).toBeInTheDocument()
    act(()=>vi.advanceTimersByTime(15000));expect(refresh).toHaveBeenCalledTimes(1)
    view.rerender(<MemoryRouter><LeisureRoom ticket={{...ticket,state:'paused',version:3,remaining_seconds:42}} onAction={action} onRefresh={refresh}/></MemoryRouter>)
    expect(screen.getByText('00:42')).toBeInTheDocument()
    act(()=>vi.advanceTimersByTime(60000));expect(screen.getByText('00:42')).toBeInTheDocument();expect(action).not.toHaveBeenCalled()
  })
  it('点击开始只提交意图，仍显示原券；已开始券没有未用退款入口',()=>{
    const ticket={...syntheticTicket(),state:'reserved',first_started_at:null,remaining_seconds:60},action=vi.fn()
    const view=render(<MemoryRouter><LeisureRoom ticket={ticket} onAction={action}/></MemoryRouter>)
    fireEvent.click(screen.getByRole('button',{name:'开始这段休闲'}));expect(action).toHaveBeenLastCalledWith('start')
    expect(screen.getByText('已预留')).toBeInTheDocument()
    expect(screen.getByRole('button',{name:'未开始，原价退回'})).toBeInTheDocument()
    view.rerender(<MemoryRouter><LeisureRoom ticket={{...syntheticTicket(),state:'paused'}} onAction={action}/></MemoryRouter>)
    expect(screen.queryByRole('button',{name:'未开始，原价退回'})).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button',{name:'继续休闲'}));expect(action).toHaveBeenLastCalledWith('resume')
    expect(screen.getByText('已暂停')).toBeInTheDocument()
  })
})
