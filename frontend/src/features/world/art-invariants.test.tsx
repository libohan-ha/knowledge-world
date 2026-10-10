import {describe,expect,it,vi} from 'vitest'
import {Vector3} from 'three'
import tokens from '../../../../docs/contracts/design-tokens.json'
import {focusToLegacyViewport,legacyViewportToFocus,placementToWorld,worldToPlacement,knownStage} from './coordinates'
import {FeedbackQueue,readBookmark} from './feedback-state'
import {sequenceFrame,effectDuration} from './timeline'
import {actionMotion} from './BattleEffects'
import {battleStatesAt,validatePlayback} from './battle-timeline'
import {createModelLibrary,disposeModel} from './models'
import {gameModelFactory} from './game-models'
import {eventToVisual} from './game-view'
import {ticketDisplaySeconds} from './LeisureRoom'
import {syntheticBattle,syntheticEvent,syntheticTicket,syntheticVisual} from './art-fixtures'

describe('相机与恢复坐标',()=>{
  it('旧视口和平移在四象限、缩放边界可往返，不混淆 x/z',()=>{
    for(const zoom of [tokens.world.camera.min_zoom,1,tokens.world.camera.max_zoom])for(const x of [-12,0,6.25,26])for(const z of [-12,0,4.5]){
      const view=focusToLegacyViewport({x,z,zoom}),roundtrip=legacyViewportToFocus(view)
      expect(roundtrip.x).toBeCloseTo(x,9);expect(roundtrip.z).toBeCloseTo(z,9);expect(roundtrip.zoom).toBe(zoom)
      const placement=placementToWorld(worldToPlacement({x,z}));expect(placement.x).toBeCloseTo(x,9);expect(placement.z).toBeCloseTo(z,9)
    }
  })
  it('损坏的设备坐标、零缩放和继承键不会把 NaN 或伪阶段带入场景',()=>{
    const result=legacyViewportToFocus({x:NaN,y:Infinity,zoom:0})
    expect(Object.values(result).every(Number.isFinite)).toBe(true)
    expect(result.zoom).toBe(tokens.world.camera.default_zoom)
    expect(knownStage('__proto__')).toBeNull();expect(knownStage('toString')).toBeNull();expect(knownStage(1.5)).toBeNull()
  })
  it('攻击位移按世界坐标计算；重合目标、低动效不会产生不合法矩阵',()=>{
    const actor={id:'a',model:'unit:hero:1:idle',x:10,z:20,title:'synthetic'},target={...actor,id:'b',x:13,z:24}
    const action={id:'synthetic-action',actorId:'a',targetId:'b',effect:'physical' as const,startedAt:0,duration:720}
    const move=actionMotion(action,actor,[actor,target],200,false)
    expect(move.x/move.z).toBeCloseTo(3/4);expect(Math.hypot(move.x,move.z)).toBeLessThanOrEqual(tokens.world.geometry.battle_lunge)
    expect(actionMotion(action,actor,[actor,{...target,x:10,z:20}],200,false)).toEqual({x:0,z:0,tilt:0})
    expect(actionMotion(action,actor,[actor,target],200,true)).toEqual({x:0,z:0,tilt:0})
  })
})

