import type {components} from '../../shared/api/schema'
import tokens from '../../../../docs/contracts/design-tokens.json'
import type {SceneObject, SceneEffectKind} from './scene-types'
import type {VisualEvent} from './feedback-state'
import {stableHash} from './coordinates'
import {gameModelFactory, type UnitPose} from './game-models'

export type Unit = components['schemas']['Unit']
export type HomeItem = components['schemas']['HomeItem']
export type Home = components['schemas']['Home']
export type Outpost = components['schemas']['Outpost']
export type GameMap = components['schemas']['WorldMap']
export type GameEvent = components['schemas']['HistoryEvent']
export type Battle = components['schemas']['Battle']
export type Ticket = components['schemas']['LeisureTicket']
const G = tokens.world.geometry
export const roleLabels: Record<string,string> = {hero:'旅人',tank:'守护',damage:'输出',dps:'输出',support:'支援',guard:'守护',enemy:'敌方'}
export const skillLabels: Record<string,string> = {ember_bolt:'星火术',stone_guard:'岩甲守护',starlight_heal:'星光治愈',shadow_strike:'暗影突袭',physical_damage:'物理攻击',magic_damage:'法术攻击',shield:'护盾',heal:'治疗',attack:'普通攻击',arcane_strike:'奥术冲击'}
export const gameStateLabels: Record<string,string> = {reserved:'已预留',running:'休息中',paused:'已暂停',completed:'已完成',cancelled:'已退回',proposed:'待接受',active:'进行中',won:'达成约定',lost:'本次未达成',voided:'押金已退回',settled:'已记录',queued:'等待战报',resolved:'战报已保存',needs_review:'待核对',available:'可以出发',locked:'前路待开启',occupied:'已占领'}

export function unitModel(unit: Pick<Unit,'code'|'visual_stage'>, pose: UnitPose = 'idle') {
  const key = `unit:${unit.code}:${unit.visual_stage}:${pose}`
  return gameModelFactory(key) ? key : null
}
export function unitObject(unit: Unit, x = 0, z = 0, pose: UnitPose = 'idle', rotation = 0): SceneObject | null {
  const model = unitModel(unit,pose)
  return model ? {id:unit.id,model,x,z,title:unit.name,subtitle:`${roleLabels[unit.role] || unit.role} · Lv.${unit.level}`,rotation,scale:G.unit_scale,motion:'unit',state:'owned'} : null
}

export function homeItemModel(item: Pick<HomeItem,'id'|'code'|'kind'|'level'>, theme = 'forest') {
  if (item.code === 'camp_hall') return `home:camp_hall:${item.level}`
  if (item.code.startsWith('trophy_')) return `trophy:${item.code.slice(7)}`
  if (item.code === 'legacy_cottage') return `building:${theme}:${stableHash(item.id) % tokens.world.assets.building_variants_per_theme}:${Math.max(1,Math.min(3,item.level))}`
  if (item.code === 'legacy_companion') return 'fox:idle:false'
  if (item.code === 'companion_outfit') return 'fox:idle:true'
  if (item.code === 'harvest_collectible') return 'plant:2'
  const key = `decor:${item.code}`
  if (item.code === 'lantern' || gameModelFactory(key)) return key
  return null
}
export function homeItemObject(item: HomeItem, preview = false): SceneObject | null {
  const model=homeItemModel(item)
  if (!model || !preview && (item.x === null || item.z === null)) return null
  const offset=(item.footprint-1)/2
  return {id:item.id,model,x:preview?0:item.x!+offset,z:preview?0:item.z!+offset,title:item.name,subtitle:`${item.legacy_ref ? '从旧家园保留 · ' : ''}${item.kind === 'building' ? `Lv.${item.level}` : item.x === null ? '已收藏 · 尚未摆放' : '已摆放'}`,rotation:item.rotation,footprint:item.footprint,scale:item.kind === 'building'?G.home_building_scale:item.kind==='trophy'?G.trophy_scale:G.decor_scale,state:'owned'}
}

/** Every owned object uses its server ID. Only the companions' idle positions
 * are decorative; changing them never writes the persisted home layout. */
