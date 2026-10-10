import {test,expect,api,ready,password,save,screenshot} from './fixtures'

test('三维恢复：十次路由往返、全局偏好与 WebGL 中断后继续签到',async({page})=>{
  const errors:string[]=[]
  page.on('pageerror',error=>errors.push(String(error)))
  await page.goto('/world')
  await page.getByLabel('怎么称呼你').fill('SYNTHETIC 三维恢复验收')
  await page.getByLabel('账户密码').fill(password)
  await page.getByRole('button',{name:'点亮我的营地'}).click()
  await ready(page)
  const scene=page.locator('.home-stage .world-three')
  expect(await scene.getAttribute('data-quality')).toBe((page.viewportSize()?.width||0)<=760?'mobile':'desktop')
  const cdp=await page.context().newCDPSession(page)
  const listenerEvidence:unknown[]=[]
  async function listeners(){
    const counts:Record<string,number>={}
    for(const target of ['window','document']){
      const {result}=await cdp.send('Runtime.evaluate',{expression:target})
      const snapshot=await cdp.send('DOMDebugger.getEventListeners',{objectId:result.objectId!})
      counts[target]=snapshot.listeners.length
      listenerEvidence.push({target,listeners:snapshot.listeners.map(({type,lineNumber,scriptId,handler})=>({type,lineNumber,scriptId,description:handler?.description?.slice(0,200)}))})
      await cdp.send('Runtime.releaseObject',{objectId:result.objectId!})
    }
    return counts
  }
  async function sample(){
    await expect.poll(()=>page.evaluate(()=>Object.values(window.__KW_WORLD_DIAGNOSTICS__?.active||{})[0]?.geometries||0)).toBeGreaterThan(0)
    return page.evaluate(()=>Object.values(window.__KW_WORLD_DIAGNOSTICS__?.active||{}).map(({geometries,textures,renderer,quality})=>({geometries,textures,renderer,quality})))
  }
  const initial=await sample(),initialListeners=await listeners(),cycles=[]
  let warmedListeners:Record<string,number>|null=null
  for(let i=0;i<10;i++){
    await page.getByRole('button',{name:'成长回看',exact:true}).click()
    await expect(page.locator('canvas[data-renderer=threejs]')).toHaveCount(0)
    await expect.poll(()=>page.evaluate(()=>Object.keys(window.__KW_WORLD_DIAGNOSTICS__?.active||{}).length)).toBe(0)
    await page.getByRole('button',{name:'我的家园',exact:true}).click();await ready(page)
    const samples=await sample(),currentListeners=await listeners()
    expect(samples).toHaveLength(1)
    expect(samples[0].geometries).toBeLessThanOrEqual(initial[0].geometries+2)
    expect(samples[0].textures).toBeLessThanOrEqual(initial[0].textures+1)
    // The first visit loads the history chunk. Compare subsequent roundtrips
    // to that warm baseline, while preserving both cold and warm counts.
    warmedListeners??=currentListeners
    cycles.push({cycle:i+1,samples,listeners:currentListeners})
    await save(page,'scene-route-cycles',{synthetic:true,initial,initialListeners,cycles,listenerEvidence})
  }
  // Save through the real settings command. Scene-local defaults are not
  // evidence that main.tsx synchronizes a user's explicit server preference.
  const wallet=await api(page,'/wallet')
  async function navigate(name:string){
    const nav=page.getByRole('navigation',{name:'主要导航'})
    if((page.viewportSize()?.width||0)<=760)await page.getByRole('button',{name:'打开导航'}).click()
    await nav.getByRole('link',{name,exact:true}).click()
  }
  await navigate('设置')
  await page.getByLabel('场景画质').selectOption('low')
  await expect(page.getByLabel('场景画质')).toHaveValue('low')
  // These controlled inputs change only after a server receipt/refetch. A
  // synchronous check() assertion would mistake that brief wait for a failure.
  await expect(page.getByRole('checkbox',{name:/减少动态效果/})).not.toBeChecked()
  await page.getByRole('checkbox',{name:/减少动态效果/}).click()
  await expect(page.getByRole('checkbox',{name:/减少动态效果/})).toBeChecked()
  await expect(page.getByRole('checkbox',{name:/自动运镜/})).toBeChecked()
  await page.getByRole('checkbox',{name:/自动运镜/}).click()
  await expect(page.getByRole('checkbox',{name:/自动运镜/})).not.toBeChecked()
  await expect(page.getByRole('checkbox',{name:/演出声音/})).not.toBeChecked()
  await navigate('世界')
  await expect(scene).toHaveAttribute('data-quality','low',{timeout:20000})
  await expect(scene).toHaveAttribute('data-reduced-motion','true');await ready(page)
  await page.getByRole('button',{name:'画面与演出设置'}).click()
  await expect(page.getByLabel('成长提示音')).not.toBeChecked()
  await expect(page.getByLabel('自动看向新的成长')).not.toBeChecked()
  await page.getByRole('button',{name:'完成',exact:true}).click()
  expect(await api(page,'/wallet')).toEqual(wallet)

  const canvas=page.locator('canvas[data-renderer=threejs]').first()
  // WEBGL_lose_context exercises actual WebGL loss, not a synthetic DOM event.
  expect(await canvas.evaluate(element=>{
    const gl=(element as HTMLCanvasElement).getContext('webgl2')
    const extension=gl?.getExtension('WEBGL_lose_context')
    if(!extension)return false
    extension.loseContext();return true
  })).toBe(true)
  await expect(page.getByText('三维画面暂时中断。',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'签到，点亮今天'}).click()
  await expect(page.getByRole('button',{name:'今日已签到'})).toBeDisabled()
  const checkin=await api(page,'/system/checkin'),afterCheckin=await api(page,'/wallet')
  await page.getByRole('button',{name:'以低画质恢复画面'}).click();await ready(page)
  await expect(page.getByText('三维画面暂时中断。',{exact:true})).toHaveCount(0)
  expect((await api(page,'/system/checkin')).ledger_entry_ids).toEqual(checkin.ledger_entry_ids)
  expect(await api(page,'/wallet')).toEqual(afterCheckin)
  await screenshot(page,'recovered-home')
  await save(page,'scene-resilience',{synthetic:true,real_ai:false,mobile_hardware:false,initial,initialListeners,cycles,checkin,afterCheckin,errors})
  expect(errors).toEqual([])
  // Check accumulation after the independent settings/context-loss checks so
  // one failed boundary does not conceal evidence about the other behaviors.
  expect(cycles.at(-1)!.listeners.window).toBeLessThanOrEqual(warmedListeners!.window)
  expect(cycles.at(-1)!.listeners.document).toBeLessThanOrEqual(warmedListeners!.document)
  await cdp.detach()
})
