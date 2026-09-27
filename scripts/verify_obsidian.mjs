// Exercise the installed plugin through Obsidian's official CLI using public text.
import {execFileSync} from 'node:child_process';
import {readFileSync, writeFileSync, mkdirSync, statSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';

const root = 'D:/Artifacts/MimoTTS/production/20260927';
const report = 'D:/Artifacts/MimoTTS/reports/20260927-161426';
const cli = process.env.LOCALAPPDATA + '/Programs/Obsidian/Obsidian.com';
const input = join(root, 'obsidian-public-fixture.txt');
const text = 'A new idea becomes easier to understand when you connect it to what you already know. Pause at the end of a paragraph, then read the next part.';
writeFileSync(input, text, 'utf8');
mkdirSync(join(report, 'audio'), {recursive:true});
const files = {old:join(report,'audio/obsidian-old.mp3'),new:join(report,'audio/obsidian-new.mp3')};
const code = `(async()=>{
  const p=app.plugins.plugins['note-reader-cosyvoice-focus'];
  if(p.activeSession || p.currentProcess) throw new Error('Reader is busy; defer the public canary');
  const q=Object.create(p);
  q.settings={...p.settings};
  q.isActive=()=>true;
  const results=[];
  for(const [side,engine] of [['old','edge-tts'],['new','mimo-tts']]) {
    const started=performance.now();
    await q.runSpeechEngine(${JSON.stringify(input)},${JSON.stringify(files)}[side],{},engine);
    results.push({side,engine,wall_seconds:(performance.now()-started)/1000,voice:side==='old'?q.settings.edgeTtsVoice:q.settings.mimoVoice,speed:q.settings.speed});
  }
  return JSON.stringify({results,plugin_version:p.manifest.version,engine:p.settings.speechEngine,pid:process.pid,leaves:app.workspace.getLeavesOfType('note-reader-cosyvoice-focus-control').map(x=>x.id)});
})()`;
const stdout = execFileSync(cli,['eval','vault=新建文件夹','code='+code],{encoding:'utf8',timeout:180000,windowsHide:true});
const line = stdout.split(/\r?\n/).find(x=>x.startsWith('=> '));
if(!line) throw new Error('Obsidian CLI did not return a canary receipt');
const live = JSON.parse(line.slice(3));
const records = live.results.map(result=>{
  const file = files[result.side];
  execFileSync('ffmpeg',['-nostdin','-v','error','-i',file,'-f','null','-'],{stdio:'pipe',timeout:60000,windowsHide:true});
  const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-show_format','-of','json',file],{encoding:'utf8',windowsHide:true}));
  return {...result,ok:true,path:'audio/obsidian-'+result.side+'.mp3',audio_seconds:Number(probe.format.duration),bytes:statSync(file).size,sha256:createHash('sha256').update(readFileSync(file)).digest('hex')};
});
const data=JSON.parse(readFileSync(join(report,'results.json'),'utf8'));
if(data.cases.some(x=>x.id==='obsidian')) throw new Error('Existing comparison must not be replaced');
data.cases.push({id:'obsidian',title:'Obsidian 阅读器 · 现用语速',text,old_provider:'edge',old_voice:records[0].voice,old_label:'Edge TTS / '+records[0].voice,new_voice:records[1].voice,note:'两侧均通过当前已加载的阅读器插件调用；保留现用 0.8 倍语速。当前源码保留分段、高亮、导出及右侧面板；录音使用公开测试文本。',results:records});
writeFileSync(join(report,'results.json'),JSON.stringify(data,null,2));
writeFileSync(join(root,'obsidian-live-canary.json'),JSON.stringify({...live,records,physical_speaker_verified:false},null,2));
console.log(JSON.stringify({ok:true,...live,audio_files:2,fully_decoded:true}));
