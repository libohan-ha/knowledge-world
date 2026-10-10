import {test,expect,api,ready,password,save,screenshot,noOverflow} from './fixtures'

test('账户与入口：时区、新手资产、退出重登、六个导航和旧链接去向',async({page})=>{
  const errors:string[]=[]
  page.on('pageerror',error=>errors.push(String(error)))
  await page.goto('/world')
  await page.getByLabel('怎么称呼你').fill('SYNTHETIC 登录与入口验收')
  await page.getByLabel('账户密码').fill(password)
  await page.getByLabel('所在时区').selectOption('Asia/Tokyo')
  await page.getByRole('button',{name:'点亮我的营地'}).click()
  await ready(page)
  const before=await api(page,'/me'),home=await api(page,'/world/home')
  expect(before.profile.timezone).toBe('Asia/Tokyo')
  expect(before.wallet.available_points).toBe(0)
  expect(home.roster.monsters).toHaveLength(1)
  expect(home.items).toHaveLength(1)
  const routes=[['世界','/world'],['角色与魔兽','/roster'],['奖励','/rewards'],['系统','/system'],['积分账本','/ledger'],['设置','/settings']]
  for(const [name,route] of routes){
    if((page.viewportSize()?.width||0)<=760)await page.getByRole('button',{name:'打开导航'}).click()
    await page.getByRole('navigation',{name:'主要导航'}).getByRole('link',{name,exact:true}).click()
    await expect(page).toHaveURL(new RegExp(route+'$'))
    if((page.viewportSize()?.width||0)<=760)await expect(page.locator('.navigation')).not.toHaveClass(/\bopen\b/)
    await noOverflow(page)
  }
  await page.getByRole('button',{name:'退出登录',exact:true}).click()
  await expect(page.getByRole('heading',{name:'营地的灯还亮着。'})).toBeVisible()
  await page.getByLabel('账户密码').fill('incorrect-synthetic-password')
  await page.getByRole('button',{name:'回到我的世界'}).click()
  await expect(page.getByText('密码不正确',{exact:true})).toBeVisible()
  await page.getByLabel('账户密码').fill(password)
  await page.getByRole('button',{name:'回到我的世界'}).click()
  await ready(page)
  await page.reload();await ready(page)
  const after=await api(page,'/me'),restored=await api(page,'/world/home')
  expect(after.profile.id).toBe(before.profile.id)
  expect(after.profile.timezone).toBe('Asia/Tokyo')
  expect(after.wallet).toEqual(before.wallet)
  expect(restored.items).toEqual(home.items)
  expect(restored.roster).toEqual(home.roster)
  const legacyRoutes=[['/habits','/system?tab=checkin'],['/commitments','/system?tab=wagers'],['/workshop','/rewards'],['/agent','/system']]
  for(const [oldPath,newPath] of legacyRoutes){
    await page.goto(oldPath)
    await expect.poll(()=>new URL(page.url()).pathname+new URL(page.url()).search).toBe(newPath)
  }
  for(const path of ['/monitor','/library','/review','/planning']){
    await page.goto(path)
    await expect(page.getByRole('heading',{name:'旅程有了新的入口。'})).toBeVisible()
    await expect(page.getByRole('link',{name:'查看原始流水',exact:true})).toBeVisible()
  }
  await screenshot(page,'retired-route')
  await save(page,'identity-navigation',{synthetic:true,real_ai:false,mobile_hardware:false,routes,legacyRoutes,before,after,home,restored,errors})
  expect(errors).toEqual([])
})
