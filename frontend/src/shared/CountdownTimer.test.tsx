import {afterEach,expect,it,vi} from 'vitest'
import {act,cleanup,render,screen} from '@testing-library/react'
import {CountdownTimer,finishTimer,idleTimer,loadTimer,pauseTimer,startTimer,timerRemaining} from './CountdownTimer'

vi.mock('./chime',()=>({playChime:vi.fn(),notify:vi.fn(),askNotificationPermission:vi.fn()}))
afterEach(()=>{cleanup();localStorage.clear();vi.useRealTimers()})

it('a running timer is anchored to wall-clock time, so pause/resume and refresh keep the remainder',()=>{
  let state=startTimer(idleTimer(10),1_000)
  expect(timerRemaining(state,61_000)).toBe(540_000)
  state=pauseTimer(state,61_000)
  expect(timerRemaining(state,999_999)).toBe(540_000)
  state=startTimer(state,100_000)
  localStorage.setItem('t',JSON.stringify(state))
  expect(timerRemaining(loadTimer('t',idleTimer(25)),160_000)).toBe(480_000)
  expect(finishTimer(state,700_000)).toMatchObject({remaining:0,endsAt:null,finishedAt:640_000})
})
it('restores a running timer after remount and finishes once',()=>{
  vi.useFakeTimers({now:0});const done=vi.fn()
  localStorage.setItem('kw-test-timer',JSON.stringify(startTimer(idleTimer(1),0)))
  vi.setSystemTime(30_000)
  render(<CountdownTimer storageKey="kw-test-timer" onFinish={done}/>)
  expect(screen.getByRole('timer').textContent).toContain('00:30')
  act(()=>{vi.advanceTimersByTime(31_000)})
  expect(done).toHaveBeenCalledTimes(1)
  expect(JSON.parse(localStorage.getItem('kw-test-timer')!).finishedAt).toBe(60_000)
})
