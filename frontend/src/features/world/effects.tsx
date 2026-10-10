import {useEffect, useMemo} from 'react'
import {useFrame, useThree} from '@react-three/fiber'
import {Vector2} from 'three'
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js'
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js'
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js'
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js'
import tokens from '../../../../docs/contracts/design-tokens.json'

export function SceneEffects({bloom}:{bloom:boolean}) {
  const {gl,scene,camera,size,invalidate}=useThree()
  const composer=useMemo(()=>{
    if(!bloom)return null
    const c=new EffectComposer(gl),l=tokens.world.lighting
    c.addPass(new RenderPass(scene,camera))
    c.addPass(new UnrealBloomPass(new Vector2(1,1),l.bloom_strength,l.bloom_radius,l.bloom_threshold))
    c.addPass(new OutputPass())
    return c
  },[bloom,gl,scene,camera])
  useEffect(()=>{composer?.setPixelRatio(gl.getPixelRatio());composer?.setSize(size.width,size.height);invalidate()},[composer,gl,size.width,size.height,invalidate])
  useEffect(()=>()=>{composer?.passes.forEach(p=>p.dispose());composer?.dispose()},[composer])
  useFrame(()=>{gl.info.reset();if(composer)composer.render();else gl.render(scene,camera)},1)
  return null
}
