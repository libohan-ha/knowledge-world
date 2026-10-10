import {Component, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react'
import type {ErrorInfo, ReactNode} from 'react'
import {Canvas, useFrame, useThree} from '@react-three/fiber'
import type {ThreeEvent} from '@react-three/fiber'
import * as THREE from 'three'
import {OrbitControls} from 'three/addons/controls/OrbitControls.js'
import {ArrowDown, ArrowUp, Hand, LocateFixed, Minus, Plus, RotateCcw, RotateCw, Settings2, Volume2, VolumeX, View} from 'lucide-react'
import type {RecordView} from '../../shared/api/client'
import {stageNames} from '../../shared/api/client'
import tokens from '../../../../docs/contracts/design-tokens.json'
import {buildingVariant, focusToLegacyViewport, groundHeight, legacyViewportToFocus, placementToWorld, riverCenter, stageOrder, stableHash, visualTheme, type LegacyViewport} from './coordinates'
import type {ActiveSequence} from './presentation'
import {createModelLibrary, creekGeometry, disposeModel, environmentGeometry, pixelTexture, type Model} from './models'
import {SceneEffects} from './effects'
import {useWorldSound} from './sound'
import {GameEffects} from './GameEffects'
import type {SceneObject, SceneSequence, CameraTarget, SceneBattleAction} from './scene-types'
import {sequenceFrame} from './timeline'
import {BattleEffects, actionMotion} from './BattleEffects'
import {savePresentationPreferences, usePresentationPreferences} from './presentation-preferences'
import './world.css'

const W = tokens.world, P = W.scene_palette, G = W.geometry, L = W.lighting
type Quality = keyof typeof W.quality_profiles
type Preferences = {azimuth: number; elevation: number; quality: Quality; autoCamera: boolean; sound: boolean; reducedMotion: boolean; mode: 'rotate' | 'pan'}
type SceneInstance = {id: string; model: string; x: number; y: number; z: number; rotation?: number; scale?: number; plot?: RecordView; object?: SceneObject; motion?: 'tree' | 'fox' | 'unit'; before?: boolean; reaction?: 'waiting' | 'celebrating'; landmark?: boolean; fog?: boolean}
type CameraCommand = {id: number; kind: 'rotate' | 'elevation' | 'zoom' | 'reset' | 'focus'; value?: number; target?: CameraTarget}
type ControlsApi = {command: (command: CameraCommand) => void}
type Diagnostics = {frames: number; calls: number; triangles: number; geometries: number; textures: number; plots: number; knowledgePlots: number; objects: number; visibleObjectCenters: number; renderer: string; quality: string; dpr: number; active: boolean; frameIntervals: number[]; mountedAt: number; readyAt?: number}
declare global {interface Window {__KW_WORLD_DIAGNOSTICS__?: {active: Record<string, Diagnostics>; unmounted: Diagnostics[]}}}

const libraries = new Map<string, {assets:ReturnType<typeof createModelLibrary>;users:number;timer?:ReturnType<typeof setTimeout>}>()
function useModels(theme:string) {
  if (!libraries.has(theme)) libraries.set(theme,{assets:createModelLibrary(theme),users:0})
  const current = libraries.get(theme)!
  if (current.timer) {clearTimeout(current.timer);current.timer=undefined}
  useEffect(() => {
    current.users++
    return () => {
      current.users--
      if (!current.users) current.timer = setTimeout(() => {if (!current.users) {current.assets.dispose();libraries.delete(theme)}}, 0)
    }
  }, [current,theme])
  return current.assets.models
}

function loadPreferences(key: string): Preferences {
  const defaults: Preferences = {azimuth: W.camera.azimuth_deg, elevation: W.camera.elevation_deg, quality: window.innerWidth <= tokens.breakpoint_px.mobile_max ? 'mobile' : 'desktop', autoCamera: true, sound: W.audio.default_enabled, reducedMotion: false, mode: 'rotate'}
  try {
    const saved = JSON.parse(localStorage.getItem(key) || 'null')
    if (!saved) return defaults
    return {...defaults, azimuth: Number.isFinite(saved.azimuth) ? saved.azimuth : defaults.azimuth, elevation: Math.max(W.camera.min_elevation_deg, Math.min(W.camera.max_elevation_deg, Number(saved.elevation) || defaults.elevation)), quality: Object.hasOwn(W.quality_profiles,saved.quality) ? saved.quality : defaults.quality, autoCamera: saved.autoCamera !== false, sound: saved.sound === true, reducedMotion: saved.reducedMotion === true, mode: saved.mode === 'pan' ? 'pan' : 'rotate'}
  } catch {return defaults}
}

const EMPTY_PLOTS: RecordView[] = [], EMPTY_OBJECTS: SceneObject[] = []
function sceneCenter(objects: SceneObject[]): CameraTarget {
  if (!objects.length) return {x:0,z:0}
  return {x:(Math.min(...objects.map(o=>o.x))+Math.max(...objects.map(o=>o.x)))/2,z:(Math.min(...objects.map(o=>o.z))+Math.max(...objects.map(o=>o.z)))/2}
}
function makeInstances(plots: RecordView[], theme: string, seed: string | number, outfit: boolean, pose: string, sequence?: ActiveSequence | null, compact = false, objects: SceneObject[] = EMPTY_OBJECTS, sceneSequence?: SceneSequence | null) {
  const entries: SceneInstance[] = [], lookup = new Map(plots.map(p => [`${p.grid_x},${p.grid_y}`, p]))
  const cells = new Map<string, {x: number; z: number; y: number; occupied: boolean}>()
  const put = (x: number, z: number) => {const key = `${x},${z}`;if (!cells.has(key) && cells.size < G.max_scene_cells) cells.set(key, {x, z, y: groundHeight(x, z, theme, seed), occupied: lookup.has(key)||objects.some(item=>Math.abs(item.x-x)<Math.max(G.scenery_clearance,(item.footprint||item.scale||1)/2)&&Math.abs(item.z-z)<Math.max(G.scenery_clearance,(item.footprint||item.scale||1)/2))})}
  const radius = compact ? G.preview_radius_cells : G.base_radius_cells
  const center = plots.length ? {x:0,z:0} : sceneCenter(objects), anchor = {x:Math.round(center.x),z:Math.round(center.z)}
  for (let x = -radius; x <= radius; x++) for (let z = -radius; z <= radius; z++) if (Math.abs(x) + Math.abs(z) <= radius + 2) put(x + anchor.x, z + anchor.z)
  // Only the returned region is modelled; absent points are never interpreted
  // as unseen knowledge. Additional cells here are explicitly scenery.
  for (const plot of plots) {put(plot.grid_x, plot.grid_y);for (const [dx, dz] of [[1,0],[-1,0],[0,1],[0,-1]]) put(plot.grid_x + dx, plot.grid_y + dz)}
  for (const item of objects) {
    const x = Math.round(item.x), z = Math.round(item.z)
    for (const [dx, dz] of [[0,0],[1,0],[-1,0],[0,1],[0,-1]]) put(x + dx, z + dz)
    const cell = cells.get(`${x},${z}`);if (cell) cell.occupied = true
    const entry: SceneInstance = {id:item.id,model:item.model,x:item.x,z:item.z,y:groundHeight(item.x,item.z,theme,seed)+0.022+(item.elevation||0),rotation:(item.rotation||0)*Math.PI/180,scale:item.scale,object:item,motion:item.motion}
    if (entry.motion === 'unit' && entry.id !== sceneSequence?.targetId && sceneSequence && ['occupation','summon','training','home'].includes(sceneSequence.kind) && !sceneSequence.correction) {
      entries.push({...entry,reaction:'waiting'})
      entries.push({...entry,id:`${entry.id}:reaction`,model:entry.model.replace(/:[^:]+$/,':victory'),reaction:'celebrating'})
    } else entries.push(entry)
    if (sceneSequence?.targetId === item.id && sceneSequence.beforeModel && sceneSequence.beforeModel !== item.model) entries.push({...entry,id:`${item.id}:before`,model:sceneSequence.beforeModel,before:true})
  }
  for (const plot of plots) {
    const x = plot.grid_x * W.world_units_per_grid_cell, z = plot.grid_y * W.world_units_per_grid_cell, y = groundHeight(x, z, theme, seed) + 0.022
    const entry = {id: plot.id, x, y, z, plot}, before = sequence && sequence.event.point_id === plot.point_id && sequence.event.kind === 'learning' ? sequence.event.before.best_stage : null
    const best = stageOrder[plot.best_stage as keyof typeof stageOrder] || 0
    if (plot.terrain === 'camp') {
      entries.push({...entry, model: 'camp'})
      entries.push({id: `fox:${plot.id}`, model: `fox:${pose}:${outfit}`, x: x + 0.55, y, z: z + 0.38, scale: G.companion_scale, motion: 'fox'})
    } else if (best >= 2 && !plot.presentation_landmark_only && !plot.chapter_landmark) {
      const variant = buildingVariant(plot.point_id, seed)
      entries.push({...entry, model: `building:${theme}:${variant}:${best - 1}`})
      if (before && stageOrder[before] >= 2 && before !== plot.best_stage) entries.push({...entry, id: `${plot.id}:before`, model: `building:${theme}:${variant}:${stageOrder[before] - 1}`, before: true})
    } else if (plot.current_stage === 'exploring' && !plot.presentation_landmark_only) entries.push({...entry, model: 'plant:0', scale: 1.5})
    if (plot.chapter_landmark) entries.push({...entry, id: `landmark:${plot.id}`, model: `landmark:${theme}`, scale: G.landmark_scale, landmark: true})
    for (const plant of plot.plants || []) entries.push({id: plant.id, model: `plant:${plant.growth_stage}`, x: x - 0.32, y, z: z + 0.37, plot})
    for (const item of plot.items || []) {
      const offset = placementToWorld(item.placement || {}), model = item.kind === 'upgrade' ? 'garden' : item.kind === 'collectible' ? 'plant:2' : 'lamp'
      entries.push({id: item.id, model, x: x + 0.33 + offset.x, y, z: z - 0.05 + offset.z, rotation: Number(item.placement?.rotation || 0) * Math.PI / 180, plot})
    }
  }
  for (const cell of cells.values()) {
    const hash = stableHash(`${seed}:${cell.x}:${cell.z}`), edge = Math.abs(cell.x-anchor.x) + Math.abs(cell.z-anchor.z)
    if (!compact && !cell.occupied && cell.x !== 0 && cell.z !== 0 && Math.abs(cell.x-riverCenter(cell.z))>0.55 && ((hash>>>8) % 4 === 0 || edge >= G.base_radius_cells && (hash>>>12) % 3 !== 0)) entries.push({id: `tree:${cell.x}:${cell.z}`, model: (hash>>>16) % 5 === 0 ? 'pine' : (hash>>>20)%3===0?'tree:1':'tree', x: cell.x + ((hash>>>7)%100/100-0.5)*G.tree_cluster_offset, y: cell.y + 0.02, z: cell.z - 0.1, scale: G.tree_scale * (G.tree_min_scale + (hash>>>3)%100/100*G.tree_scale_variation), motion: 'tree'})
  }
  if (!compact) {
    for (const [dx,dz] of [[1,2],[-1,-2],[2,-1]]) {const x=dx+anchor.x,z=dz+anchor.z;if(!cells.get(`${x},${z}`)?.occupied)entries.push({id: `lamp:${x}:${z}`, model: 'lamp', x: x + 0.38, y: groundHeight(x,z,theme,seed), z: z + 0.38})}
    for (const z of [0,3]) if (cells.has(`-3,${z}`)) entries.push({id: `bridge:${z}`, model: 'bridge', x: riverCenter(z), y: groundHeight(-3,z,theme,seed) - 0.015, z})
  }
  return {entries, cells: [...cells.values()]}
}

function InstanceGroup({model, entries, material, lightMaterial, reduced, sequence, sceneSequence, battleAction, objects, onSelect, onObjectSelect, canSelect}: {model: Model; entries: SceneInstance[]; material: THREE.Material; lightMaterial: THREE.Material; reduced: boolean; sequence?: ActiveSequence | null; sceneSequence?: SceneSequence | null; battleAction?: SceneBattleAction | null; objects: SceneObject[]; onSelect?: (plot: RecordView) => void; onObjectSelect?: (object: SceneObject) => void; canSelect: () => boolean}) {
  const body = useRef<THREE.InstancedMesh>(null), light = useRef<THREE.InstancedMesh>(null)
  const object = useMemo(() => new THREE.Object3D(), [])
  const update = (time: number) => {
    entries.forEach((entry, index) => {
      let scale = entry.scale ?? 1, lift = 0, tilt = 0
      const battle = entry.object ? actionMotion(battleAction, entry.object, objects, performance.now(), reduced) : {x:0,z:0,tilt:0}
      tilt += battle.tilt
      if (!reduced && entry.motion === 'tree') tilt = Math.sin(time / L.environment_cycle_seconds * Math.PI * 2 + entry.x) * 0.012
      if (!reduced && (entry.motion === 'fox' || entry.motion === 'unit')) lift = Math.sin(time / 2 * Math.PI + entry.x) * 0.006
      if (sceneSequence && entry.object?.id === sceneSequence.targetId) {
        const frame = sequenceFrame(sceneSequence, performance.now(), reduced)
        if (['home','summon','training','occupation','history'].includes(sceneSequence.kind) && !sceneSequence.correction) {
          scale *= entry.before ? frame.build < 0.18 ? 1 : 0.0001 : Math.max(0.0001, frame.easedBuild)
          if (!entry.before) lift -= (1 - frame.easedBuild) * 0.18
        } else if (entry.before) scale = 0.0001
      }
      if (sceneSequence && entry.reaction) {
        const celebrating = !reduced && sequenceFrame(sceneSequence, performance.now(), reduced).companion
        if (celebrating !== (entry.reaction === 'celebrating')) scale = 0.0001
        else if (celebrating) lift += Math.max(0, Math.sin((performance.now() - sceneSequence.startedAt) / tokens.motion_ms.companion_reaction * Math.PI * 2)) * 0.035
      }
      if (sequence && entry.plot?.point_id === sequence.event.point_id) {
        const elapsed = performance.now() - sequence.startedAt
        if (entry.landmark && sequence.event.kind === 'chapter_landmark') {
          const progress = reduced ? 1 : THREE.MathUtils.clamp((elapsed - W.presentation.landmark_cues_ms.build) / (W.presentation.landmark_cues_ms.lights - W.presentation.landmark_cues_ms.build), 0, 1)
          scale *= Math.max(0.0001, 1 - (1 - progress) ** 3);lift -= (1 - progress) * 0.24
        } else if (sequence.event.kind === 'learning' && sequence.event.coverage === 'complete' && entry.model.startsWith('building:')) {
          const progress = reduced || sequence.event.is_correction ? 1 : THREE.MathUtils.clamp(elapsed / tokens.motion_ms.building_growth, 0, 1)
          scale *= entry.before ? (progress < 0.12 ? 1 : 0.0001) : Math.max(0.0001, (1 - (1 - progress) ** 3))
          if (!entry.before) lift -= (1 - progress) * 0.12
        }
      } else if (entry.before && !sceneSequence) scale = 0.0001
      object.position.set(entry.x + battle.x, entry.y + lift, entry.z + battle.z);object.rotation.set(0, entry.rotation || 0, tilt);object.scale.setScalar(scale);object.updateMatrix()
      body.current?.setMatrixAt(index, object.matrix)
      if (sequence && entry.landmark && !reduced && performance.now() - sequence.startedAt < W.presentation.landmark_cues_ms.lights) {object.scale.setScalar(0.0001);object.updateMatrix()}
      if (sceneSequence && entry.object && sceneSequence.targetId === entry.object.id && !sequenceFrame(sceneSequence,performance.now(),reduced).lights) {object.scale.setScalar(0.0001);object.updateMatrix()}
      light.current?.setMatrixAt(index, object.matrix)
    })
    if (body.current) body.current.instanceMatrix.needsUpdate = true
    if (light.current) light.current.instanceMatrix.needsUpdate = true
  }
  useLayoutEffect(() => {update(0);body.current?.computeBoundingSphere();light.current?.computeBoundingSphere()}, [entries, sequence, sceneSequence, battleAction, reduced])
  useFrame(({clock}) => {if ((!reduced && entries.some(e => e.motion)) || sequence || sceneSequence || battleAction) update(clock.elapsedTime)})
  const select = (event: ThreeEvent<MouseEvent>) => {if (!canSelect()) return;const entry = entries[event.instanceId ?? -1];if (entry?.plot) {event.stopPropagation();onSelect?.(entry.plot)} else if (entry?.object && entry.object.selectable !== false) {event.stopPropagation();onObjectSelect?.(entry.object)}}
  return <group dispose={null}><instancedMesh ref={body} args={[model.body, material, entries.length]} onClick={select} castShadow receiveShadow frustumCulled={false}/>{model.light.getAttribute('position')&&<instancedMesh ref={light} args={[model.light, lightMaterial, entries.length]} onClick={select} frustumCulled={false}/>}</group>
}

function CameraRig({initial, preferences, setPreferences, apiRef, onViewport, focusId, selected, sequenceTarget, sequence, sceneSequence, reduced, compact, framing, onManual, interactionBlocked = false}: {initial?: LegacyViewport; preferences: Preferences; setPreferences: (p: Preferences) => void; apiRef: React.RefObject<ControlsApi | null>; onViewport?: (view: LegacyViewport) => void; focusId?: string; selected?: CameraTarget & {id:string;pointId?:string}; sequenceTarget?: CameraTarget; sequence?: ActiveSequence | null; sceneSequence?: SceneSequence | null; reduced: boolean; compact: boolean; framing?: 'room'; onManual: () => void; interactionBlocked?: boolean}) {
  const {camera, gl, size, invalidate} = useThree(), controls = useRef<OrbitControls | null>(null), baseZoom = useRef(1), initialized = useRef(false)
  const propsRef = useRef({preferences, setPreferences, onViewport, onManual});propsRef.current = {preferences, setPreferences, onViewport, onManual}
  const transition = useRef<{at: number; from: THREE.Vector3; to: THREE.Vector3} | null>(null)
  const manual = useRef(false), changed = useRef(false)
  const blocked = useRef(interactionBlocked);blocked.current = interactionBlocked
  const editing = () => !!document.activeElement?.matches('input,textarea,select,[contenteditable="true"]')
  const savedFocus = useRef(initial ? legacyViewportToFocus(initial) : {x: 0, z: 0, zoom: compact ? 1.15 : 1})
  const sync = () => {
    const control = controls.current;if (!control) return
    const view = focusToLegacyViewport({x: control.target.x, z: control.target.z, zoom: camera.zoom / baseZoom.current})
    propsRef.current.onViewport?.(view)
    const next = {...propsRef.current.preferences, azimuth: control.getAzimuthalAngle() * 180 / Math.PI, elevation: 90 - control.getPolarAngle() * 180 / Math.PI}
    propsRef.current.setPreferences(next)
  }
  const focus = (target?: CameraTarget, animate = true) => {
    const control = controls.current;if (!control) return
    const to = new THREE.Vector3(target?.x ?? savedFocus.current.x, compact?G.preview_look_height:0, target?.z ?? savedFocus.current.z)
    if (animate && !reduced) transition.current = {at: performance.now(), from: control.target.clone(), to}
    else {const offset = camera.position.clone().sub(control.target);control.target.copy(to);camera.position.copy(to).add(offset);control.update();sync()}
    invalidate()
  }
  useLayoutEffect(() => {
    const control = new OrbitControls(camera, gl.domElement);controls.current = control
    // Three r186 resolves getRootNode() again in disconnect(). R3F can dispose
    // after its canvas is detached, so also release from the original root.
    const keyboardRoot=gl.domElement.getRootNode()
    const keyboardHandlers=control as unknown as {_interceptControlDown: EventListener; _interceptControlUp: EventListener}
    control.enableDamping = false;control.enableRotate = true;control.enableZoom = true;control.enablePan = true
    control.minPolarAngle = THREE.MathUtils.degToRad(90 - W.camera.max_elevation_deg);control.maxPolarAngle = THREE.MathUtils.degToRad(90 - W.camera.min_elevation_deg)
    control.screenSpacePanning = false;control.zoomSpeed = 0.8;control.rotateSpeed = 0.65
    const onStart = () => {transition.current = null;manual.current = true;changed.current = false;propsRef.current.onManual()}
    const onChange = () => {changed.current = true;invalidate();const element = gl.domElement;const view = focusToLegacyViewport({x: control.target.x, z: control.target.z, zoom: camera.zoom / baseZoom.current});element.dataset.viewport = JSON.stringify(view);element.dataset.azimuth = String(control.getAzimuthalAngle() * 180 / Math.PI);element.dataset.elevation = String(90 - control.getPolarAngle() * 180 / Math.PI)}
    const onEnd = () => {if (changed.current) sync()}
    control.addEventListener('start', onStart);control.addEventListener('change', onChange);control.addEventListener('end', onEnd)
    const checkInput = () => {
      const dialog = document.querySelector('dialog[open],[role="dialog"][aria-modal="true"]')
      control.enabled = !blocked.current && !gl.domElement.closest('[inert]') && (!dialog || dialog.contains(gl.domElement))
      if (!control.enabled || editing()) transition.current = null
    }
    const observer = new MutationObserver(checkInput)
    observer.observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['open','inert']})
    document.addEventListener('focusin',checkInput);checkInput()
    apiRef.current = {command(command) {
      onStart()
      if (command.kind === 'focus') {focus(command.target);return}
      if (command.kind === 'reset') {
        const offset = new THREE.Vector3().setFromSphericalCoords(G.camera_radius, THREE.MathUtils.degToRad(90 - W.camera.elevation_deg), THREE.MathUtils.degToRad(W.camera.azimuth_deg))
        control.target.set(savedFocus.current.x, compact?G.preview_look_height:0, savedFocus.current.z);camera.position.copy(control.target).add(offset);camera.zoom = baseZoom.current * W.camera.default_zoom
      } else if (command.kind === 'zoom') camera.zoom = THREE.MathUtils.clamp(camera.zoom * (command.value || 1), control.minZoom, control.maxZoom)
      else {
        const offset = camera.position.clone().sub(control.target), spherical = new THREE.Spherical().setFromVector3(offset)
        if (command.kind === 'rotate') spherical.theta += THREE.MathUtils.degToRad(command.value || 0)
        else spherical.phi = THREE.MathUtils.clamp(spherical.phi - THREE.MathUtils.degToRad(command.value || 0), control.minPolarAngle, control.maxPolarAngle)
        camera.position.copy(control.target).add(offset.setFromSpherical(spherical))
      }
      camera.updateProjectionMatrix();control.update();sync();invalidate()
    }}
    return () => {apiRef.current = null;transition.current = null;observer.disconnect();document.removeEventListener('focusin',checkInput);control.removeEventListener('start', onStart);control.removeEventListener('change', onChange);control.removeEventListener('end', onEnd);keyboardRoot.removeEventListener('keydown',keyboardHandlers._interceptControlDown,true);keyboardRoot.removeEventListener('keyup',keyboardHandlers._interceptControlUp,true);control.dispose();controls.current = null}
  }, [camera, gl, invalidate])
  useLayoutEffect(() => {
    const control = controls.current;if (!control) return
    const normalZoom = initialized.current ? camera.zoom / baseZoom.current : savedFocus.current.zoom
    baseZoom.current = size.height / (framing==='room'?G.room_preview_world_height:compact ? G.preview_world_height : G.camera_world_height)
    camera.zoom = baseZoom.current * normalZoom;control.minZoom = baseZoom.current * W.camera.min_zoom;control.maxZoom = baseZoom.current * W.camera.max_zoom
    if (!initialized.current) {
      const spherical = new THREE.Spherical(G.camera_radius, THREE.MathUtils.degToRad(90 - preferences.elevation), THREE.MathUtils.degToRad(preferences.azimuth))
      control.target.set(savedFocus.current.x, compact?G.preview_look_height:0, savedFocus.current.z);camera.position.copy(control.target).add(new THREE.Vector3().setFromSpherical(spherical));initialized.current = true
    }
    camera.updateProjectionMatrix();control.update();invalidate()
  }, [size.height, size.width, compact, framing, camera, invalidate])
  useEffect(() => {
    const control = controls.current;if (!control) return
    control.mouseButtons.LEFT = preferences.mode === 'pan' ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE
    control.mouseButtons.RIGHT = THREE.MOUSE.PAN
    control.touches.ONE = preferences.mode === 'pan' ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE;control.touches.TWO = THREE.TOUCH.DOLLY_PAN
  }, [preferences.mode])
  useEffect(() => {if (focusId && selected) focus(selected)}, [focusId])
  useEffect(() => {
    manual.current = false
    if (preferences.autoCamera && !reduced && !blocked.current && !editing() && controls.current?.enabled) {
      if (sceneSequence && sequenceTarget) focus(sequenceTarget)
      else if (selected && sequence && sequence.event.point_id === selected.pointId) focus(selected)
    }
  }, [sequence?.event.id, sceneSequence?.id])
  useEffect(() => {
    if (!preferences.autoCamera || reduced || interactionBlocked) transition.current = null
    if (controls.current && interactionBlocked) controls.current.enabled = false
    if (controls.current && !interactionBlocked && !document.querySelector('dialog[open],[role="dialog"][aria-modal="true"]')) controls.current.enabled = true
  }, [preferences.autoCamera, reduced, interactionBlocked])
  useFrame(() => {
    const control = controls.current, tween = transition.current
    if (!control || !tween) return
    const progress = THREE.MathUtils.clamp((performance.now() - tween.at) / tokens.motion_ms.camera_focus, 0, 1), offset = camera.position.clone().sub(control.target)
    control.target.lerpVectors(tween.from, tween.to, 1 - (1 - progress) ** 3);camera.position.copy(control.target).add(offset);control.update();invalidate()
    if (progress === 1) {transition.current = null;sync()}
  })
  return null
}

