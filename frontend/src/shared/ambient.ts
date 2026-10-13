/** Procedural ambient soundscapes built from Web Audio noise and filters.
 * Nothing is downloaded: no copyrighted recordings and no binary assets. */
import {audioContext} from './chime'

export const AMBIENT_SOUNDS=[
  {id:'rain',name:'窗外的雨',hint:'沙沙的雨幕与零星雨滴'},
  {id:'cafe',name:'街角咖啡馆',hint:'低低的人声与杯碟轻响'},
  {id:'fireplace',name:'壁炉',hint:'温暖的低鸣与木柴噼啪'},
  {id:'brown',name:'棕噪音',hint:'低沉、柔和，适合长时间专注'},
  {id:'white',name:'白噪音',hint:'均匀的沙沙声，遮住环境杂音'},
] as const
export type AmbientId=typeof AMBIENT_SOUNDS[number]['id']
export type AmbientMix={master:number;layers:Record<AmbientId,number>}
export const DEFAULT_MIX:AmbientMix={master:0.6,layers:{rain:0.6,cafe:0,fireplace:0.35,brown:0,white:0}}
export const AMBIENT_PRESETS:{name:string;mix:Partial<Record<AmbientId,number>>}[]=[
  {name:'雨夜书桌',mix:{rain:0.65,fireplace:0.35}},
  {name:'午后咖啡',mix:{cafe:0.6,brown:0.2}},
  {name:'深度专注',mix:{brown:0.6}},
  {name:'屏蔽杂音',mix:{white:0.45,brown:0.25}},
]

type Layer={gain:GainNode;stop:()=>void}
function noiseBuffer(ctx:AudioContext,kind:'white'|'pink'|'brown',seconds=4){
  const length=Math.floor(ctx.sampleRate*seconds),buffer=ctx.createBuffer(2,length,ctx.sampleRate)
  for(let channel=0;channel<2;channel++){
    const data=buffer.getChannelData(channel);let last=0,b0=0,b1=0,b2=0,b3=0,b4=0,b5=0,b6=0
    for(let i=0;i<length;i++){
      const white=Math.random()*2-1
      if(kind==='white')data[i]=white*0.5
      else if(kind==='brown'){last=(last+0.02*white)/1.02;data[i]=last*3.2}
      else{b0=0.99886*b0+white*0.0555179;b1=0.99332*b1+white*0.0750759;b2=0.969*b2+white*0.153852;b3=0.8665*b3+white*0.3104856;b4=0.55*b4+white*0.5329522;b5=-0.7616*b5-white*0.016898;data[i]=(b0+b1+b2+b3+b4+b5+b6+white*0.5362)*0.11;b6=white*0.115926}
    }
    // crossfade the loop seam
    const fade=Math.min(2048,length>>3);for(let i=0;i<fade;i++){const t=i/fade;data[i]=data[i]*t+data[length-fade+i]*(1-t)}
  }
  return buffer
}
function loop(ctx:AudioContext,buffer:AudioBuffer,destination:AudioNode){const source=ctx.createBufferSource();source.buffer=buffer;source.loop=true;source.connect(destination);source.start();return source}
function filter(ctx:AudioContext,type:BiquadFilterType,frequency:number,q=0.7){const node=ctx.createBiquadFilter();node.type=type;node.frequency.value=frequency;node.Q.value=q;return node}
function lfo(ctx:AudioContext,target:AudioParam,rate:number,depth:number){const osc=ctx.createOscillator(),gain=ctx.createGain();osc.frequency.value=rate;gain.gain.value=depth;osc.connect(gain).connect(target);osc.start();return osc}
/** Short filtered noise burst: a raindrop, a crackle or a cup. */
function burst(ctx:AudioContext,buffer:AudioBuffer,out:AudioNode,{at,duration,frequency,q=1,level}:{at:number;duration:number;frequency:number;q?:number;level:number}){
  const source=ctx.createBufferSource(),band=filter(ctx,'bandpass',frequency,q),gain=ctx.createGain()
  source.buffer=buffer;gain.gain.setValueAtTime(0.0001,at);gain.gain.exponentialRampToValueAtTime(level,at+0.004);gain.gain.exponentialRampToValueAtTime(0.0001,at+duration)
  source.connect(band).connect(gain).connect(out);source.start(at,Math.random()*(buffer.duration-1));source.stop(at+duration+0.05)
}
function scatter(ctx:AudioContext,every:number,jitter:number,spawn:(at:number)=>void){
  // Schedule a little ahead on a coarse JS timer; audio timing stays sample-accurate.
  let cursor=ctx.currentTime+0.1
  const tick=()=>{while(cursor<ctx.currentTime+0.6){spawn(cursor);cursor+=every*(1-jitter/2+Math.random()*jitter)}}
  tick();const timer=window.setInterval(tick,200);return()=>window.clearInterval(timer)
}

