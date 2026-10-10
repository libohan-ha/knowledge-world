import {useRef} from 'react'
import {useFrame} from '@react-three/fiber'
import * as THREE from 'three'
import tokens from '../../../../docs/contracts/design-tokens.json'
import type {SceneBattleAction, SceneObject} from './scene-types'
import {groundHeight} from './coordinates'

const G = tokens.world.geometry, P = tokens.world.scene_palette, T = tokens.world.presentation
export function actionProgress(action: SceneBattleAction, now: number) {
  return Math.max(0, Math.min(1, action.frozenProgress ?? (now - action.startedAt) / Math.max(1, action.duration)))
}

/** Geometry motion only: damage/HP/outcome never enter this function. */
export function actionMotion(action: SceneBattleAction | null | undefined, object: SceneObject, objects: readonly SceneObject[], now: number, reduced: boolean) {
  const result = {x:0,z:0,tilt:0}
  if (!action || reduced) return result
  const progress = actionProgress(action, now), target = objects.find(o => o.id === action.targetId)
  if (progress >= 1 || !target) return result
  if (object.id === action.actorId && action.effect === 'physical') {
    const dx = target.x - object.x, dz = target.z - object.z, distance = Math.hypot(dx, dz)
    if (distance > 0) {const travel = Math.sin(Math.min(1, progress / T.battle_recovery_ratio) * Math.PI) * Math.min(G.battle_lunge, distance / 3);result.x = dx / distance * travel;result.z = dz / distance * travel}
  }
  if (object.id === action.targetId && progress > T.battle_impact_ratio && !['heal','shield'].includes(action.effect)) {
    const impact = (progress - T.battle_impact_ratio) / (1 - T.battle_impact_ratio)
    if (action.effect === 'dodge') result.z = Math.sin(impact * Math.PI) * G.battle_lunge / 2
    else result.tilt = Math.sin(impact * Math.PI * 3) * 0.1 * (1 - impact)
  }
  return result
}

export function BattleEffects({action, objects, theme, seed, reduced}: {action?: SceneBattleAction | null; objects: SceneObject[]; theme: string; seed: string | number; reduced: boolean}) {
  const root = useRef<THREE.Group>(null), arc = useRef<THREE.Mesh>(null), orb = useRef<THREE.Mesh>(null), shell = useRef<THREE.Mesh>(null)
  const actor = objects.find(o => o.id === action?.actorId), target = objects.find(o => o.id === action?.targetId)
  useFrame(() => {
    if (!action || !actor || !target || !root.current) return
    const progress = actionProgress(action, performance.now()), hit = Math.max(0, (progress - T.battle_impact_ratio) / (1 - T.battle_impact_ratio))
    root.current.visible = progress < 1 && !reduced
    if (orb.current) {
      const travel = Math.min(1, progress / T.battle_impact_ratio)
      orb.current.visible = progress < T.battle_impact_ratio
      orb.current.position.set(THREE.MathUtils.lerp(actor.x, target.x, travel), THREE.MathUtils.lerp(groundHeight(actor.x, actor.z, theme, seed), groundHeight(target.x, target.z, theme, seed), travel) + 0.5 + Math.sin(travel * Math.PI) * 0.35, THREE.MathUtils.lerp(actor.z, target.z, travel))
    }
    if (arc.current) {
      arc.current.visible = hit > 0
      arc.current.rotation.set(-Math.PI / 2 + (action.effect === 'physical' ? 0.6 : 0), 0, hit * Math.PI)
      arc.current.scale.setScalar(0.5 + hit * 0.7)
      ;(arc.current.material as THREE.MeshBasicMaterial).opacity = (1 - hit) * 0.85
    }
    if (shell.current) {
      shell.current.visible = hit > 0;shell.current.scale.setScalar(0.75 + Math.sin(hit * Math.PI) * 0.25)
      ;(shell.current.material as THREE.MeshBasicMaterial).opacity = Math.sin(hit * Math.PI) * 0.2
    }
  })
  if (!action || !actor || !target || reduced) return null
  const color = action.effect === 'heal' ? P.heal : action.effect === 'shield' || action.effect === 'magic' ? P.magic : P.selection
  return <group ref={root}>
    {action.effect === 'magic' && <mesh ref={orb}><icosahedronGeometry args={[0.075, 1]}/><meshBasicMaterial color={color}/></mesh>}
    <group position={[target.x, groundHeight(target.x, target.z, theme, seed) + 0.3, target.z]}>
      <mesh ref={arc}><torusGeometry args={[0.55, action.effect === 'physical' ? 0.035 : 0.018, 5, 32, action.effect === 'physical' ? Math.PI * 1.15 : Math.PI * 2]}/><meshBasicMaterial color={color} transparent depthWrite={false}/></mesh>
      {action.effect === 'shield' && <mesh ref={shell} position={[0,0.1,0]}><sphereGeometry args={[0.55, 20, 12]}/><meshBasicMaterial color={color} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide}/></mesh>}
      {action.effect === 'heal' && <mesh ref={shell} position={[0,0.25,0]}><cylinderGeometry args={[0.23,0.39,0.8,20,1,true]}/><meshBasicMaterial color={color} transparent opacity={0.2} depthWrite={false} side={THREE.DoubleSide}/></mesh>}
    </group>
  </group>
}
