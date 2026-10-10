import {useMemo, useRef} from 'react'
import {useFrame} from '@react-three/fiber'
import * as THREE from 'three'
import tokens from '../../../../docs/contracts/design-tokens.json'
import type {SceneSequence} from './scene-types'
import {sequenceFrame} from './timeline'

const G = tokens.world.geometry, P = tokens.world.scene_palette

/** Only draws a saved outcome. It has no API client, wallet or command hooks. */
export function GameEffects({sequence, position, reduced, particleBudget}: {sequence?: SceneSequence | null; position: [number, number, number]; reduced: boolean; particleBudget: number}) {
  const root = useRef<THREE.Group>(null), ring = useRef<THREE.Mesh>(null), beam = useRef<THREE.Mesh>(null), motes = useRef<THREE.InstancedMesh>(null)
  const object = useMemo(() => new THREE.Object3D(), [])
  const count = Math.min(G.effect_particle_count, particleBudget)
  useFrame(() => {
    if (!sequence || !root.current) return
    const frame = sequenceFrame(sequence, performance.now(), reduced)
    root.current.visible = !frame.finished && !reduced
    if (ring.current) {
      ring.current.scale.setScalar(0.72 + Math.sin(frame.progress * Math.PI) * 0.43)
      ring.current.rotation.z = frame.progress * Math.PI * 0.4
      ;(ring.current.material as THREE.MeshBasicMaterial).opacity = Math.sin(frame.progress * Math.PI) * 0.85
    }
    if (beam.current) {
      beam.current.scale.y = Math.max(0.001, Math.sin(frame.progress * Math.PI))
      ;(beam.current.material as THREE.MeshBasicMaterial).opacity = Math.sin(frame.progress * Math.PI) * 0.13
    }
    if (motes.current) {
      for (let i = 0; i < count; i++) {
        const phase = (frame.progress + i / count) % 1, angle = i * 2.399 + frame.progress
        object.position.set(Math.sin(angle) * G.effect_ring_radius * (0.6 + phase * 0.4), phase * G.effect_particle_height, Math.cos(angle) * G.effect_ring_radius * (0.6 + phase * 0.4))
        object.rotation.set(phase, angle, 0);object.scale.setScalar(Math.sin(phase * Math.PI) * 0.8);object.updateMatrix();motes.current.setMatrixAt(i, object.matrix)
      }
      motes.current.instanceMatrix.needsUpdate = true
    }
  })
  if (!sequence || reduced || sequence.correction) return null
  const color = sequence.kind === 'penalty' ? tokens.color.danger : sequence.kind === 'summon' || sequence.kind === 'training' ? P.magic : P.selection
  const major = ['summon', 'occupation', 'training'].includes(sequence.kind)
  return <group ref={root} position={position}>
    <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.035, 0]}><ringGeometry args={[G.effect_ring_radius * 0.86, G.effect_ring_radius, 48]}/><meshBasicMaterial color={color} transparent opacity={0.7} depthWrite={false} side={THREE.DoubleSide}/></mesh>
    {major && <mesh ref={beam} position={[0, 0.66, 0]}><cylinderGeometry args={[G.effect_ring_radius * 0.45, G.effect_ring_radius * 0.9, 1.3, 32, 1, true]}/><meshBasicMaterial color={color} transparent opacity={0.1} depthWrite={false} side={THREE.DoubleSide}/></mesh>}
    {count > 0 && sequence.kind !== 'penalty' && <instancedMesh ref={motes} args={[undefined, undefined, count]} frustumCulled={false}><octahedronGeometry args={[tokens.world.lighting.particle_size]}/><meshBasicMaterial color={color} transparent opacity={0.9} depthWrite={false}/></instancedMesh>}
  </group>
}
