/** Evaluates the real --execute body with fake Playwright and no network/browser. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {performance} from 'node:perf_hooks';
import {pathToFileURL} from 'node:url';
import {validateNativeEvents,PHRASES,admitPost} from './event_gate.mjs';
import {privateChild,sha,ROOT} from './binding_gate.mjs';
test('Actual execute flow: normal auth, before/native/after per ES/PT, exactly2MESSAGE4STATUS0other',async()=>{
 const sourcePath=path.join(ROOT,'native_message_live.mjs'),moduleUrl=pathToFileURL(sourcePath).href;
 const source=await fs.readFile(sourcePath,'utf8');
 const base=JSON.parse(await fs.readFile('[private-local-path]','utf8'));
 const asset='assets/index-Css6KlOl.js',assetBytes=await fs.readFile(path.join('[private-local-path]',asset));
 const cfg={runtime:{git_head:'f2fa597a481a87b5301531cf180f8f61d1f3ba70',image_digest:'sha256:'+'f'.repeat(64),browser_source:base.final_head,served_ui:base.new_browser},expected_runtime_sha256:'e'.repeat(64),native_harness_sha256:sha(source),base_url:'https://savia-rc-2026.fly.dev',gateway:{label:'Mock entry',button:'Mock enter',code:'mock-only'},code:'mock-only',cases:[{language:'es',profile:'mexico'},{language:'pt',profile:'colombia'}]};
 const calls=[],writes=[],logs=[];let contexts=0,bindings=0;
 const mockBrowser={async close(){},async newContext(){
  const index=contexts++,entry=index%2===0,spec=cfg.cases[Math.floor(index/2)];let routing,listener,waits=0;
  const context={async route(pattern,fn){routing=fn;},async close(){},async storageState(){return {cookies:[],origins:[]};},async newPage(){
   const locator={async count(){return 0;},async fill(){},async selectOption(){},async click(){},getByRole(){return this;},filter(){return this;}};
   const page={setDefaultTimeout(){},on(event,fn){if(event==='response')listener=fn;},locator(query){return {...locator,async count(){return query==='nav'?1:0;}};},getByLabel(){return {...locator,async count(){return 0;}};},getByRole(){return locator;},async waitForResponse(){const profiles=waits++===0;return {status:()=>200,json:async()=>({profiles:[{id:spec.profile,alias:'Mock Profile'}]})};},async goto(){if(!entry)listener?.({url:()=>cfg.base_url+'/'+asset,status:()=>200,body:async()=>assetBytes});},async evaluate(fn,arg){
    if(!arg)return {status:200,body:{products:[{reference:'mock-owned-card',status:'Active',type:spec.language==='es'?'Tarjeta':'Cartão',card_protection_status:'blocked'}]}};
    const native=Object.hasOwn(arg,'message'),route=native?'/api/voice/turn':'/api/cards/block';
    const body=native?{message:arg.message,language:arg.language,fresh:true}:{product_reference:arg.reference,operation:'status',language:arg.language};
    let forwarded=false;
    await routing({request:()=>({url:()=>cfg.base_url+route,method:()=> 'POST',postDataJSON:()=>body}),async continue(){forwarded=true;calls.push({route,body});},async abort(){throw Error('Mock route rejected');}});
    assert.equal(forwarded,true);
    if(native){const events=[{type:'start',sample_rate:24000,turn_id:'mock-'+spec.language},{type:'audio',data:Buffer.from([1,0,2,0]).toString('base64')},{type:'delegate',request:PHRASES[spec.language]},{type:'complete',turn_id:'mock-'+spec.language,samples:2,text:spec.language==='es'?'Voy a consultar tu petición.':'Vou consultar seu pedido.'}];return {status:200,contentType:'application/x-ndjson',text:events.map(x=>JSON.stringify(x)).join('\n')+'\n'};}
    return {status:200,body:{state:'card_block_verified',product_reference:arg.reference,simulated:true,real_bank_action:false,receipt:{schema:'savia-simulated-card-block/v1',status:'blocked',simulated:true,real_bank_action:false,mockStableReceipt:'same'}}};
   }};return page;
  }};return context;
 }};
 const mockPW={chromium:{async launch(){return mockBrowser;}}};
 const mockFS={...fs,async writeFile(file,...args){writes.push(file);return fs.writeFile(file,...args);}};
 const sandboxProcess={argv:['node','native_message_live.mjs','--execute','mock-binding.private.json'],exitCode:0};
 const sandboxRoot=path.join(ROOT,'mock-tests','execute-'+Date.now());
 const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
 const script=source.replace(/^import .*;\r?\n/gm,'').replaceAll('import.meta.url','moduleUrl');
 await new AsyncFunction('fs','path','assert','createRequire','performance','validateBinding','privateChild','sha','ROOT','validateNativeEvents','PHRASES','admitPost','process','console','moduleUrl',script)(mockFS,path,assert,()=>()=>mockPW,performance,async()=>{bindings++;return {cfg};},privateChild,sha,sandboxRoot,validateNativeEvents,PHRASES,admitPost,sandboxProcess,{log(value){logs.push(value);}},moduleUrl);
 assert.equal(bindings,2);assert.equal(contexts,4);assert.equal(sandboxProcess.exitCode,0);
 assert.deepEqual(calls.map(x=>x.route),['/api/cards/block','/api/voice/turn','/api/cards/block','/api/cards/block','/api/voice/turn','/api/cards/block']);
 assert.deepEqual(calls.filter(x=>x.route==='/api/voice/turn').map(x=>x.body),[{message:PHRASES.es,language:'es',fresh:true},{message:PHRASES.pt,language:'pt',fresh:true}]);
 assert.equal(calls.filter(x=>x.route==='/api/cards/block').length,4);assert(calls.every(x=>x.route==='/api/voice/turn'||x.body.operation==='status'));
 const receiptPath=writes.find(x=>path.basename(x)==='receipt-private.json');assert(receiptPath);
 const receipt=JSON.parse(await fs.readFile(receiptPath,'utf8'));assert.equal(receipt.passed,true);assert.equal(receipt.observedProviderEligibleRequests,2);assert.equal(receipt.observedCardStatusRequests,4);assert(receipt.cases.every(x=>x.existingCardProtection.savedReceiptUnchanged));
 assert(receipt.cases.every(x=>x.nativeAdmission.exactDelegate&&x.nativeAdmission.audioPlayed===false&&x.nativeAdmission.actualUIPlayedAck===false));
 assert.equal(JSON.parse(logs[0]).passed,true);
});
