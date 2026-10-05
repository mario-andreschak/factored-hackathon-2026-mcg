/** Actual browser capture. No routes/mocks, injected replies, or visual edits.
 * Usage: node record_customer.mjs PRIVATE_CONFIG OUTPUT_DIR [PRIVATE_RECIPE]
 * Config: base_url,code,profile,generated_only:true,runtime, optional channel.
 * Recipe steps: click {role,name}, fill {role,name,value}, wait {text},
 * snapshot {name}, pause {ms}, reload. Regex names use name_regex:true.
 * Public output contains only fictional on-screen text and timings.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {performance} from 'node:perf_hooks';
import {createHash} from 'node:crypto';
import {captureReleaseAudio} from './capture_savia_audio.mjs';
const require=createRequire(import.meta.url);
let playwright;
try { playwright=require('playwright'); }
catch { playwright=require(path.join(process.env.LOCALAPPDATA ?? 'C:/Users/Moe/AppData/Local','../../.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')); }
const [cfgPath,outDir,recipePath]=process.argv.slice(2);
if(!cfgPath || !outDir) throw Error('private config and new output directory required');
const cfg=JSON.parse(await fs.readFile(cfgPath,'utf8'));
if(cfg.generated_only!==true || !cfg.runtime) throw Error('confirmed generated-only runtime required');
await fs.mkdir(outDir,{recursive:false});
const browser=await playwright.chromium.launch({headless:true,...(cfg.channel?{channel:cfg.channel}:{}),...(cfg.fake_audio_wav?{args:['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--use-file-for-fake-audio-capture='+path.resolve(cfg.fake_audio_wav)]}:{})});
const viewport=cfg.viewport??{width:1280,height:720};
const context=await browser.newContext({viewport,recordVideo:{dir:outDir,size:viewport},locale:'es-CO',timezoneId:cfg.timezone??'America/Bogota',...(cfg.fake_audio_wav?{permissions:['microphone']}:{}),...(cfg.load_storage_state_private?{storageState:cfg.load_storage_state_private}:{})});
let authentication={private_state_loaded:Boolean(cfg.load_storage_state_private),fresh_login:false};
let needsLogin=!cfg.load_storage_state_private;
if(cfg.load_storage_state_private){
 const existing=await context.request.get(cfg.base_url+(cfg.login_path??'/api/auth/login').replace(/\/login$/,'/me'));
 authentication.existing_session_http_status=existing.status();
 needsLogin=existing.status()===401;
 if(!existing.ok()&&!needsLogin){await browser.close();throw Error('fictional session check failed');}
}
if(needsLogin){
 const auth=await context.request.post(cfg.base_url+(cfg.login_path??'/api/auth/login'),{data:{profile:cfg.profile,code:cfg.code},headers:{Origin:cfg.base_url}});
 if(!auth.ok()) {await browser.close();throw Error('fictional login failed');}
 authentication.fresh_login=true;
}
const privateState=path.join(path.dirname(cfgPath),path.basename(outDir)+'.browser-state.json');
await context.storageState({path:privateState});
const page=await context.newPage();
const finalizeAudio=cfg.capture_native_audio?await captureReleaseAudio(page,path.join(outDir,'audio')):null;
const start=performance.now(),startedAt=new Date().toISOString(),events=[],responseTasks=[],served_js_assets=[];
await page.exposeBinding('recordVoiceMilestone',(_,{event,at})=>events.push({kind:'voice-milestone',event,browser_at_ms:at,at_ms:Math.round(performance.now()-start)}));
await page.addInitScript(()=>window.addEventListener('savia:voice-milestone',e=>window.recordVoiceMilestone({event:e.detail?.event,at:e.detail?.at})));
page.on('request',r=>{
 const pathname=new URL(r.url()).pathname;
 if(pathname.includes('/api/'))events.push({kind:'http-request',method:r.method(),path:pathname,at_ms:Math.round(performance.now()-start)});
});
page.on('response',r=>{
 const pathname=new URL(r.url()).pathname;
 if(pathname.endsWith('.js'))responseTasks.push((async()=>{try{served_js_assets.push({path:pathname,status:r.status(),sha256:createHash('sha256').update(await r.body()).digest('hex')});}catch{}})());
 if(!pathname.includes('/api/'))return;
 const entry={kind:'http',method:r.request().method(),path:pathname,status:r.status(),at_ms:Math.round(performance.now()-start)};
 events.push(entry);
 if(/\/(chat\/messages|chat\/history|action\/|followups|assistant\/)/.test(pathname))responseTasks.push((async()=>{
  try {const body=await r.json();entry.public_response=Object.fromEntries(['reply','state','message','mode','status','messages','active','followups','updates','next_step','items','id','workers','events','status_message','created_at','updated_at','next_check_at','informational_only','bank_authority','event_id','inquiry_state'].filter(k=>k in body).map(k=>[k,body[k]]));
   if(body.receipt)entry.receipt={kind:body.receipt.kind,simulated:body.receipt.simulated,transaction:body.receipt.transaction};
  }catch{}
 })());
});
await page.goto(cfg.base_url,{waitUntil:'networkidle'});
const recipe=recipePath?JSON.parse(await fs.readFile(recipePath,'utf8')):[{snapshot:'overview'}];
const snapshots=[];
const publicCapture=()=>({schema:'savia-actual-browser-capture/v1',started_at:startedAt,recorded_at:new Date().toISOString(),timezone:cfg.timezone??'America/Bogota',runtime:cfg.runtime,authentication,served_js_assets,generated_only:true,actual_browser:true,mocked_requests:0,events,snapshots});
async function* steps(){
 if(Array.isArray(recipe)){yield* recipe;return;}
 yield* recipe.initial??[];
 let seen=0;
 while(recipe.commands_private){
  let lines=[];try{lines=(await fs.readFile(recipe.commands_private,'utf8')).split(/\r?\n/).filter(Boolean);}catch{}
  while(seen<lines.length){const step=JSON.parse(lines[seen++]);if(step.finish)return;yield step;}
  await new Promise(r=>setTimeout(r,200));
 }
}
try {
let i=0;
for await(const step of steps()){
 const stamp={index:i,at_ms:Math.round(performance.now()-start),step:step.snapshot??step.click?.name??step.fill?.name??step.wait?.text??Object.keys(step)[0]};
 events.push(stamp);
 const scope=step.frame_selector?page.frameLocator(step.frame_selector):page;
 if(step.click){const s=step.click;await scope.getByRole(s.role??'button',{name:s.name_regex?new RegExp(s.name,'i'):s.name,exact:!s.name_regex}).click();}
 if(step.click_text)await scope.getByText(step.click_text,{exact:true}).click();
 if(step.fill){const s=step.fill;await scope.getByRole(s.role??'textbox',{name:s.name_regex?new RegExp(s.name,'i'):s.name,exact:!s.name_regex}).fill(s.value);}
 if(step.wait)await page.getByText(step.wait.text,{exact:false}).first().waitFor({timeout:step.wait.timeout??600000});
 if(step.pause)await page.waitForTimeout(Math.min(step.pause.ms,60000));
 if(step.reload)await page.reload({waitUntil:'networkidle'});
 if(step.goto)await page.goto(new URL(step.goto,cfg.base_url).href,{waitUntil:'networkidle'});
 if(step.press)await page.keyboard.press(step.press);
 if(step.scroll_text)await scope.getByText(step.scroll_text,{exact:false}).first().scrollIntoViewIfNeeded();
 if(step.select){const s=step.select;await scope.getByRole('combobox',{name:s.name,exact:true}).selectOption(s.value);}
 if(step.wait_enabled){const s=step.wait_enabled;await scope.getByRole(s.role??'textbox',{name:s.name,exact:true}).waitFor({state:'visible',timeout:600000});await scope.getByRole(s.role??'textbox',{name:s.name,exact:true}).evaluate(async el=>{for(let n=0;n<1200&&el.disabled;n++)await new Promise(r=>setTimeout(r,500));if(el.disabled)throw Error('control still disabled');});}
 if(step.snapshot){
  const name=step.snapshot.replace(/[^a-z0-9_-]/gi,'_');
  await page.screenshot({path:path.join(outDir,name+'.png'),fullPage:false});
  const text=await page.locator('body').innerText();
  const controls=await page.locator('button,input,textarea,select').evaluateAll(nodes=>nodes.map(n=>({tag:n.tagName,type:n.type??'',text:n.tagName==='INPUT'?'':n.textContent?.trim().slice(0,180),placeholder:n.getAttribute('placeholder'),ariaLabel:n.getAttribute('aria-label')})));
  const loaded_js_assets=await page.locator('script[src]').evaluateAll(nodes=>nodes.map(n=>new URL(n.src).pathname));
  snapshots.push({name,text,controls,loaded_js_assets,at_ms:Math.round(performance.now()-start)});
  await fs.writeFile(path.join(outDir,'capture-progress.json'),JSON.stringify(publicCapture(),null,2));
  console.log(JSON.stringify({snapshot:name,at_ms:Math.round(performance.now()-start)}));
 }
 i++;
}
} finally {
 await page.waitForTimeout(1500);
 await Promise.allSettled(responseTasks);
 if(finalizeAudio)await finalizeAudio();
 const video=page.video();
 await context.storageState({path:privateState});
 await context.close();
 if(video){
  const original=await video.path();
  const final=path.resolve(outDir,'actual-browser.webm');
  await video.saveAs(final);
  if(path.dirname(original)===path.resolve(outDir)&&original!==final)await fs.unlink(original);
 }
 await browser.close();
 await fs.writeFile(path.join(outDir,'capture.json'),JSON.stringify(publicCapture(),null,2));
}
console.log(JSON.stringify({output:outDir,snapshots:snapshots.length,duration_ms:Math.round(performance.now()-start)}));