function Scenery({cells, theme, seed, reduced, material, compact}: {cells: ReturnType<typeof makeInstances>['cells']; theme: string; seed: string | number; reduced: boolean; material: THREE.Material;compact:boolean}) {
  const ground = useMemo(() => environmentGeometry(cells, theme, seed, compact), [cells, theme, seed, compact]), creek = useMemo(()=>creekGeometry(cells),[cells])
  const water = useRef<THREE.Mesh>(null), waterMaterial = useMemo(() => new THREE.MeshStandardMaterial({color: P.water, metalness: 0.25, roughness: 0.32, transparent: true, opacity: 0.86,side:THREE.DoubleSide}), [])
  useEffect(() => () => disposeModel(ground), [ground]);useEffect(() => () => creek.dispose(),[creek]);useEffect(() => () => waterMaterial.dispose(), [waterMaterial])
  useFrame(({clock}) => {if (!reduced && water.current) water.current.position.y = Math.sin(clock.elapsedTime / L.water_cycle_seconds * Math.PI * 2) * 0.006})
  return <group dispose={null}><mesh geometry={ground.body} material={material} receiveShadow/>
    {!compact&&<mesh ref={water} geometry={creek} material={waterMaterial} receiveShadow/>}
  </group>
}

function FogAndMarkers({plots, selected, theme, seed, sequence, reduced, onSelect, canSelect}: {plots: RecordView[]; selected?: string; theme: string; seed: string | number; sequence?: ActiveSequence | null; reduced: boolean; onSelect?: (plot: RecordView) => void; canSelect: () => boolean}) {
  const fog = useRef<THREE.InstancedMesh>(null), object = useMemo(() => new THREE.Object3D(), [])
  const fogPlots = useMemo(() => plots.filter(p => p.terrain !== 'camp' && !p.presentation_landmark_only && (p.current_stage === 'unseen' || sequence && sequence.event.point_id === p.point_id && (sequence.event.before.current_stage === 'unseen' || sequence.event.kind === 'chapter_landmark'))), [plots, sequence])
  const update = () => {
    fogPlots.forEach((plot, index) => {
      let scale = 1
      if (plot.current_stage !== 'unseen') scale = !sequence || reduced ? 0.0001 : Math.max(0.0001, 1 - THREE.MathUtils.clamp((performance.now() - sequence.startedAt - (sequence.event.kind==='chapter_landmark'?W.presentation.landmark_cues_ms.fog:0)) / tokens.motion_ms.fog_reveal, 0, 1))
      object.position.set(plot.grid_x, groundHeight(plot.grid_x,plot.grid_y,theme,seed) + 0.11, plot.grid_y);object.scale.set(0.43 * scale, 0.11 * scale, 0.43 * scale);object.updateMatrix();fog.current?.setMatrixAt(index, object.matrix)
    });if (fog.current) fog.current.instanceMatrix.needsUpdate = true
  }
  useLayoutEffect(() => {update();fog.current?.computeBoundingSphere()}, [fogPlots, reduced, sequence]);useFrame(() => {if (sequence) update()})
  const select = (plot: RecordView, event: ThreeEvent<MouseEvent>) => {if (canSelect()) {event.stopPropagation();onSelect?.(plot)}}
  return <group>
    {!!fogPlots.length&&<instancedMesh ref={fog} args={[undefined, undefined, fogPlots.length]} frustumCulled={false} onClick={e => {const p = fogPlots[e.instanceId ?? -1];if (p) select(p,e)}}><icosahedronGeometry args={[1, 1]}/><meshStandardMaterial color={P.unknown} transparent opacity={0.55} roughness={1}/></instancedMesh>}
    {plots.map(plot => <group key={plot.id} position={[plot.grid_x, groundHeight(plot.grid_x,plot.grid_y,theme,seed) + 0.058, plot.grid_y]}>
      <mesh rotation={[-Math.PI / 2,0,0]} onClick={e => select(plot,e)}><planeGeometry args={[0.96,0.96]}/><meshBasicMaterial transparent opacity={0} depthWrite={false}/></mesh>
      {selected === plot.id&&<mesh rotation={[-Math.PI / 2,0,0]}><ringGeometry args={[0.55,0.55 + G.selection_line_width,4,1,Math.PI / 4]}/><meshBasicMaterial color={P.selection} depthWrite={false} side={THREE.DoubleSide}/></mesh>}
      {plot.due&&<mesh position={[0.35,0.19,0.35]} rotation={[0,Math.PI / 4,0]}><octahedronGeometry args={[0.06]}/><meshStandardMaterial color={P.flag} emissive={P.flag} emissiveIntensity={0.2}/></mesh>}
    </group>)}
  </group>
}

