import {test,expect,password,screenshot,save} from './fixtures'
import type {Schema} from '../src/shared/api/client'

test('long system conversations scroll inside the panel while controls stay in place',async({page})=>{
  // Only the read-only thread responses are synthetic; no provider or economic
  // command is needed to exercise the real AgentPanel and production CSS.
  const thread:Schema<'AgentThread'>={id:'synthetic-long-thread',title:'SYNTHETIC 长对话滚动验收',created_at:'2026-10-10T00:00:00Z',runs:[],actions:[],messages:Array.from({length:60},(_,i)=>({id:`synthetic-message-${i}`,role:i%2?'assistant':'user',content_md:`第 ${i+1} 条隔离测试消息。\n\n用于验证对话区滚动、输入框固定与会话切换，不代表真实 AI 回复或用户记录。`,run_id:null,created_at:'2026-10-10T00:00:00Z'}))}
  const empty:Schema<'AgentThread'>={...thread,id:'synthetic-empty-thread',title:'SYNTHETIC 空对话',messages:[]}
  await page.route('**/api/v1/system/threads**',async route=>{
    if(route.request().method()!=='GET'){await route.continue();return}
    const pathname=new URL(route.request().url()).pathname
    const data=pathname.endsWith('/threads')?{items:[thread,empty],next_cursor:null}:pathname.endsWith(empty.id)?empty:thread
    await route.fulfill({json:{data}})
  })
  await page.goto('/system')
  await page.getByLabel('怎么称呼你').fill('SYNTHETIC 滚动验收')
  await page.getByLabel('账户密码').fill(password)
  await page.getByRole('button',{name:'点亮我的营地'}).click()
  await expect(page).toHaveURL(/\/world$/)
  await page.goto('/system')
  const panel=page.locator('.agent-panel.full'),messages=panel.locator('.agent-messages'),composer=panel.locator('.agent-composer'),select=page.getByLabel('选择系统会话')
  await expect(messages.locator('.message')).toHaveCount(60)
  await expect(page.locator('.game-feedback')).toHaveCount(0,{timeout:20000})
  const measure=()=>messages.evaluate(el=>({overflow:getComputedStyle(el).overflowY,height:el.clientHeight,content:el.scrollHeight,top:el.scrollTop}))
  const before=await measure()
  expect(before.overflow).toBe('auto')
  expect(before.content).toBeGreaterThan(before.height)
  expect(before.height).toBeGreaterThan(80)
  await panel.scrollIntoViewIfNeeded()
  await messages.evaluate(el=>{el.scrollTop=0})
  const inputBefore=await composer.boundingBox(),selectBefore=await select.boundingBox(),pageBefore=await page.evaluate(()=>window.scrollY)
  await messages.hover();await page.mouse.wheel(0,500)
  await expect.poll(async()=>(await measure()).top).toBeGreaterThan(100)
  expect((await composer.boundingBox())!.y).toBeCloseTo(inputBefore!.y,0)
  expect((await select.boundingBox())!.y).toBeCloseTo(selectBefore!.y,0)
  expect(await page.evaluate(()=>window.scrollY)).toBeCloseTo(pageBefore,0)
  await expect(page.getByLabel('发送给系统')).toBeInViewport()
  await expect(select).toBeInViewport()
  await screenshot(page,'system-conversation-scroll')
  await select.selectOption(empty.id)
  await expect(messages.locator('.message')).toHaveCount(0)
  await expect(messages.getByRole('heading',{name:'今天，想向前走哪一步？'})).toBeInViewport()
  const headingBottom=await panel.locator('.agent-heading').evaluate(el=>el.getBoundingClientRect().bottom)
  expect((await select.boundingBox())!.y).toBeGreaterThanOrEqual(headingBottom-1)
  expect((await measure()).top).toBe(0)
  await screenshot(page,'system-conversation-empty')
  await save(page,'scroll-evidence',{synthetic:true,before,after:await measure(),inputBefore,selectBefore,pageBefore})
})
