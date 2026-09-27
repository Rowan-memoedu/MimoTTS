import {spawn} from 'node:child_process';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {join, dirname} from 'node:path';
import {pathToFileURL} from 'node:url';

// Read-only browser verification in a dedicated, disposable Chrome profile.
const report = process.argv[2] || JSON.parse(await readFile('D:/Artifacts/MimoTTS/latest-report.json','utf8')).path;
const chrome = process.env.LOCALAPPDATA + '/Google/Chrome/Application/chrome.exe';
const profile = `D:/Caches/MimoTTS/chrome-check-${Date.now()}`;
await mkdir(profile, {recursive:true});
const child = spawn(chrome, ['--headless=new', `--user-data-dir=${profile}`, '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--autoplay-policy=no-user-gesture-required', '--mute-audio', 'about:blank'], {windowsHide:true, stdio:'ignore'});
const sleep = ms => new Promise(r=>setTimeout(r,ms));
let ws, sequence=0; const pending = new Map();
function cdp(method,params={}) {
  const id=++sequence;
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error(`CDP timeout: ${method}`))},45000);
    pending.set(id,{resolve,reject,timer});
    ws.send(JSON.stringify({id,method,params}));
  });
}
async function evaluate(expression) {
  const answer=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  if(answer.exceptionDetails) throw new Error(answer.exceptionDetails.text + ': ' + answer.exceptionDetails.exception?.description);
  return answer.result.value;
}
try {
  let port;
  for(let i=0;i<100;i++) {
    try {port=(await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]; break} catch {await sleep(100)}
  }
  if(!port) throw new Error('Chrome did not expose its isolated debugging port');
  const pages=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws=new WebSocket(pages.find(x=>x.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
  ws.onmessage=e=>{const m=JSON.parse(e.data),p=pending.get(m.id);if(p){clearTimeout(p.timer);pending.delete(m.id);m.error?p.reject(new Error(m.error.message)):p.resolve(m.result)}};
  await cdp('Page.enable');
  await cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await cdp('Page.navigate',{url:pathToFileURL(report).href});
  for(let i=0;i<100;i++) {if(await evaluate('document.readyState === "complete" && !!document.querySelector("audio")')) break; await sleep(100)}
  const audio=await evaluate(`(async()=>{
    const out=[];
    for(const p of document.querySelectorAll('audio')) {
      p.muted=true;
      if(p.readyState<1) await new Promise((resolve,reject)=>{p.addEventListener('loadedmetadata',resolve,{once:true});p.addEventListener('error',()=>reject(new Error('Media load failed')),{once:true});setTimeout(()=>reject(new Error('Metadata timeout')),5000)});
      if(!Number.isFinite(p.duration)||p.duration<=0) throw new Error('Invalid duration');
      await p.play();
      await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('Playback did not advance')),4000);const done=()=>{if(p.currentTime>0.05){clearTimeout(timer);p.removeEventListener('timeupdate',done);resolve()}};p.addEventListener('timeupdate',done)});
      out.push({file:p.getAttribute('src'),duration:p.duration,advanced:p.currentTime});p.pause();p.currentTime=0;
    }
    return out;
  })()`);
  const controls=await evaluate(`(async()=>{
    document.querySelector('#speed').value='1.25';document.querySelector('#speed').dispatchEvent(new Event('change'));
    const speed=[...document.querySelectorAll('audio')].every(p=>p.playbackRate===1.25);
    document.querySelector('.pair-play').click();const pair=[...document.querySelector('.pair').querySelectorAll('audio')];
    await new Promise(r=>setTimeout(r,250));const first=!pair[0].paused&&pair[1].paused;
    pair[0].currentTime=pair[0].duration-.08;await new Promise(r=>setTimeout(r,900));
    const second=pair[0].ended&&!pair[1].paused;
    document.querySelector('#stop').click();const stopped=[...document.querySelectorAll('audio')].every(p=>p.paused&&p.currentTime===0);
    document.querySelector('#speed').value='1';document.querySelector('#speed').dispatchEvent(new Event('change'));
    return {speed,first,second,stopped};
  })()`);
  if(Object.values(controls).some(x=>!x)) throw new Error('Playback control verification failed: '+JSON.stringify(controls));
  for(const [width,height,name] of [[1440,1100,'desktop'],[390,844,'mobile']]) {
    await cdp('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
    const overflow=await evaluate('document.documentElement.scrollWidth > innerWidth');
    if(overflow) throw new Error(`Horizontal overflow at ${width}px`);
    const {data}=await cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
    await writeFile(join(dirname(report),`preview-${name}.png`),Buffer.from(data,'base64'));
  }
  const result={ok:true,report,audio_count:audio.length,audio,controls,physical_speaker_verified:false};
  await writeFile(join(dirname(report),'browser-validation.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({ok:true,audio_count:audio.length,controls}));
} finally {
  if(ws?.readyState===WebSocket.OPEN) {await cdp('Browser.close').catch(()=>{});ws.close()}
  for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('Browser closed'))}
  if(child.exitCode===null) child.kill();
}