function ObjectMarkers({objects, selected, theme, seed, sequence, reduced, onSelect, canSelect}: {objects: SceneObject[]; selected?: string; theme: string; seed: string | number; sequence?: SceneSequence | null; reduced: boolean; onSelect?: (object: SceneObject) => void; canSelect: () => boolean}) {
  const fog = useRef<THREE.InstancedMesh>(null), hits=useRef<THREE.InstancedMesh>(null), rings=useRef<THREE.InstancedMesh>(null), dummy = useMemo(() => new THREE.Object3D(), [])
  const selectable=useMemo(()=>objects.filter(o=>o.selectable!==false),[objects]), available=useMemo(()=>selectable.filter(o=>o.state==='available'&&o.id!==selected),[selectable,selected]), focused=selectable.find(o=>o.id===selected)
  const obscured = useMemo(() => objects.filter(object => object.state === 'locked' || sequence?.kind === 'occupation' && sequence.targetId === object.id), [objects, sequence])
  const updateFog = () => {
    obscured.forEach((item, i) => {
      const scale = item.state === 'locked' ? 1 : sequence ? sequenceFrame(sequence,performance.now(),reduced).fog : 0
      dummy.position.set(item.x,groundHeight(item.x,item.z,theme,seed)+0.35,item.z);dummy.scale.set(0.8*scale,0.33*scale,0.7*scale);dummy.updateMatrix();fog.current?.setMatrixAt(i,dummy.matrix)
    })
    if(fog.current)fog.current.instanceMatrix.needsUpdate=true
  }
  useLayoutEffect(() => {updateFog();fog.current?.computeBoundingSphere()}, [obscured, reduced])
  useLayoutEffect(()=>{
    for (const [entries,mesh] of [[selectable,hits.current],[available,rings.current]] as const) {
      entries.forEach((item,index)=>{dummy.position.set(item.x,groundHeight(item.x,item.z,theme,seed)+0.055,item.z);dummy.rotation.set(-Math.PI/2,0,0);dummy.scale.setScalar(1);dummy.updateMatrix();mesh?.setMatrixAt(index,dummy.matrix)})
      if(mesh){mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere()}
    }
    dummy.rotation.set(0,0,0)
  },[selectable,available,theme,seed])
  useFrame(() => {if(sequence)updateFog()})
  return <group>
    {obscured.length > 0 && <instancedMesh ref={fog} args={[undefined,undefined,obscured.length]} frustumCulled={false}><icosahedronGeometry args={[1,1]}/><meshStandardMaterial color={P.unknown} transparent opacity={0.5} depthWrite={false}/></instancedMesh>}
    {!!selectable.length&&<instancedMesh ref={hits} args={[undefined,undefined,selectable.length]} frustumCulled={false} onClick={event=>{const item=selectable[event.instanceId??-1];if(item&&canSelect()){event.stopPropagation();onSelect?.(item)}}}><circleGeometry args={[0.56,16]}/><meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false}/></instancedMesh>}
    {!!available.length&&<instancedMesh ref={rings} args={[undefined,undefined,available.length]} frustumCulled={false}><ringGeometry args={[0.57,0.57+G.selection_line_width,48]}/><meshBasicMaterial color={P.exploration} transparent opacity={0.6} depthWrite={false} side={THREE.DoubleSide}/></instancedMesh>}
    {focused&&<mesh position={[focused.x,groundHeight(focused.x,focused.z,theme,seed)+0.057,focused.z]} rotation={[-Math.PI/2,0,0]}><ringGeometry args={[0.57,0.57+G.selection_line_width,48]}/><meshBasicMaterial color={P.selection} depthWrite={false} side={THREE.DoubleSide}/></mesh>}
  </group>
}