function build(ctx:AudioContext,id:AmbientId,out:GainNode):()=>void{
  const nodes:AudioScheduledSourceNode[]=[],stops:(()=>void)[]=[]
  if(id==='white'||id==='brown'){
    const lp=filter(ctx,'lowpass',id==='white'?9000:900);lp.connect(out)
    nodes.push(loop(ctx,noiseBuffer(ctx,id),lp))
  }else if(id==='rain'){
    const pink=noiseBuffer(ctx,'pink'),hp=filter(ctx,'highpass',400),lp=filter(ctx,'lowpass',7000),bed=ctx.createGain();bed.gain.value=0.8
    hp.connect(lp).connect(bed).connect(out);nodes.push(loop(ctx,pink,hp),lfo(ctx,bed.gain,0.07,0.15))
    const white=noiseBuffer(ctx,'white',2)
    stops.push(scatter(ctx,0.045,1.6,at=>burst(ctx,white,out,{at,duration:0.03+Math.random()*0.05,frequency:2500+Math.random()*4000,q:2,level:0.05+Math.random()*0.12})))
  }else if(id==='cafe'){
    const brown=noiseBuffer(ctx,'brown'),murmur=filter(ctx,'bandpass',420,0.6),room=filter(ctx,'lowpass',1600),voice=ctx.createGain();voice.gain.value=0.7
    murmur.connect(room).connect(voice).connect(out);nodes.push(loop(ctx,brown,murmur),lfo(ctx,voice.gain,0.31,0.22),lfo(ctx,murmur.frequency,0.13,120))
    const air=filter(ctx,'lowpass',3000),airGain=ctx.createGain();airGain.gain.value=0.12;air.connect(airGain).connect(out);nodes.push(loop(ctx,noiseBuffer(ctx,'pink'),air))
    stops.push(scatter(ctx,2.6,1.8,at=>{ // a cup or spoon somewhere in the room
      const osc=ctx.createOscillator(),gain=ctx.createGain(),f=2200+Math.random()*1800
      osc.type='sine';osc.frequency.value=f;gain.gain.setValueAtTime(0.0001,at);gain.gain.exponentialRampToValueAtTime(0.03+Math.random()*0.04,at+0.003);gain.gain.exponentialRampToValueAtTime(0.0001,at+0.35)
      osc.connect(gain).connect(out);osc.start(at);osc.stop(at+0.4)
    }))
  }else{
    const brown=noiseBuffer(ctx,'brown'),roar=filter(ctx,'lowpass',380),flame=ctx.createGain();flame.gain.value=0.9
    roar.connect(flame).connect(out);nodes.push(loop(ctx,brown,roar),lfo(ctx,flame.gain,0.4,0.18))
    const white=noiseBuffer(ctx,'white',2)
    stops.push(scatter(ctx,0.32,1.9,at=>{const pops=Math.random()<0.25?3:1;for(let i=0;i<pops;i++)burst(ctx,white,out,{at:at+i*0.03,duration:0.012+Math.random()*0.04,frequency:1200+Math.random()*3500,q:1.4,level:0.08+Math.random()*0.25})}))
  }
  return()=>{stops.forEach(stop=>stop());for(const node of nodes){try{node.stop()}catch{/* already stopped */}node.disconnect()}}
}

export class AmbientMixer{
  private layers=new Map<AmbientId,Layer>();private master:GainNode|null=null;private ctx:AudioContext|null=null
  get playing(){return !!this.master}
  start(mix:AmbientMix){
    this.ctx=audioContext();if(!this.ctx)return false
    if(!this.master){this.master=this.ctx.createGain();this.master.gain.value=0;this.master.connect(this.ctx.destination)}
    this.apply(mix);return true
  }
  apply(mix:AmbientMix){
    if(!this.ctx||!this.master)return
    const now=this.ctx.currentTime
    this.master.gain.setTargetAtTime(Math.max(0,Math.min(1,mix.master))*0.9,now,0.25)
    for(const {id} of AMBIENT_SOUNDS){
      const level=Math.max(0,Math.min(1,mix.layers[id]||0)),layer=this.layers.get(id)
      if(level>0&&!layer){const gain=this.ctx.createGain();gain.gain.value=0;gain.connect(this.master);this.layers.set(id,{gain,stop:build(this.ctx,id,gain)});gain.gain.setTargetAtTime(level,now,0.4)}
      else if(layer&&level===0){layer.gain.gain.setTargetAtTime(0,now,0.25);this.layers.delete(id);window.setTimeout(()=>{layer.stop();layer.gain.disconnect()},1200)}
      else if(layer)layer.gain.gain.setTargetAtTime(level,now,0.3)
    }
  }
  stop(){
    if(!this.ctx||!this.master)return
    const master=this.master,layers=[...this.layers.values()];this.master=null;this.layers.clear()
    master.gain.setTargetAtTime(0,this.ctx.currentTime,0.2)
    window.setTimeout(()=>{layers.forEach(layer=>{layer.stop();layer.gain.disconnect()});master.disconnect()},900)
  }
}
export function loadMix(key:string):AmbientMix{
  try{const value=JSON.parse(localStorage.getItem(key)||'null');if(value&&typeof value.master==='number'&&value.layers)return {master:value.master,layers:{...DEFAULT_MIX.layers,...Object.fromEntries(Object.keys(DEFAULT_MIX.layers).map(id=>[id,Number(value.layers[id])||0]))}}}catch{/* start fresh */}
  return DEFAULT_MIX
}
