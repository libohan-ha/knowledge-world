/** Explicitly synthetic fixtures imported by art tests only. */
import type {Battle, GameEvent, Ticket, Unit} from './game-view'
import type {VisualEvent} from './feedback-state'

export function syntheticUnit(id:string,side='ally'):Unit {
  return {id,code:side==='ally'?'hero':'bramble',name:`synthetic · ${id}`,role:side==='ally'?'hero':'enemy',level:1,visual_stage:1,version:1,side,position:0,stats:{hp:100,mp:50,physical_attack:30,magic_attack:25,defense:5,resistance:3,speed:10,dodge_bps:0},skill:null}
}
export function syntheticBattle():Battle {
  const ally=syntheticUnit('synthetic-ally'),enemy=syntheticUnit('synthetic-enemy','enemy'),initial={hp:100,mp:50,shield:0},shielded={hp:100,mp:44,shield:30},hurt={hp:90,mp:44,shield:0},healed={hp:100,mp:36,shield:0}
  return {id:'synthetic-battle',outpost_id:'synthetic-outpost',state:'resolved',rule_version:'synthetic',catalog_version:'synthetic',seed:'synthetic',engine_version:'synthetic',job_id:'synthetic-job',created_at:'2026-10-10T10:00:00Z',completed_at:'2026-10-10T10:00:01Z',snapshot:{allies:[ally],enemies:[enemy],team_version:1,battle_rules:{},outpost:{id:'synthetic-outpost',name:'隔离测试据点',description:'仅用于前端不变量测试',region_id:'mist_forest',theme:'mist_forest',is_boss:false,prerequisites:[],enemies:[],position:{x:0,z:0},reward_points:0,trophy_code:null,status:'available'}},result:{outcome:'lost',reason:'round_limit',rounds:2,first_clear:false,reward_points:0,reward_item_id:null,occupation_changed:false,ledger_entry_ids:[],game_event_ids:[],command_id:'synthetic-command',wallet:{available_points:0,held_points:0,version:1},final_states:{[ally.id]:healed,[enemy.id]:initial},events:[
    {sequence:1,round:1,actor_id:ally.id,target_id:ally.id,action:'stone_guard',effect:'shield',damage_type:null,damage:0,absorbed:0,healing:0,shield_gain:30,dodged:false,died:false,actor_before:initial,target_before:initial,actor_after:shielded,target_after:shielded},
    {sequence:2,round:1,actor_id:enemy.id,target_id:ally.id,action:'attack',effect:'physical_damage',damage_type:'physical',damage:10,absorbed:30,healing:0,shield_gain:0,dodged:false,died:false,actor_before:initial,target_before:shielded,actor_after:initial,target_after:hurt},
    {sequence:3,round:2,actor_id:ally.id,target_id:ally.id,action:'starlight_heal',effect:'heal',damage_type:null,damage:0,absorbed:0,healing:10,shield_gain:0,dodged:false,died:false,actor_before:hurt,target_before:hurt,actor_after:healed,target_after:healed},
  ]}}
}
export function syntheticTicket():Ticket {
  return {id:'synthetic-ticket',catalog_id:'synthetic-reward',snapshot:{id:'synthetic-reward',code:'leisure_novel',name:'隔离测试 · 小说时光',description:'仅用于前端计时展示验证',price_points:1,duration_minutes:1,version:1},price_points:1,duration_seconds:60,used_seconds:59,remaining_seconds:1,state:'running',first_started_at:'2026-10-10T10:00:00Z',running_since:'2026-10-10T10:00:00Z',version:2,rule_version:'synthetic',server_time:'2026-10-10T10:00:59Z',ledger_entry_ids:[],game_event_ids:['synthetic-ticket-start']}
}
export function syntheticVisual(order:number,tone:VisualEvent['tone']='positive'):VisualEvent {
  return {id:`synthetic-event-${order}`,order,kind:'home',title:'隔离测试 · 家园变化',description:'仅用于前端防重验证',occurredAt:'2026-10-10T10:00:00Z',source:{label:'测试来源',id:`synthetic-source-${order}`},ledgerIds:[],tone,changes:[]}
}
export function syntheticEvent(overrides:Partial<GameEvent>={}):GameEvent {
  return {id:'synthetic-event',sequence:1,kind:'system_reward',object_id:'synthetic-action',region_id:null,origin_type:'system_decision',origin_id:'synthetic-decision',before:{net_points:0},after:{net_points:0,delta:0},receipt:{actual_points:0,reason:'这次记录没有积分变动',ledger_entry_ids:[]},rule_version:'synthetic',business_date:'2026-10-10',created_at:'2026-10-10T10:00:00Z',...overrides}
}