function Atmosphere({quality, reduced, daylight}: {quality: Quality; reduced: boolean; daylight: boolean}) {
  const group = useRef<THREE.Points>(null), count = W.quality_profiles[quality].ambient_particles_max
  const positions = useMemo(() => {const data = new Float32Array(count * 3);for (let i = 0; i < count; i++) {const h = stableHash(`firefly:${i}`);data[i*3] = (h % 1300) / 100 - 6.5;data[i*3+1] = 0.4 + (h % 250) / 100;data[i*3+2] = (Math.floor(h / 1300) % 1300) / 100 - 6.5}return data}, [count])
  useFrame(({clock}) => {if (group.current && !reduced) {group.current.position.y = Math.sin(clock.elapsedTime / L.environment_cycle_seconds * Math.PI * 2) * 0.07;group.current.rotation.y = Math.sin(clock.elapsedTime / L.environment_cycle_seconds) * 0.012}})
  return count > 0 && !reduced && !daylight ? <points ref={group}><bufferGeometry><bufferAttribute attach="attributes-position" args={[positions,3]}/></bufferGeometry><pointsMaterial color={P.window} size={L.particle_size} transparent opacity={0.65} sizeAttenuation depthWrite={false}/></points> : null
}

function Runtime({sceneId, plots, objects, quality, onReady}: {sceneId: string; plots: RecordView[]; objects: SceneObject[]; quality: Quality; onReady: () => void}) {
  const {gl, camera, invalidate} = useThree(), frames = useRef(0), last = useRef(0), ready = useRef(false), previous = useRef(0), intervals = useRef<number[]>([]), point=useMemo(()=>new THREE.Vector3(),[])
  useEffect(() => {
    const diagnostics = window.__KW_WORLD_DIAGNOSTICS__ ||= {active: {}, unmounted: []}
    diagnostics.active[sceneId] = {frames:0,calls:0,triangles:0,geometries:0,textures:0,plots:plots.length,knowledgePlots:plots.filter(p=>p.point_id).length,objects:objects.length,visibleObjectCenters:0,renderer:'',quality,dpr:gl.getPixelRatio(),active:true,frameIntervals:[],mountedAt:performance.now()}
    invalidate()
    return () => {const final = diagnostics.active[sceneId];if (final) diagnostics.unmounted.push({...final,active:false});diagnostics.unmounted = diagnostics.unmounted.slice(-W.performance_targets.route_roundtrips * 2);delete diagnostics.active[sceneId]}
  }, [sceneId, gl, quality])
  useFrame(() => {
    frames.current++
    const now=performance.now(),stats=window.__KW_WORLD_DIAGNOSTICS__?.active[sceneId]
    if(previous.current&&!document.hidden)intervals.current.push(now-previous.current)
    previous.current=now
    const limit=W.performance_targets.sample_seconds*W.performance_targets.desktop_fps_target*3
    if(intervals.current.length>limit)intervals.current.splice(0,intervals.current.length-limit)
    if (!ready.current && frames.current >= 1) {ready.current = true;if(stats)stats.readyAt=now;onReady()}
    if (performance.now() - last.current < G.diagnostic_interval_ms && ready.current) return
    last.current = performance.now()
    const context = gl.getContext(), extension = context.getExtension('WEBGL_debug_renderer_info'), renderer = extension ? context.getParameter(extension.UNMASKED_RENDERER_WEBGL) : context.getParameter(context.RENDERER)
    const visibleObjectCenters=objects.filter(object=>{point.set(object.x,(object.elevation||0)+0.35,object.z).project(camera);return Math.abs(point.x)<=1&&Math.abs(point.y)<=1&&Math.abs(point.z)<=1}).length
    if (stats) Object.assign(stats,{frames:frames.current,calls:gl.info.render.calls,triangles:gl.info.render.triangles,geometries:gl.info.memory.geometries,textures:gl.info.memory.textures,renderer:String(renderer),frameIntervals:[...intervals.current],objects:objects.length,visibleObjectCenters})
  },2)
  return null
}

