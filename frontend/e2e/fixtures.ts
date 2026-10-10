import {test as base, expect, type Page} from '@playwright/test'
import {spawn} from 'node:child_process'
import {mkdir, writeFile} from 'node:fs/promises'
import {createWriteStream} from 'node:fs'
import path from 'node:path'

export const root = path.resolve(import.meta.dirname, '../..')
export const password = 'synthetic-browser-acceptance-only'
export const test = base.extend<{serverURL: string; runtimeDirectory: string}>({
  runtimeDirectory: [async ({},use,info)=>{
    const directory=path.join(root,'artifacts/refactor/runtime',`browser-${info.project.name}-${Date.now()}`)
    await mkdir(directory,{recursive:true});await use(directory)
  },{}],
  serverURL: [async ({runtimeDirectory},use,info)=>{
    const port=18220+info.workerIndex, url=`http://127.0.0.1:${port}`
    const processes:ReturnType<typeof spawn>[]=[], logs:ReturnType<typeof createWriteStream>[]=[]
    function start(role:string){
      const log=createWriteStream(path.join(runtimeDirectory,role+'.log'));logs.push(log)
      const env={...process.env,KW_DATA_DIR:runtimeDirectory,PYTHONUTF8:'1',PYTHONIOENCODING:'utf-8'}
      // Inherited real provider environment is irrelevant to these synthetic tests.
      for(const key of Object.keys(env)) if(key.startsWith('AI_')) delete env[key as keyof typeof env]
      const child=spawn(path.join(root,'backend/.venv/Scripts/python.exe'),[
        path.join(root,'backend/tests/core/browser_runtime.py'),role,'--data-dir',runtimeDirectory,'--port',String(port),
      ],{cwd:root,env,windowsHide:true,stdio:['ignore','pipe','pipe']})
      child.stdout?.pipe(log,{end:false});child.stderr?.pipe(log,{end:false});processes.push(child)
    }
    try{
      start('api')
      await expect.poll(async()=>{try{return (await fetch(url+'/api/v1/health')).ok}catch{return false}},{timeout:30000}).toBe(true)
      start('worker')
      await writeFile(path.join(runtimeDirectory,'runtime.json'),JSON.stringify({synthetic:true,real_ai:false,host:'FastAPI serving frontend/dist',url,pids:processes.map(p=>p.pid)},null,2))
      await use(url)
    }finally{
      await Promise.all(processes.map(child=>new Promise<void>(resolve=>{
        if(child.exitCode!==null){resolve();return}child.once('exit',()=>resolve());child.kill()
      })))
      logs.forEach(log=>log.end())
    }
  },{timeout:45000}],
  baseURL:async({serverURL},use)=>use(serverURL),
})
export {expect}

export async function api(page:Page,route:string,method='GET',data?:unknown){
  const origin=new URL(page.url()).origin,cookies=await page.context().cookies()
  const response=await page.request.fetch(origin+'/api/v1'+route,{method,data,headers:{Origin:origin,'X-CSRF-Token':cookies.find(c=>c.name==='kw_csrf')?.value||'','Idempotency-Key':crypto.randomUUID()}})
  expect(response.ok(),`${method} ${route}: ${await response.text()}`).toBeTruthy()
  return (await response.json()).data
}
export async function ready(page:Page){await expect(page.locator('.world-three[data-ready=true]').first()).toBeVisible({timeout:45000})}
export async function quoteConfirm(page:Page){
  const dialog=page.getByRole('dialog',{name:'确认这次选择'})
  await expect(dialog).toBeVisible();await dialog.getByRole('button',{name:/确认(执行|兑换) ·/}).click();await expect(dialog).not.toBeVisible()
}
export async function noOverflow(page:Page){expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual((page.viewportSize()?.width||0)+1)}

export async function screenshot(page:Page,name:string){
  await page.evaluate(()=>document.fonts.ready)
  await page.screenshot({path:base.info().outputPath(name+'.png')})
}
export async function save(_page:Page,name:string,data:unknown){
  const file=base.info().outputPath(name+'.json')
  await writeFile(file,JSON.stringify(data,null,2),'utf8')
  await base.info().attach(name,{path:file,contentType:'application/json'})
}
export async function settleNotice(page:Page){
  const close=page.locator('.game-feedback .game-skip');if(await close.count())await close.first().click()
}
export async function recordTimeline(page:Page){
  await page.addInitScript(()=>{
    const target=window as typeof window & {__ART_TIMELINE__:unknown[]}
    target.__ART_TIMELINE__=[]
    let previous=''
    window.addEventListener('DOMContentLoaded',()=>new MutationObserver(()=>{
      const node=document.querySelector('.game-feedback');if(!node)return
      const item={at:performance.now(),event:node.getAttribute('data-event-id'),cue:node.getAttribute('data-cue')}
      const key=item.event+':'+item.cue
      if(key!==previous){previous=key;target.__ART_TIMELINE__.push(item)}
    }).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['data-cue','data-event-id','data-sequence-id']}))
  })
}
