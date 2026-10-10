import {useEffect, useMemo, useState} from 'react'
import type {ReactNode} from 'react'
import {BookOpen, Shield, Sparkles, Swords} from 'lucide-react'
import type {components} from '../../shared/api/schema'
import tokens from '../../../../docs/contracts/design-tokens.json'
import rules from '../../../../docs/contracts/system-core-rules.target.json'
import {roleLabels, skillLabels, unitObject, unitModel, type Unit} from './game-view'
import type {SceneObject, SceneSequence} from './scene-types'
import type {UnitPose} from './game-models'
import {WorldMap} from './WorldMap'
import './game-ui.css'

const poseLabels:Partial<Record<UnitPose,string>>={idle:'闲站',attack:'攻击',cast:'施法',victory:'胜利',rest:'休息'}
export type UnitShowcaseProps={unit:Unit;accountId?:string;displayEpoch?:string;actions?:ReactNode;sequence?:SceneSequence|null;reducedMotion?:boolean}
export function UnitShowcase(props:UnitShowcaseProps){return <Showcase key={props.unit.id} {...props}/>}
function Showcase({unit,accountId,displayEpoch,actions,sequence,reducedMotion}:UnitShowcaseProps) {
  const [previewStage,setPreviewStage]=useState<number|null>(null),[pose,setPose]=useState<UnitPose>('idle'),stage=previewStage??unit.visual_stage
  useEffect(()=>{setPreviewStage(null);setPose('idle')},[unit.visual_stage,unit.version])
  const objects=useMemo(()=>{
    const object=unitObject({...unit,visual_stage:stage},0,0,pose)
    return object?[{...object,scale:tokens.world.geometry.unit_showcase_scale,selectable:false}]:[]
  },[unit,stage,pose])
  const stages=unit.code==='hero'?rules.hero.visual_stage_min_levels.length:rules.monsters.visual_stage_min_levels.length
  const RoleIcon=unit.role==='tank'?Shield:unit.role==='support'?Sparkles:Swords
  return <section className="unit-showcase game-art-panel" data-unit-id={unit.id}>
    <div className="unit-showcase-art"><WorldMap objects={objects} compact showControls accountId={accountId} displayEpoch={displayEpoch} regionId={`unit:${unit.id}`} initialFocus={{x:0,z:0}} sceneSequence={sequence} reducedMotion={reducedMotion} sceneLabel={`${unit.name}的三维外观，可拖动或用按钮环绕观察`}/>
      <span className="unit-showcase-label">{previewStage!==null?'外观预览 · 不改变等级':`当前外观 · 阶段 ${unit.visual_stage}`}</span>
      {!objects.length&&<div className="game-empty unit-unready">这位伙伴的模型尚未就绪，属性与操作仍可查看。</div>}
      <div className="unit-pose-controls" aria-label="外观动作预览">{Object.entries(poseLabels).map(([key,label])=><button key={key} aria-pressed={pose===key} onClick={()=>setPose(key as UnitPose)}>{label}</button>)}</div>
    </div>
    <div className="game-panel-body"><header className="unit-showcase-heading"><div><span className="game-eyebrow">YOUR COMPANION</span><h2>{unit.name}</h2></div><span className="game-state-pill"><RoleIcon size={14}/>{roleLabels[unit.role]||unit.role} · Lv.{unit.level}</span></header>
      <div className="unit-stage-controls" aria-label="外观成长预览">{Array.from({length:stages},(_,index)=><button key={index} aria-pressed={stage===index+1} onClick={()=>setPreviewStage(index+1===unit.visual_stage?null:index+1)}><span>{String(index+1).padStart(2,'0')}</span>{index+1===unit.visual_stage?'当前模样':index+1>unit.visual_stage?'未来模样':'此前模样'}</button>)}</div>
      {previewStage!==null&&<p className="unit-preview-note">这里是模型外观预览。当前实际等级仍为 Lv.{unit.level}，阶段 {unit.visual_stage}。</p>}
      {unit.attributes&&<dl className="game-stat-list unit-attributes"><div><dt>力量</dt><dd>{unit.attributes.strength}</dd></div><div><dt>敏捷</dt><dd>{unit.attributes.agility}</dd></div><div><dt>法力属性</dt><dd>{unit.attributes.mana}</dd></div></dl>}
      <dl className="unit-combat-stats">{[['生命',unit.stats.hp],['物理攻击',unit.stats.physical_attack],['法术攻击',unit.stats.magic_attack],['护甲',unit.stats.defense],['魔抗',unit.stats.resistance],['速度',unit.stats.speed],['法力值',unit.stats.mp]].map(([label,value])=><div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      {unit.skill&&<div className="unit-skill"><BookOpen size={19}/><div><strong>{skillLabels[unit.skill.code]||unit.skill.code}</strong><p>{skillLabels[unit.skill.effect]||unit.skill.effect}{unit.skill.amount!==null&&unit.skill.amount!==undefined?` ${unit.skill.amount}`:''} · 每 {unit.skill.every_nth_action} 次行动，消耗 {unit.skill.mp_cost} 法力</p></div></div>}
      {unit.next_stage_level!==null&&unit.next_stage_level!==undefined&&<p className="unit-next-stage">下一阶段外观 · Lv.{unit.next_stage_level}</p>}
      {actions&&<div className="unit-growth-actions">{actions}</div>}
      <details className="unit-provenance"><summary>伙伴记录</summary><p>实例 · {unit.id}<br/>记录版本 · {unit.version}</p></details>
    </div>
  </section>
}

/** Catalogue art is explicitly a species preview, not a granted unit. */
export function SpeciesPreview({species,action,accountId,displayEpoch}:{species:components['schemas']['Species'];action?:ReactNode;accountId?:string;displayEpoch?:string}) {
  const model=unitModel({code:species.code,visual_stage:1}),objects:SceneObject[]=model?[{id:`species:${species.code}`,model,x:0,z:0,title:species.name,scale:tokens.world.geometry.unit_showcase_scale,selectable:false}]:[]
  return <article className="species-preview game-art-panel"><WorldMap objects={objects} compact accountId={accountId} displayEpoch={displayEpoch} regionId={`species:${species.code}`} reducedMotion/><div className="game-panel-body"><span className="game-eyebrow">物种图鉴 · 外观预览</span><h3>{species.name}</h3><p>{roleLabels[species.role]||species.role} · {skillLabels[species.skill.code]||species.skill.code}</p><strong className="species-price">{species.recruit_cost}<small>招募积分</small></strong>{action}</div></article>
}