function SceneContents(props: WorldMapProps & {preferences: Preferences; setPreferences: (p: Preferences) => void; apiRef: React.RefObject<ControlsApi | null>; reduced: boolean; canSelect: () => boolean; onReady: () => void; onManual: () => void; sceneId: string}) {
  const {plots = EMPTY_PLOTS, objects = EMPTY_OBJECTS, selected, sequence, sceneSequence, seed = 0, daylight = false, outfit = false, companionPose = 'idle', preferences, setPreferences, reduced, compact = false, canSelect, onSelect} = props
  const theme = visualTheme(props.theme)
  const models = useModels(theme), content = useMemo(() => makeInstances(plots, theme, seed, outfit, companionPose, sequence, compact, objects, sceneSequence), [plots,theme,seed,outfit,companionPose,sequence,compact,objects,sceneSequence])
  const grouped = useMemo(() => {const map = new Map<string,SceneInstance[]>();for (const item of content.entries) {if (!map.has(item.model)) map.set(item.model,[]);map.get(item.model)!.push(item)}return map}, [content])
  const materials = useMemo(() => {const texture = pixelTexture();return {texture, body:new THREE.MeshStandardMaterial({vertexColors:true,map:texture,roughness:0.92,metalness:0}), light:new THREE.MeshStandardMaterial({color:daylight?P.window_day:P.window,emissive:daylight?P.window_day:P.window,emissiveIntensity:daylight?L.window_emissive_day:L.window_emissive_night,roughness:0.6})}}, [daylight])
  useEffect(() => () => {materials.body.dispose();materials.light.dispose();materials.texture.dispose()}, [materials])
  const profile = W.quality_profiles[preferences.quality], focusedObject = objects.find(o=>o.id===selected), focusedPlot=plots.find(p=>p.id===selected)
  const focused=focusedObject?{id:focusedObject.id,x:focusedObject.x,z:focusedObject.z}:focusedPlot?{id:focusedPlot.id,x:Number(focusedPlot.grid_x),z:Number(focusedPlot.grid_y),pointId:focusedPlot.point_id as string}:undefined
  const center=plots.length?{x:0,z:0}:sceneCenter(objects), lightTarget=useMemo(()=>new THREE.Object3D(),[])
  lightTarget.position.set(center.x,0,center.z)
  const effectTarget=objects.find(o=>o.id===sceneSequence?.targetId),effectPosition:[number,number,number]=effectTarget?[effectTarget.x,groundHeight(effectTarget.x,effectTarget.z,theme,seed),effectTarget.z]:[0,groundHeight(0,0,theme,seed),0]
  return <>
    <color attach="background" args={[daylight?P.sky_day:P.sky_night]}/><fog attach="fog" args={[daylight?P.fog_day:P.fog_night,L.fog_near,L.fog_far]}/>
    <hemisphereLight args={[L.ambient_sky,L.ambient_ground,daylight?L.ambient_intensity_day:L.ambient_intensity_night]}/>
    <primitive object={lightTarget}/>
    <directionalLight position={[L.key_position[0]+center.x,L.key_position[1],L.key_position[2]+center.z]} target={lightTarget} color={daylight?L.key_color_day:L.key_color_night} intensity={daylight?L.key_intensity_day:L.key_intensity_night} castShadow={profile.shadow_casting_lights>0} shadow-mapSize={[profile.shadow_map_size,profile.shadow_map_size]} shadow-bias={L.shadow_bias} shadow-normalBias={L.shadow_normal_bias} shadow-radius={L.shadow_radius} shadow-camera-left={-L.shadow_extent} shadow-camera-right={L.shadow_extent} shadow-camera-top={L.shadow_extent} shadow-camera-bottom={-L.shadow_extent} shadow-camera-near={L.shadow_near} shadow-camera-far={L.shadow_far}/>
    {!daylight&&<pointLight position={[center.x,0.9,center.z+0.6]} color={P.window} intensity={L.warm_light_intensity} distance={L.warm_light_distance} decay={2}/>}
    {props.framing!=='room'&&<Scenery cells={content.cells} theme={theme} seed={seed} reduced={reduced} material={materials.body} compact={compact}/>}
    {[...grouped].map(([key,entries]) => models.has(key) ? <InstanceGroup key={key} model={models.get(key)!} entries={entries} material={materials.body} lightMaterial={materials.light} reduced={reduced} sequence={sequence} sceneSequence={sceneSequence} battleAction={props.battleAction} objects={objects} onSelect={onSelect} onObjectSelect={props.onObjectSelect} canSelect={canSelect}/> : null)}
    <FogAndMarkers plots={plots} selected={selected} theme={theme} seed={seed} sequence={sequence} reduced={reduced} onSelect={onSelect} canSelect={canSelect}/>
    <ObjectMarkers objects={objects} selected={selected} theme={theme} seed={seed} sequence={sceneSequence} reduced={reduced} onSelect={props.onObjectSelect} canSelect={canSelect}/>
    <GameEffects sequence={sceneSequence} position={effectPosition} reduced={reduced} particleBudget={profile.ambient_particles_max}/>
    <BattleEffects action={props.battleAction} objects={objects} theme={theme} seed={seed} reduced={reduced}/>
    <Atmosphere quality={preferences.quality} reduced={reduced} daylight={daylight}/>
    <CameraRig initial={props.initialCamera||focusToLegacyViewport({...(props.initialFocus||center),zoom:W.camera.default_zoom})} preferences={preferences} setPreferences={setPreferences} apiRef={props.apiRef} onViewport={props.onViewport} focusId={props.focusId} selected={focused} sequenceTarget={effectTarget} sequence={sequence} sceneSequence={sceneSequence} reduced={reduced} compact={compact} framing={props.framing} onManual={props.onManual} interactionBlocked={props.interactionBlocked}/>
    <SceneEffects bloom={profile.bloom&&!compact&&!daylight}/>
    <Runtime sceneId={props.sceneId} plots={plots} objects={objects} quality={preferences.quality} onReady={props.onReady}/>
  </>
}