export function homeObjects(home: Home) {
  const objects=home.items.map(item=>homeItemObject(item)).filter((item):item is SceneObject=>!!item)
  const camp=objects.find(item=>item.model.startsWith('home:'))
  const units=[home.roster.hero,...home.roster.monsters].filter(unit=>home.roster.team.member_ids.includes(unit.id))
  for(const [index,unit] of units.entries()) {
    let x=(camp?.x||0)+1.85+index%2*0.8,z=(camp?.z||0)+0.7+Math.floor(index/2)*0.8
    // Find an idle place outside actual occupied footprints.
    for(let attempt=0;attempt<home.items.length+1;attempt++) {
      const occupied=home.items.find(item=>item.x!==null&&item.z!==null&&x>=item.x-0.5&&x<item.x+item.footprint-0.5&&z>=item.z-0.5&&z<item.z+item.footprint-0.5)
      if(!occupied)break
      x=occupied.x!+occupied.footprint+0.1
    }
    const object=unitObject(unit,x,z,'idle',-25-index*12)
    if(object)objects.push(object)
  }
  return objects
}
export function outpostObject(site: Outpost): SceneObject {
  return {id:site.id,model:`outpost:${site.theme}:${site.is_boss?'boss':'camp'}:${site.status==='occupied'?'occupied':'hostile'}`,x:site.position.x,z:site.position.z,title:site.name,subtitle:`${site.is_boss?'区域首领 · ':''}${gameStateLabels[site.status]}`,scale:G.outpost_scale,state:site.status==='occupied'?'owned':site.status}
}

const number = (value:unknown): number | undefined => typeof value==='number'&&Number.isFinite(value)?value:undefined
const string = (value:unknown): string | undefined => typeof value==='string'?value:undefined
const record = (value:unknown): Record<string,unknown> | null => value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:null
const list = (value:unknown): string[] => Array.isArray(value)?value.filter((v):v is string=>typeof v==='string'):[]
function field(state:Record<string,unknown>|null,path:string):unknown {return path.split('.').reduce<unknown>((value,key)=>record(value)?.[key],state)}

function stateObjects(state:Record<string,unknown>|null,id:string):SceneObject[]|null {
  if(state===null)return null
  if(!Object.keys(state).length)return []
  const code=string(state.code),stage=number(state.visual_stage),level=number(state.level)
  if(code&&stage!==undefined) {
    const model=gameModelFactory(`unit:${code}:${stage}:idle`)?`unit:${code}:${stage}:idle`:null
    return model?[{id,model,x:0,z:0,title:string(state.name)||'这位伙伴',subtitle:level===undefined?undefined:`Lv.${level}`,scale:G.unit_scale,state:'owned'}]:null
  }
  if(code&&level!==undefined&&Number.isInteger(level)) {
    const model=homeItemModel({id,code,level,kind:string(state.kind)||''})
    return model?[{id,model,x:0,z:0,title:string(state.name)||'这件收藏',subtitle:state.x===null?'已收藏 · 尚未摆放':`Lv.${level}`,rotation:number(state.rotation)||0,scale:code==='camp_hall'?G.home_building_scale:G.decor_scale,state:'owned'}]:null
  }
  return null
}

/** Decode only fields present in the actual event payload. Missing history is
 * left unknown; current stats/layout never fill an old snapshot. */
