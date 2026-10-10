import {test,expect,api,noOverflow,ready,password} from './fixtures'

test('隔离生产构建：四入口、签到、对赌、培养、远征与回看',async({page})=>{
  await page.goto('/world')
  await page.getByLabel('怎么称呼你').fill('浏览器隔离验收账户')
  await page.getByLabel('账户密码').fill(password)
  await page.getByRole('button',{name:'点亮我的营地'}).click()
  await expect(page.locator('.test-banner')).toContainText('测试适配器')
  await ready(page);await noOverflow(page)
  const me=await api(page,'/me'),home=await api(page,'/world/home'),roster=await api(page,'/roster'),world=await api(page,'/world/map')
  expect(me.wallet.available_points).toBe(0);expect(home.items.length).toBeGreaterThanOrEqual(1);expect(roster.monsters.length).toBeGreaterThanOrEqual(1)

  await expect(page.getByRole('button',{name:'签到，点亮今天'})).toBeVisible()
  await page.getByRole('button',{name:'签到，点亮今天'}).click()
  await expect(page.getByRole('button',{name:'今日已签到'})).toBeDisabled()
  expect((await api(page,'/system/checkin')).streak).toBe(1)

  await api(page,'/system/adjustments','POST',{points:500,reason:'SYNTHETIC browser fixture funding',command_key:crypto.randomUUID()})
  const proposal=await api(page,'/system/wagers','POST',{title:'浏览器隔离对赌',target_points:5,stake_points:2,bonus_points:3})
  const wager=await api(page,`/system/wagers/${proposal.id}/accept`,'POST',{expected_version:proposal.version,terms_hash:proposal.terms_hash})
  await page.goto('/system?tab=wagers');await expect(page.getByRole('region',{name:'对赌 Skill',exact:true}).getByRole('heading',{name:'浏览器隔离对赌',level:2,exact:true})).toBeVisible()
  expect((await api(page,`/system/wagers/${wager.id}`)).state).toBe('active')

  const quote=await api(page,'/roster/quotes','POST',{operation:'hero_train',attribute:'strength'})
  await api(page,'/roster/orders','POST',{quote_token:quote.quote_token})
  await page.goto('/roster');await expect(page.getByRole('heading',{name:'一点积累，成为新的力量。'})).toBeVisible();await noOverflow(page)

  const battle=await api(page,'/world/battles','POST',{outpost_id:'fern_gate',team_version:world.team.version,command_key:crypto.randomUUID()})
  await expect.poll(async()=>(await api(page,`/world/battles/${battle.id}`)).state,{timeout:45000}).toBe('resolved')
  const resolved=await api(page,`/world/battles/${battle.id}`)
  expect(resolved.result.events.length).toBeGreaterThan(0);expect(['won','lost']).toContain(resolved.result.outcome)
  await page.goto('/world?tab=history');await expect(page.getByRole('heading',{name:'那些真实的变化，都还在。'})).toBeVisible();await noOverflow(page)
  await page.goto('/rewards');await expect(page.getByRole('heading',{name:'把努力，换成一点喜欢。'})).toBeVisible();await noOverflow(page)
})