describe('正式事件的显示防重',()=>{
  it('重返仅自动展示最近一项，实时批次按序展示；中途刷新不重播已领取的显示事件',()=>{
    const queue=new FeedbackQueue();queue.ingest([syntheticVisual(3),syntheticVisual(1),syntheticVisual(2)])
    expect(queue.pending.map(e=>e.order)).toEqual([3]);expect(queue.take()?.order).toBe(3)
    queue.ingest([syntheticVisual(5),syntheticVisual(4),syntheticVisual(4)])
    expect(queue.take()?.order).toBe(4);expect(queue.take()?.order).toBe(5)
    const restored=new FeedbackQueue(readBookmark(JSON.stringify(queue.bookmark)));restored.ingest([syntheticVisual(1),syntheticVisual(5)])
    expect(restored.take()).toBeUndefined()
  })
  it('首次成功空 feed 后的一批成长不丢失；纠错即使没有账本 ID 也有自己的事件',()=>{
    const queue=new FeedbackQueue();queue.ingest([]);queue.ingest([syntheticVisual(1),syntheticVisual(2,'correction')])
    expect(queue.pending).toHaveLength(2);expect(queue.take()?.tone).toBe('positive');expect(queue.take()?.tone).toBe('correction')
  })
  it('其他窗口的显示确认合并后清掉待播旧事件，缺少来源的事件不播放',()=>{
    const queue=new FeedbackQueue();queue.ingest([]);queue.ingest([syntheticVisual(1),syntheticVisual(2),{...syntheticVisual(3),source:{label:'缺失',id:''}}])
    queue.mergeBookmark({watermark:1,ids:['synthetic-event-1']});expect(queue.pending.map(e=>e.order)).toEqual([2])
  })
  it('零奖励、扣分与纠错具有不同语义，不把预留或失败消费当新增奖励',()=>{
    expect(eventToVisual(syntheticEvent()).tone).toBe('neutral')
    const correction=eventToVisual(syntheticEvent({kind:'system_correction',after:{net_points:0,delta:-20},receipt:{actual_points:-20}}))
    expect(correction.tone).toBe('correction');expect(correction.economics?.[0].value).toBe(-20)
    const wager=eventToVisual(syntheticEvent({kind:'wager_lost',receipt:{returned_stake_points:0,extra_bonus_points:0,spent_stake_points:50}}))
    expect(wager.economics).toContainEqual({label:'本单押金消费',value:-50});expect(wager.economics?.some(item=>item.label==='可用积分变化')).toBe(false)
  })
  it('缺失的老前态保持未知；空对象与缺失对象不会混成同一张旧建筑',()=>{
    const event=syntheticEvent({kind:'home_buy',before:null,after:{code:'flower_bed',name:'花圃',level:1}})
    expect(eventToVisual(event).beforeObjects).toBeNull()
    expect(eventToVisual({...event,before:{}}).beforeObjects).toEqual([])
  })
  it('占领优先使用当场保存的据点快照，目录更新后仍能真实回看',()=>{
    const event=syntheticEvent({kind:'boss_occupied',object_id:'synthetic-site',before:{occupied:false},after:{occupied:true},receipt:{outpost_snapshot:{id:'synthetic-site',name:'当场的霜冠钟塔',theme:'frost_ridge',is_boss:true}}})
    const visual=eventToVisual(event)
    expect(visual.beforeObjects?.[0].model).toBe('outpost:frost_ridge:boss:hostile')
    expect(visual.afterObjects?.[0]).toMatchObject({title:'当场的霜冠钟塔',state:'owned',model:'outpost:frost_ridge:boss:occupied'})
    expect(eventToVisual({...event,receipt:{outpost_snapshot:{id:'another-site',name:'错误对象',theme:'mist_forest',is_boss:false}}}).afterObjects).toBeNull()
  })
})