export function eventToVisual(event:GameEvent,context?:{map?:GameMap}):VisualEvent {
  const before=event.before,after=event.after,receipt=event.receipt,id=event.object_id||event.origin_id
  const actual=number(receipt.actual_points)??number(after?.delta)??number(after?.points)
  let kind:SceneEffectKind='system',tone:VisualEvent['tone']='neutral',title='一条新的世界记录'
  const economics:NonNullable<VisualEvent['economics']>=[],changes:VisualEvent['changes']=[]
  const money=(label:string,value:unknown,sign=1)=>{const n=number(value);if(n!==undefined)economics.push({label,value:n*sign})}
  const changed=(label:string,path:string,format:(value:unknown)=>string=String)=>{
    const a=field(before,path),b=field(after,path)
    if(b!==undefined&&b!==null&&(a!==b||!before))changes.push({label,before:a===undefined||a===null?undefined:format(a),after:format(b)})
  }
  if(event.kind==='initial_grant'){kind='home';tone='positive';title='营地的灯，为你亮起';if(Array.isArray(after?.monster_ids))changes.push({label:'初始同行伙伴',before:'尚未领取',after:`${after.monster_ids.length} 位`})}
  else if(event.kind.startsWith('system_')||event.kind==='manual_adjustment') {
    kind=actual!==undefined&&actual<0?'penalty':'system';tone=event.kind==='system_correction'?'correction':actual===undefined||actual===0?'neutral':actual<0?'negative':'positive'
    title=tone==='correction'?'这项判定，已按记录更正':tone==='negative'?'系统记下了这次扣分':tone==='positive'?'你的行动，获得了回应':'这次行动，已经记下'
    if(event.kind==='manual_adjustment')title='这笔手动调整，已记入账本'
    money('可用积分变化',actual);changed('这项行动累计积分','net_points')
  } else if(event.kind.startsWith('checkin_')) {
    kind=actual!==undefined&&actual<0?'penalty':'checkin';tone=actual===undefined||actual===0?'neutral':actual<0?'negative':'positive';title=tone==='negative'?'签到条款已有结算':tone==='positive'?'早安，今天也见到你了':'今天的签到状态已记录'
    money('签到积分',actual);changed('连续签到','streak',v=>`${v} 天`)
  } else if(event.kind.startsWith('wager_')) {
    kind='wager';title=event.kind==='wager_accepted'?'约定已立下，积分已预留':event.kind==='wager_won'?'你做到了，约定已达成':event.kind==='wager_lost'?'这一程，按约定收好结果':'约定已结束，押金已退回'
    tone=event.kind==='wager_won'?'positive':event.kind==='wager_lost'?'negative':'neutral'
    if(event.kind==='wager_accepted')money('本单预留押金',receipt.stake_points)
    else {money('返还押金',receipt.returned_stake_points);money('额外奖金',receipt.extra_bonus_points);if(number(receipt.spent_stake_points))money('本单押金消费',receipt.spent_stake_points,-1)}
  } else if(event.kind.startsWith('leisure_')) {
    kind=['leisure_start','leisure_resume'].includes(event.kind)?'leisure':'reward'
    title=({leisure_reserved:'把这段时光，留给自己',leisure_start:'暖灯亮好了，安心歇一会儿',leisure_resume:'继续刚才的好时光',leisure_pause:'先收好，剩余时光还在',leisure_cancel:'未开始的休闲已退回',leisure_completed:'这段休息，慢慢收尾'})[event.kind]||'休闲状态已有变化'
    tone=['leisure_reserved','leisure_start'].includes(event.kind)?'positive':'neutral'
    if(event.kind==='leisure_reserved')money('本券预留积分',after?.price_points)
    if(event.kind==='leisure_start'&&before?.state==='reserved')money('消费本券预留',after?.price_points,-1)
    if(event.kind==='leisure_cancel')money('返还可用积分',before?.price_points)
    changed('剩余时光','remaining_seconds',v=>`${Math.ceil(Number(v)/60)} 分钟`)
  } else if(event.kind==='monster_recruit'){kind='summon';tone='positive';title=`${string(after?.name)||'新的伙伴'}，愿与你同行`;money('招募消费',receipt.price_points,-1)}
  else if(['hero_train','monster_train'].includes(event.kind)){kind='training';tone='positive';title='一点积累，成为新的力量';money('本次培养消费',receipt.price_points,-1)}
  else if(['outpost_occupied','boss_occupied'].includes(event.kind)){kind='occupation';tone='positive';title=event.kind==='boss_occupied'?'这一片领地，记住了你们':'前方的灯火，成为归途';money('首胜积分',receipt.reward_points);changed('永久占领','occupied',v=>v?'已占领':'尚未占领')}
  else if(['battle_won','battle_lost'].includes(event.kind)){kind='battle';tone=event.kind==='battle_won'?'positive':'neutral';title=event.kind==='battle_won'?'远征胜利，战报已送达':'伙伴都还在，休整后再出发';changed('远征结果','outcome',v=>v==='won'?'胜利':'本次未胜利')}
  else if(event.kind.startsWith('home_')){kind='home';tone='positive';title=event.kind==='home_upgrade'?'让这里，更像你的家':event.kind==='home_buy'?'又一件喜欢的收藏':'家园的新位置，已经收好';money(event.kind==='home_upgrade'?'建筑升级消费':'家园消费',receipt.price_points,-1)}
  else if(event.kind==='team_changed'){tone='neutral';title='出发的阵位，已经排好'}
  else if(event.kind.startsWith('legacy_')){kind='history';tone='neutral';title='从旧世界保留的成长'}
  else if(event.kind.startsWith('challenge_')){title='系统任务已有结果';tone=event.kind==='challenge_completed'?'positive':'neutral'}
  for(const [label,path] of [['等级','level'],['外观阶段','visual_stage'],['力量','attributes.strength'],['敏捷','attributes.agility'],['法力','attributes.mana'],['生命上限','stats.hp'],['物理攻击','stats.physical_attack'],['法术攻击','stats.magic_attack'],['护甲','stats.defense'],['魔抗','stats.resistance'],['速度','stats.speed'],['法力上限','stats.mp']])changed(label,path)
  if(after?.state!==undefined)changed('状态','state',v=>gameStateLabels[String(v)]||String(v))
  if(event.kind==='home_placed') {
    const placement=(value:Record<string,unknown>|null)=>!value?'当时位置未记录':value.x===null||value.z===null?'收在藏品柜':`(${value.x}, ${value.z}) · ${value.rotation}°`
    changes.push({label:'摆放位置',before:placement(before),after:placement(after)})
  }
  let beforeObjects=stateObjects(before,id),afterObjects=stateObjects(after,id)
  // New receipts carry the immutable catalogue object used by the battle.
  // Historical art must not change when a later rules version edits the map.
  const saved=record(receipt.outpost_snapshot),savedTheme=string(saved?.theme),savedName=string(saved?.name)
  const captured=saved?.id===id&&savedTheme&&savedName&&typeof saved.is_boss==='boolean'&&gameModelFactory(`outpost:${savedTheme}:${saved.is_boss?'boss':'camp'}:occupied`)?{id,theme:savedTheme,name:savedName,is_boss:saved.is_boss}:undefined
  const site=captured||(context?.map?.version===event.rule_version?context.map.outposts.find(site=>site.id===id):undefined)
  if(kind==='occupation'&&site) {
    const at=(state:Record<string,unknown>|null):SceneObject[]|null=>typeof state?.occupied==='boolean'?[{id,title:site.name,x:0,z:0,scale:G.outpost_scale,model:`outpost:${site.theme}:${site.is_boss?'boss':'camp'}:${state.occupied?'occupied':'hostile'}`,state:state.occupied?'owned':undefined,subtitle:state.occupied?'已占领':'尚未占领'}]:null
    beforeObjects=at(before);afterObjects=at(after)
  }
  const sourceLabel=event.origin_type==='battle'?'保存的战报':event.origin_type==='leisure'?'休闲券':event.origin_type==='commitment'?'对赌合约':event.origin_type==='habit_occurrence'?'签到记录':event.origin_type==='game_order'?'培养或购买订单':event.origin_type==='legacy_world'?'旧世界记录':'系统记录'
  const href=event.origin_type==='battle'?`/world/battles/${encodeURIComponent(event.origin_id)}`:event.origin_type==='leisure'?`/leisure/${encodeURIComponent(event.origin_id)}`:['commitment','habit_occurrence','system_decision','challenge'].includes(event.origin_type)?'/system':undefined
  return {id:event.id,order:event.sequence,kind,tone,title,description:string(receipt.reason)||'这条记录已保存在世界历史中。',occurredAt:event.created_at,source:{label:sourceLabel,id:event.origin_id,href},ledgerIds:list(receipt.ledger_entry_ids),economics,changes,targetId:id,theme:site?.theme||'forest',beforeObjects,afterObjects,
    missing:beforeObjects===null||afterObjects===null?['这条事件未保存可完整重建的模型前后态；仅展示有依据的记录。']:[]}
}