class CanvasBoundary extends Component<{children: ReactNode; onError: () => void}, {failed: boolean}> {
  state = {failed:false}
  static getDerivedStateFromError() {return {failed:true}}
  componentDidCatch(_error: Error, _info: ErrorInfo) {this.props.onError()}
  render() {return this.state.failed ? null : this.props.children}
}

export type WorldMapProps = {
  plots?: RecordView[]; objects?: SceneObject[]; theme?: string; selected?: string; onSelect?: (plot: RecordView) => void; onObjectSelect?: (object: SceneObject) => void;
  onViewport?: (v: LegacyViewport) => void; initialCamera?: LegacyViewport; daylight?: boolean; compact?: boolean;
  focusId?: string; outfit?: boolean; seed?: string | number; accountId?: string; regionId?: string;
  reducedMotion?: boolean; sequence?: ActiveSequence | null; companionPose?: 'idle' | 'wave' | 'celebrate' | 'rest'; displayEpoch?: string;
  onManualCamera?: () => void;
  sceneSequence?: SceneSequence | null; initialFocus?: CameraTarget; interactionBlocked?: boolean;
  battleAction?: SceneBattleAction | null;
  showControls?: boolean;
  framing?: 'room';
  sceneLabel?: string; statusText?: string;
}

export function WorldMap(props: WorldMapProps) {
  const {plots=EMPTY_PLOTS, objects=EMPTY_OBJECTS, selected, daylight=false, compact=false} = props
  const preferenceKey = `kw-world-device:${tokens.version}:${props.accountId || 'preview'}:${props.displayEpoch || 'initial'}:${props.regionId || 'preview'}`
  const [devicePreferences, setPreferencesState] = useState(() => loadPreferences(preferenceKey)), [settings, setSettings] = useState(false), [visible, setVisible] = useState(!document.hidden), [failure, setFailure] = useState(''), [lost, setLost] = useState(false), [ready, setReady] = useState(false), [generation, setGeneration] = useState(0)
  const presentation = usePresentationPreferences(props.accountId,props.displayEpoch), preferences = props.accountId ? {...devicePreferences,reducedMotion:presentation.reducedMotion,sound:presentation.sound,autoCamera:presentation.autoCamera,quality:presentation.quality??devicePreferences.quality} : devicePreferences
  const reduced = !!props.reducedMotion || preferences.reducedMotion || presentation.systemReduced, apiRef = useRef<ControlsApi|null>(null), canvas = useRef<HTMLCanvasElement|null>(null), commandId = useRef(0), sceneId = useRef(crypto.randomUUID()).current
  const pointers = useRef(new Map<number,{x:number;y:number}>()), moved = useRef(0), controlsDisabled = lost || !!failure || !!props.interactionBlocked
  const setPreferences = (next: Preferences) => {setPreferencesState(next);if (props.accountId && (!compact || props.showControls)) {try {localStorage.setItem(preferenceKey,JSON.stringify(next))} catch {/* Display preferences must not block commands. */ }savePresentationPreferences(props.accountId,props.displayEpoch,{reducedMotion:next.reducedMotion,autoCamera:next.autoCamera,sound:next.sound,quality:next.quality!==preferences.quality?next.quality:presentation.quality})}}
  const command = (kind: CameraCommand['kind'], value?: number, target?: CameraTarget) => apiRef.current?.command({id:++commandId.current,kind,value,target})
  const enableSound=useWorldSound(preferences.sound&&visible&&!lost&&!compact,props.sequence,props.companionPose,props.sceneSequence)
  useEffect(()=>{setPreferencesState(loadPreferences(preferenceKey));setReady(false)},[preferenceKey])
  useEffect(() => {const visibility=()=>setVisible(!document.hidden);document.addEventListener('visibilitychange',visibility);return()=>document.removeEventListener('visibilitychange',visibility)},[])
  useEffect(() => {
    const element = canvas.current;if (!element) return
    const contextLost = (event: Event) => {event.preventDefault();setLost(true);setReady(false)}
    const contextRestored = () => {setLost(false);setReady(false);setGeneration(value=>value+1)}
    element.addEventListener('webglcontextlost',contextLost);element.addEventListener('webglcontextrestored',contextRestored)
    return()=>{element.removeEventListener('webglcontextlost',contextLost);element.removeEventListener('webglcontextrestored',contextRestored)}
  },[generation,ready,preferenceKey,preferences.quality])
  const recover=()=>{setFailure('');setLost(false);setReady(false);setPreferences({...preferences,quality:'low'});setGeneration(value=>value+1)}
  const selectedObject=objects.find(o=>o.id===selected),selectedPlot=plots.find(p=>p.id===selected)
  const selectedTarget=selectedObject?{x:selectedObject.x,z:selectedObject.z}:selectedPlot?{x:Number(selectedPlot.grid_x),z:Number(selectedPlot.grid_y)}:undefined
  const legacy=plots.some(p=>p.point_id)
  return <div className={'world-scene world-three '+(daylight?'daylight ':'')+(compact?'compact':'')} data-scene-id={sceneId} data-renderer="threejs" data-ready={ready&&!lost&&!failure} data-quality={preferences.quality} data-reduced-motion={reduced} data-knowledge-count={plots.filter(p=>p.point_id).length} data-object-count={objects.length} data-selected={selected||''} data-sequence-id={props.sceneSequence?.id||props.sequence?.event.id||''}>
    <div className="scene-stars" aria-hidden="true"/>
    <div className="world-canvas" role="group" aria-label={props.sceneLabel||'可旋转、平移和缩放的三维世界；也可使用页面中的对象列表'} onPointerDownCapture={e=>{if(!pointers.current.size)moved.current=0;pointers.current.set(e.pointerId,{x:e.clientX,y:e.clientY});if(pointers.current.size>1)moved.current=G.click_drag_threshold_px+1}} onPointerMoveCapture={e=>{const p=pointers.current.get(e.pointerId);if(p){moved.current+=Math.abs(e.clientX-p.x)+Math.abs(e.clientY-p.y);pointers.current.set(e.pointerId,{x:e.clientX,y:e.clientY})}}} onPointerUpCapture={e=>pointers.current.delete(e.pointerId)} onPointerCancel={()=>pointers.current.clear()}>
      <CanvasBoundary key={`${preferenceKey}:${generation}`} onError={()=>setFailure('这台设备暂时无法打开三维画面。')}>
        <Canvas orthographic dpr={[1,W.quality_profiles[preferences.quality].max_dpr]} camera={{near:0.1,far:100,position:[9,9,9]}} shadows={preferences.quality!=='low'?'soft':false} frameloop={!visible||lost?'never':reduced||compact&&!props.sequence&&!props.sceneSequence&&(!props.battleAction||props.battleAction.frozenProgress!==undefined)?'demand':'always'} gl={{alpha:false,antialias:preferences.quality!=='low',powerPreference:'high-performance'}} onCreated={({gl})=>{canvas.current=gl.domElement;gl.toneMapping=THREE.ACESFilmicToneMapping;gl.toneMappingExposure=L.exposure;gl.info.autoReset=false;gl.domElement.dataset.renderer='threejs';gl.domElement.setAttribute('aria-hidden','true')}} fallback={<p className="world-fallback">浏览器暂不支持三维画面。对象详情和操作仍可从页面列表打开。</p>}>
          <SceneContents {...props} preferences={preferences} setPreferences={setPreferences} apiRef={apiRef} reduced={reduced||!visible} canSelect={()=>!controlsDisabled&&moved.current<G.click_drag_threshold_px} onReady={()=>setReady(true)} onManual={()=>props.onManualCamera?.()} sceneId={sceneId}/>
        </Canvas>
      </CanvasBoundary>
    </div>
    {(!ready&&!lost&&!failure)&&<div className="world-loading" role="status">正在点亮这座小镇…<span>建筑、植被与灯光就绪后即可漫游</span></div>}
    {(lost||failure)&&<div className="world-fallback" role="status"><strong>{lost?'三维画面暂时中断。':failure}</strong><p>已保存的记录和物件状态仍然保留，可继续使用页面中的列表与操作。</p><button className="button secondary" onClick={recover}>以低画质恢复画面</button></div>}
    {(!compact||props.showControls)&&<>
      <div className="map-coordinate"><span className="live-dot"/>{props.statusText||(daylight?'日光里的小镇':'灯还亮着，慢慢来。')}<span>· {legacy?'每一份成长都有来处':'属于你的世界'}</span></div>
      <div className="map-mode" aria-label="地图操作模式"><button className={preferences.mode==='rotate'?'active':''} aria-pressed={preferences.mode==='rotate'} onClick={()=>setPreferences({...preferences,mode:'rotate'})}><RotateCw size={15}/>旋转</button><button className={preferences.mode==='pan'?'active':''} aria-pressed={preferences.mode==='pan'} onClick={()=>setPreferences({...preferences,mode:'pan'})}><Hand size={15}/>平移</button></div>
      <div className="map-controls" aria-label="地图相机控制"><button disabled={controlsDisabled} aria-label="放大地图" onClick={()=>command('zoom',1.2)}><Plus size={18}/></button><button disabled={controlsDisabled} aria-label="缩小地图" onClick={()=>command('zoom',1/1.2)}><Minus size={18}/></button><button disabled={controlsDisabled} aria-label="向左旋转地图" onClick={()=>command('rotate',-G.manual_rotate_step_deg)}><RotateCcw size={18}/></button><button disabled={controlsDisabled} aria-label="向右旋转地图" onClick={()=>command('rotate',G.manual_rotate_step_deg)}><RotateCw size={18}/></button><button disabled={controlsDisabled} aria-label="抬高观察视角" onClick={()=>command('elevation',G.manual_elevation_step_deg)}><ArrowUp size={18}/></button><button disabled={controlsDisabled} aria-label="降低观察视角" onClick={()=>command('elevation',-G.manual_elevation_step_deg)}><ArrowDown size={18}/></button><button disabled={controlsDisabled} aria-label="定位选中地块或营地" onClick={()=>command('focus',undefined,selectedTarget)}><LocateFixed size={18}/></button><button disabled={controlsDisabled} aria-label="重置地图视角" onClick={()=>command('reset')}><View size={18}/></button></div>
      {(selectedPlot||selectedObject)&&<div className="map-selected" aria-live="polite"><strong>{selectedObject?.title||selectedPlot?.title||'林间营地'}</strong><span>{selectedObject?.subtitle||(selectedPlot?.point_id?stageNames[selectedPlot.current_stage]:'属于你的起点')}{selectedPlot?.due?' · 待复习':''}</span></div>}
      <div className="map-hint">{preferences.mode==='rotate'?'拖动环绕':'拖动平移'} · 双指 / 滚轮缩放</div>
      <button className="scene-settings-button" aria-label="画面与演出设置" aria-expanded={settings} onClick={()=>setSettings(!settings)}><Settings2 size={17}/></button>
      {settings&&<div className="scene-settings"><strong>画面与演出</strong><label>画质<select value={preferences.quality} onChange={e=>setPreferences({...preferences,quality:e.target.value as Quality})}><option value="desktop">精细 · 桌面</option><option value="mobile">轻盈 · 手机</option><option value="low">低画质 · 减少负担</option></select></label><label><input type="checkbox" checked={preferences.autoCamera} onChange={e=>setPreferences({...preferences,autoCamera:e.target.checked})}/>自动看向新的成长</label><label><input type="checkbox" checked={preferences.reducedMotion} onChange={e=>setPreferences({...preferences,reducedMotion:e.target.checked})}/>低动效</label><label><input type="checkbox" checked={preferences.sound} onChange={e=>{if(e.target.checked)enableSound();setPreferences({...preferences,sound:e.target.checked})}}/>{preferences.sound?<Volume2 size={15}/>:<VolumeX size={15}/>}成长提示音</label><p>{reduced?'低动效已生效：环境保持静止，以文字说明变化。':'拖动镜头会立即接管自动运镜。'}</p><button className="text-link" onClick={()=>setSettings(false)}>完成</button></div>}
    </>}
  </div>
}
