import {afterEach,expect,it} from 'vitest'
import {cleanup,fireEvent,render,screen} from '@testing-library/react'
import {DEFAULT_MIX,loadMix} from './ambient'
import {AmbientPanel} from '../features/Study'

afterEach(()=>{cleanup();localStorage.clear()})
it('loadMix tolerates missing or corrupt saved mixes',()=>{
  expect(loadMix('none')).toEqual(DEFAULT_MIX)
  localStorage.setItem('bad','{oops');expect(loadMix('bad')).toEqual(DEFAULT_MIX)
  localStorage.setItem('old',JSON.stringify({master:0.3,layers:{rain:0.2,unknown:1}}))
  expect(loadMix('old')).toEqual({master:0.3,layers:{rain:0.2,cafe:0,fireplace:0,brown:0,white:0}})
})
it('the mixer remembers choices on this device',()=>{
  render(<AmbientPanel storageKey="kw-test-mix"/>)
  fireEvent.change(screen.getByRole('slider',{name:'棕噪音 音量'}),{target:{value:'0.4'}})
  fireEvent.click(screen.getByRole('button',{name:'午后咖啡'}))
  expect(JSON.parse(localStorage.getItem('kw-test-mix')!).layers).toMatchObject({cafe:0.6,brown:0.2,rain:0})
  fireEvent.click(screen.getByRole('button',{name:/播放声音/}))
  expect(screen.getByText(/不支持 Web Audio/)).toBeInTheDocument()
})
