import {test,expect,password} from './fixtures'
import type {Schema} from '../src/shared/api/client'

test('Ctrl+Enter inserts at the caret and Enter sends the multiline message',async({page})=>{
  const thread:Schema<'AgentThread'>={id:'synthetic-keyboard-thread',title:'SYNTHETIC 键盘验收',created_at:'2026-10-10T00:00:00Z',messages:[],runs:[],actions:[]}
  const sent:{content:string;client_message_id:string}[]=[]
  // All chat requests are intercepted: this UI check never invokes a provider.
  await page.route('**/api/v1/system/threads**',async route=>{
    const request=route.request(),pathname=new URL(request.url()).pathname
    if(request.method()==='POST'&&pathname.endsWith('/messages')){
      sent.push(request.postDataJSON())
      const receipt:Schema<'MessageReceipt'>={thread_id:thread.id,message_id:'synthetic-message',run_id:'synthetic-run',job_id:'synthetic-job',state:'queued'}
      await route.fulfill({json:{data:receipt}});return
    }
    if(request.method()==='GET'){
      await route.fulfill({json:{data:pathname.endsWith('/threads')?{items:[thread],next_cursor:null}:thread}});return
    }
    throw new Error(`Unexpected chat request: ${request.method()} ${pathname}`)
  })
  await page.goto('/system')
  await page.getByLabel('怎么称呼你').fill('SYNTHETIC 键盘验收')
  await page.getByLabel('账户密码').fill(password)
  await page.getByRole('button',{name:'点亮我的营地'}).click()
  await expect(page).toHaveURL(/\/world$/)
  await page.goto('/system')
  await expect(page.getByLabel('选择系统会话')).toHaveValue(thread.id)
  await expect(page.locator('.game-feedback')).toHaveCount(0,{timeout:20000})
  const composer=page.getByRole('textbox',{name:'发送给系统'})
  await composer.fill('第一行第二行')
  await composer.evaluate((input:HTMLTextAreaElement)=>input.setSelectionRange(3,3))
  await composer.press('Control+Enter')
  await expect(composer).toHaveValue('第一行\n第二行')
  expect(await composer.evaluate((input:HTMLTextAreaElement)=>input.selectionStart)).toBe(4)
  expect(sent).toHaveLength(0)
  await composer.press('Enter')
  await expect.poll(()=>sent.length).toBe(1)
  expect(sent[0].content).toBe('第一行\n第二行')
  await expect(composer).toHaveValue('')
})