describe('连续演出与服务器战报',()=>{
  it('占领按定位→退雾→建造→亮灯→伙伴→回执推进，可直接跳到最终态',()=>{
    const sequence={id:'synthetic-occupation',kind:'occupation' as const,startedAt:0,duration:effectDuration('occupation')},cues=tokens.world.presentation.landmark_cues_ms
    expect(sequenceFrame(sequence,cues.fog).build).toBe(0)
    expect(sequenceFrame(sequence,cues.build+1).build).toBeGreaterThan(0)
    expect(sequenceFrame(sequence,cues.lights-1).lights).toBe(false)
    expect(sequenceFrame(sequence,cues.lights).lights).toBe(true)
    expect(sequenceFrame(sequence,cues.companion).companion).toBe(true)
    expect(sequenceFrame(sequence,cues.receipt).receipt).toBe(true)
    expect(sequenceFrame(sequence,sequence.duration)).toMatchObject({finished:true,build:1,fog:0,lights:true})
    expect(sequenceFrame(sequence,0,true)).toMatchObject({finished:true,build:1,fog:0,lights:true})
    expect(sequenceFrame({...sequence,correction:true},0)).toMatchObject({build:1,fog:0,lights:true,receipt:true})
  })
  it('回放读取每步保存的护盾、受击、治疗状态；任意跳转和读取不改原战报',()=>{
    const battle=syntheticBattle(),before=JSON.stringify(battle)
    expect(validatePlayback(battle)).toBeNull()
    expect(battleStatesAt(battle,1)['synthetic-ally']).toEqual({hp:100,mp:44,shield:30})
    expect(battleStatesAt(battle,2)['synthetic-ally']).toEqual({hp:90,mp:44,shield:0})
    const end=battleStatesAt(battle,999);expect(end).toEqual(battle.result!.final_states);end['synthetic-ally'].hp=1
    expect(battleStatesAt(battle,0)['synthetic-ally']).toEqual({hp:100,mp:50,shield:0});expect(JSON.stringify(battle)).toBe(before)
    battle.result!.events[1].damage=9999
    expect(battleStatesAt(battle,2)['synthetic-ally'].hp).toBe(90)
  })
  it('动作缺页或状态断裂会阻止连续回放，不自行补齐伤害',()=>{
    const battle=syntheticBattle();battle.result!.events.splice(1,1);expect(validatePlayback(battle)).toContain('序号不连续')
    const broken=syntheticBattle();broken.result!.events[1].target_before={hp:10,mp:44,shield:30};expect(validatePlayback(broken)).toContain('前后态存在缺口')
  })
  it('休闲只从服务器余量估算显示，暂停、时钟倒退与到零都不增加权益',()=>{
    const ticket=syntheticTicket()
    expect(ticketDisplaySeconds(ticket,1000,4000)).toBe(0)
    expect(ticketDisplaySeconds({...ticket,state:'paused'},1000,900000)).toBe(1)
    expect(ticketDisplaySeconds(ticket,1000,0)).toBe(1)
    expect(ticket.state).toBe('running');expect(ticket.remaining_seconds).toBe(1)
  })
})

describe('真实模型与资源恢复',()=>{
  it('主建筑有完整前后体积，四种伙伴的成长改变几何且无无效顶点',()=>{
    const camp=gameModelFactory('home:camp_hall:3')!();camp.body.computeBoundingBox();const size=camp.body.boundingBox!.getSize(new Vector3())
    expect(size.x).toBeGreaterThan(.6);expect(size.y).toBeGreaterThan(.6);expect(size.z).toBeGreaterThan(.6)
    const p=camp.body.getAttribute('position'),n=camp.body.getAttribute('normal');let back=0
    for(let i=0;i<p.count;i++)if(p.getZ(i)<-.25&&n.getZ(i)<-.5)back++
    expect(back).toBeGreaterThan(12);disposeModel(camp)
    for(const code of ['hero','moss_bear','shadow_wolf','star_fox']) {
      const counts=[]
      for(const stage of [1,2,3]){const model=gameModelFactory(`unit:${code}:${stage}:idle`)!();counts.push(model.body.getAttribute('position').count);expect([...model.body.getAttribute('position').array].every(Number.isFinite)).toBe(true);disposeModel(model)}
      expect(new Set(counts).size).toBe(3)
    }
    for(const code of ['moss_bear','shadow_wolf','bramble','forest_boss']) {
      const model=gameModelFactory(`unit:${code}:1:defeat`)!();model.body.computeBoundingBox()
      expect(model.body.boundingBox!.min.y).toBeCloseTo(0,5);disposeModel(model)
    }
  })
  it('同一模型复用几何，释放一次，恢复时可重新构建；非法阶段或继承键不被当作模型',()=>{
    const library=createModelLibrary('forest'),a=library.models.get('home:camp_hall:1')!,disposed=vi.fn()
    a.body.addEventListener('dispose',disposed);expect(library.models.get('home:camp_hall:1')).toBe(a)
    library.dispose();library.dispose();expect(disposed).toHaveBeenCalledTimes(1)
    expect(library.models.get('home:camp_hall:1')!.body).not.toBe(a.body);library.dispose()
    expect(gameModelFactory('unit:toString:1:idle')).toBeUndefined();expect(gameModelFactory('decor:__proto__')).toBeUndefined();expect(gameModelFactory('home:camp_hall:1.5')).toBeUndefined()
  })
})
