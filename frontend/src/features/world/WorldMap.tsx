import {Component, Suspense, lazy} from 'react'
import type {ReactNode} from 'react'
import type {WorldMapProps} from './WorldScene'
import './world.css'

const Scene=lazy(()=>import('./WorldScene').then(module=>({default:module.WorldMap})))
class SceneAssetsBoundary extends Component<{children:ReactNode},{failed:boolean}> {
  state={failed:false}
  static getDerivedStateFromError(){return {failed:true}}
  render(){return this.state.failed?<div className="world-scene world-three"><div className="world-canvas"/><div className="world-fallback" role="status"><strong>三维资源还没有载入。</strong><p>对象列表、正式记录与页面操作仍然可用。恢复连接后可以重新打开画面。</p><button className="button secondary" onClick={()=>location.reload()}>重新载入画面</button></div></div>:this.props.children}
}
export function WorldMap(props:WorldMapProps){return <SceneAssetsBoundary><Suspense fallback={<div className="world-scene world-three"><div className="world-canvas"/><div className="world-loading" role="status">正在打开小镇的画面…</div></div>}><Scene {...props}/></Suspense></SceneAssetsBoundary>}
