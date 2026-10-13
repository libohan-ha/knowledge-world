/** A soft two-partial bell synthesised with the Web Audio API: no audio asset needed. */
let shared:AudioContext|null=null
export function audioContext(){
  const Context=window.AudioContext||(window as unknown as {webkitAudioContext?:typeof AudioContext}).webkitAudioContext
  if(!Context)return null
  if(!shared||shared.state==='closed')shared=new Context()
  if(shared.state==='suspended')void shared.resume()
  return shared
}
export function playChime(volume=0.35){
  const ctx=audioContext()
  if(!ctx)return
  const start=ctx.currentTime+0.02,out=ctx.createGain()
  out.gain.value=Math.max(0,Math.min(1,volume));out.connect(ctx.destination)
  // Three gentle strikes of a bell-like tone (fundamental + soft overtone).
  for(const [offset,base] of [[0,659.25],[0.55,783.99],[1.1,987.77]] as const)for(const [ratio,level] of [[1,0.6],[2.01,0.18],[3.02,0.06]] as const){
    const osc=ctx.createOscillator(),gain=ctx.createGain(),t=start+offset
    osc.type='sine';osc.frequency.value=base*ratio
    gain.gain.setValueAtTime(0.0001,t);gain.gain.exponentialRampToValueAtTime(level,t+0.02);gain.gain.exponentialRampToValueAtTime(0.0001,t+2.2)
    osc.connect(gain).connect(out);osc.start(t);osc.stop(t+2.3)
  }
}
export function notify(title:string,body:string){
  try{if('Notification' in window&&Notification.permission==='granted')new Notification(title,{body,silent:true})}catch{/* notifications are optional */}
}
export function askNotificationPermission(){
  try{if('Notification' in window&&Notification.permission==='default')void Notification.requestPermission()}catch{/* optional */}
}
