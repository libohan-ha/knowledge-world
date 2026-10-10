import {useEffect, useMemo, useState} from 'react'
import tokens from '../../../../docs/contracts/design-tokens.json'

export type PresentationQuality = keyof typeof tokens.world.quality_profiles
export type PresentationPreferences = {reducedMotion: boolean; autoCamera: boolean; sound: boolean; quality?: PresentationQuality}
const defaults: PresentationPreferences = {reducedMotion: false, autoCamera: true, sound: tokens.world.audio.default_enabled}
const changedEvent = 'kw-presentation-preferences'
const keyFor = (accountId?: string, epoch?: string) => `kw-world-device:${tokens.version}:${accountId || 'preview'}:${epoch || 'initial'}:presentation`
const read = (key: string) => {try {return localStorage.getItem(key) || ''} catch {return ''}}

function parsePreferences(value: string): PresentationPreferences {
  try {
    const raw = JSON.parse(value || '{}')
    if (!raw || typeof raw !== 'object') return defaults
    const quality = Object.hasOwn(tokens.world.quality_profiles, raw.quality) ? raw.quality as PresentationQuality : undefined
    return {reducedMotion: raw.reducedMotion === true, autoCamera: raw.autoCamera !== false, sound: raw.sound === true, quality}
  } catch {return defaults}
}

export function savePresentationPreferences(accountId: string | undefined, epoch: string | undefined, next: PresentationPreferences) {
  if (!accountId) return
  const key = keyFor(accountId, epoch)
  // Callers that only synchronize motion/audio must not erase the user's
  // device quality. Until explicitly selected, the scene keeps its responsive
  // default (mobile on narrow screens).
  const value = JSON.stringify({...next, quality: next.quality ?? parsePreferences(read(key)).quality})
  if (read(key) === value) return
  try {localStorage.setItem(key, value)} catch { /* Device preferences never block a command. */ }
  window.dispatchEvent(new CustomEvent(changedEvent, {detail: {key, value}}))
}

export function usePresentationPreferences(accountId?: string, epoch?: string) {
  const key = keyFor(accountId, epoch), [saved, setSaved] = useState(() => ({key, value: read(key)}))
  const [systemReduced, setSystemReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  useEffect(() => {
    setSaved({key, value: read(key)})
    const storage = (event: StorageEvent) => {if (event.key === key || event.key === null) setSaved({key, value: read(key)})}
    const local = (event: Event) => {const detail = (event as CustomEvent).detail;if (detail?.key === key) setSaved({key, value: detail.value})}
    window.addEventListener('storage', storage);window.addEventListener(changedEvent, local)
    return () => {window.removeEventListener('storage', storage);window.removeEventListener(changedEvent, local)}
  }, [key])
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)'), change = () => setSystemReduced(media.matches)
    change();media.addEventListener('change', change);return () => media.removeEventListener('change', change)
  }, [])
  const preferences = useMemo(() => parsePreferences(saved.key === key ? saved.value : read(key)), [key, saved])
  return {...preferences, systemReduced}
}
