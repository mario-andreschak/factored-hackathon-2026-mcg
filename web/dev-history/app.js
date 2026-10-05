/* SAVIA development history. No build step or external dependencies. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const SOURCE_DEFAULTS = {
    github: { label: 'GitHub', color: '#c7ff5e' },
    slack: { label: 'Slack', color: '#ac9bff' },
    codex: { label: 'Codex', color: '#64d8ff' },
    flujo: { label: 'FLUJO', color: '#ffbd80' },
    docs: { label: 'Docs', color: '#ff91bd' },
    infrastructure: { label: 'Machines', color: '#9ce6bf' }
  };
  const WORKSTREAMS = {backend:'Backend',mcp:'MCP & tools',dataset:'Data & pipeline',frontend:'Frontend & experience',deployment:'Deployment',review:'Review & validation',steering:'Team steering',ci:'CI & automation',research:'Research'};
  const PAGE_SIZE = 40;
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const state = {
    data: null, events: [], filtered: [], sources: [], enabled: new Set(), selected: -1,
    search: '', workstream: '', includeAll: true, page: 0, duration: 180000,
    offsets: [], totalWeight: 1, position: 0, speed: 1, playing: false,
    previousFrame: 0, raf: 0, view: 'activity', width: 0, height: 0, dpr: 1,
    base: document.createElement('canvas'), eventById: new Map(), hitNodes: [], hitEdges: [],
    plotLeft: 96, plotRight: 12, laneY: [], min: 0, max: 0, chapters: [],
    now: 0, connectionStamp: '', searchCache: new Map(), bodyLoads: new Map(), bodyRequest: 0,
    playbackMode: 'all', storyIndices: [], allLinks: false, dwell:850, engine:new window.HistoryReplayEngine(), eventProgress:0, episodes:[], episode:-1, graph:null, sessionFilter:'', flowId:'', chatEvents:new Map(), sessions:new Map(), focusTimer:0, focusToken:0
  };
  const canvas = $('timeline-canvas');
  const ctx = canvas.getContext('2d');
  let timezone = 'America/Bogota';
  let dateFormat, shortFormat, timeFormat, fullFormat;
  const number = n => Number(n || 0).toLocaleString('en-US');
  const str = v => v == null ? '' : typeof v === 'string' ? v : typeof v === 'object' ? JSON.stringify(v) : String(v);
  const clip = (s, n = 170) => s.length > n ? s.slice(0, n - 1) + '…' : s;
  const readable = value => {let text=str(value);if(text.startsWith('<send_user_message_question_reply>')){try{const replies=JSON.parse(text.replace(/<\/?send_user_message_question_reply>/g,''));text=replies.map(reply=>`${reply.question}\n${reply.answer}`).join('\n\n');}catch(_){}}return text.replace(/<!(here|channel|everyone)>/g,'@$1').replace(/<@[^>|]+\|([^>]+)>/g,'$1').replace(/<#[^>|]+\|([^>]+)>/g,'#$1').replace(/<(https?:\/\/[^>|]+)\|([^>]+)>/g,'$2');};
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const safeTimestamp = v => Number.isFinite(Date.parse(v)) ? Date.parse(v) : null;
  const sourceDef = id => state.sources.find(s => s.id === id) || SOURCE_DEFAULTS[id] || {id,label:id,color:'#c4d1e5'};
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };
  const dot = id => {const node=el('span','source-dot');node.style.setProperty('--source-color',sourceDef(id).color);node.setAttribute('aria-hidden','true');return node;};
  function formatters() {
    const options = {timeZone:timezone};
    try {
      dateFormat = new Intl.DateTimeFormat('en-US',{...options,month:'short',day:'2-digit',year:'numeric'});
      shortFormat = new Intl.DateTimeFormat('en-US',{...options,month:'short',day:'2-digit'});
      timeFormat = new Intl.DateTimeFormat('en-GB',{...options,hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
      fullFormat = new Intl.DateTimeFormat('en-US',{...options,weekday:'short',month:'short',day:'numeric',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
    } catch (_) {timezone='America/Bogota';formatters();}
  }
  function timeLabel(ms) { return Number.isFinite(ms) ? `${fullFormat.format(ms)} · Bogotá` : 'Timestamp unavailable'; }
  function durationLabel(ms) { const sec=Math.floor(ms/1000),hours=Math.floor(sec/3600);return `${hours?hours+':':''}${String(Math.floor(sec/60)%60).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}`; }
  function safeUrl(value) {
    if (!value) return null;
    try {const url=new URL(str(value),location.href);return ['https:','http:','codex:'].includes(url.protocol)?url.href:null;}catch(_){return null;}
  }
  function visibleBody(event) {return str(event.body) || 'No message body was captured for this record.';}
  function chatBody(event,body=visibleBody(event)) {let text=readable(body);if(event.source==='slack'){if(event.metadata?.reactions?.length)text=text.replace(/^Reactions:.*$/gm,'');if(event.metadata?.files?.length)text=text.replace(/^Files?:.*$/gm,'');text=text.replace(/:([a-z0-9_+-]+):/g,(match,name)=>REACTION_EMOJI[name]||match);}return text.trim();}
  const REACTION_EMOJI={eyes:'👀',heart:'❤️',heart_eyes:'😍',rocket:'🚀',raised_hands:'🙌',muscle:'💪',tada:'🎉',partying_face:'🥳',clap:'👏',fire:'🔥',white_check_mark:'✅',heavy_check_mark:'✔️',thumbsup:'👍','+1':'👍',thumbsdown:'👎','-1':'👎',slightly_smiling_face:'🙂',smile:'😄',laughing:'😆',joy:'😂',sweat_smile:'😅',thinking_face:'🤔',pray:'🙏',handshake:'🤝',wave:'👋',100:'💯',star:'⭐',sparkles:'✨',brain:'🧠',computer:'💻',robot_face:'🤖',warning:'⚠️',x:'❌',saluting_face:'🫡',sob:'😭',sunglasses:'😎',bulb:'💡',ok_hand:'👌',point_up:'☝️',point_up_2:'👆',grinning:'😀',heart_hands:'🫶',blue_heart:'💙',green_heart:'💚'};
  function reactionEmoji(name) {const [base,tone]=str(name).split('::');return (REACTION_EMOJI[base]||`:${base}:`)+(tone&&/^skin-tone-[2-6]$/.test(tone)?String.fromCodePoint(0x1f3fa+Number(tone.at(-1))):'');}
  function localImage(value) {return /^data\/media\/slack-F[A-Z0-9]+-[a-f0-9]{16}\.png$/.test(str(value))?str(value):null;}
  function renderChatMedia(event,mediaContainer,reactionContainer) {
    mediaContainer.replaceChildren();reactionContainer.replaceChildren();
    const files=Array.isArray(event.metadata?.files)?event.metadata.files:[],reactions=Array.isArray(event.metadata?.reactions)?event.metadata.reactions:[];
    mediaContainer.hidden=!files.length;reactionContainer.hidden=!reactions.length;
    for(const file of files){
      const figure=el('figure','chat-attachment'),src=file.status==='available'?localImage(file.src):null;
      if(src){const anchor=el('a','attachment-image-link');anchor.href=src;anchor.target='_blank';anchor.rel='noopener';anchor.title='Open captured image at full size';const image=el('img');image.src=src;image.alt=str(file.title||file.name||'Captured Slack image');image.loading='lazy';image.decoding='async';if(file.width&&file.height){image.width=file.width;image.height=file.height;}anchor.append(image);figure.append(anchor);}
      else{const placeholder=el('div','attachment-placeholder');placeholder.append(el('span','attachment-glyph',file.isImage?'▧':'▤'),el('span','',file.isImage?(file.status==='withheld'?'Image withheld for contact privacy':'Image unavailable'):'Attached file'));figure.append(placeholder);}
      const caption=el('figcaption');caption.append(el('strong','',str(file.title||file.name||file.id)));
      if(src)caption.append(el('span','',`${file.width} × ${file.height} · local copy`));else if(file.reason)caption.append(el('span','',str(file.reason)));
      figure.append(caption);mediaContainer.append(figure);
    }
    if(reactions.length){reactionContainer.append(el('span','reactions-label','REACTIONS AT CAPTURE'));const chips=el('div','reaction-chips');
      for(const reaction of reactions){if(!reaction.name||!Number.isFinite(Number(reaction.count)))continue;const chip=el('span','reaction-chip');chip.title=`:${reaction.name}: · ${number(reaction.count)} reactions observed in the source snapshot`;chip.setAttribute('aria-label',`${reaction.name}, ${number(reaction.count)} reactions`);chip.append(el('span','reaction-emoji',reactionEmoji(reaction.name)),el('span','reaction-count',number(reaction.count)));chips.append(chip);}reactionContainer.append(chips);
    }
  }
  function byline(container,event) {
    container.replaceChildren();
    const actor=(str(event.actor).replace(/\s*\([UB][A-Z0-9]+\)\s*$/,'') || 'Unattributed');
    const avatar=el('span','actor-avatar',actor.split(/\s+/).map(s=>s[0]).join('').slice(0,2).toUpperCase());
    avatar.setAttribute('aria-hidden','true');container.append(avatar,el('span','',actor));
    const thread=str(event.metadata?.channel || event.metadata?.projectName || event.metadata?.repository || '');
    if(thread) container.append(el('span','subtle',clip(thread,70)));
  }
  function renderSourceApp(event) {
    const pane=document.querySelector('.event-focus'),meta=event.metadata||{},session=state.sessions.get(meta.sessionId);
    pane.dataset.app=event.source;pane.dataset.role=meta.role||'';
    renderChatMedia(event,$('focus-media'),$('focus-reactions'));
    const names={slack:'Slack',codex:'Codex',flujo:'FLUJO',github:'GitHub',infrastructure:'Terminal',docs:'Project documents'};
    $('source-app-name').textContent=names[event.source]||sourceDef(event.source).label;
    const contexts={slack:`# ${meta.channel||'conversation'}`,codex:'factored-hackathon-2026',flujo:meta.flowName||session?.flowLabel||'Development conversations',github:'factored-hackathon-2026-mcg',infrastructure:[meta.provider,meta.location||meta.region].filter(Boolean).join(' / ')||'Recorded build output',docs:'Repository / challenge references'};
    $('source-app-context').textContent=contexts[event.source]||'Captured activity';
    const chips=$('source-thread-context');chips.replaceChildren();
    const labels=[];
    if(session?.role)labels.push(session.role);
    if(session?.parentId)labels.push(`Child of ${clip(state.sessions.get(session.parentId)?.label||session.parentId,55)}`);
    if(meta.nodeId){const flow=(state.data.topology?.flows||[]).find(f=>f.id===meta.flowId);labels.push(`Node: ${flow?.nodes?.find(n=>n.id===meta.nodeId)?.label||meta.nodeId}`);}
    if(event.source==='slack')labels.push(event.kind==='reply'?'Thread reply · channel context':'Channel message');
    else if(!labels.length&&event.threadId)labels.push(`Chat ${clip(str(session?.label||meta.threadTitle||event.threadId),75)}`);
    if(meta.machineId)labels.push(`Machine ${clip(str(meta.machineId),40)}`);
    for(const label of labels.slice(0,3))chips.append(el('span','',label));
    const key=`${event.source}:${event.source==='slack'?meta.channel:(event.threadId||meta.channel||'')}`,messages=state.chatEvents.get(key)||[];
    const pos=messages.indexOf(event),previous=pos>0?messages.slice(Math.max(0,pos-2),pos):[];
    $('source-chat-context').replaceChildren();
    if(['slack','codex','flujo'].includes(event.source))for(const item of previous){
      const row=el('div','previous-chat');row.append(el('strong','',`${str(item.actor||item.metadata?.role||'Message').replace(/\s*\([UB][A-Z0-9]+\)\s*$/,'')} · ${timeFormat.format(item.ms)}`),el('p','',clip(chatBody(item),140)));$('source-chat-context').append(row);
    }
    clearTimeout(state.focusTimer);const token=++state.focusToken;
    if(event.bodyRef)state.focusTimer=setTimeout(async()=>{
      try{const body=await fullBody(event);if(token!==state.focusToken)return;$('focus-body').textContent=clip(chatBody(event,body),16000);}
      catch(_){/* The full-record action can retry a failed local shard. */}
    },280);
  }
  function configureSystem() {
    const topology=state.data.topology||{},infra=state.data.infrastructure||{};
    state.sessions=new Map((topology.sessions||[]).map(s=>[s.id,s]));
    for(const event of state.events){const key=`${event.source}:${event.source==='slack'?event.metadata?.channel:(event.threadId||event.metadata?.channel||'')}`;if(!state.chatEvents.has(key))state.chatEvents.set(key,[]);state.chatEvents.get(key).push(event);}
    $('metric-chats').textContent=number(state.sessions.size);$('metric-dispatches').textContent=number(topology.agentEdges?.length);
    $('metric-flows').textContent=number(topology.flows?.length);$('metric-machines').textContent=number(infra.machines?.length);
    const roots=(topology.sessions||[]).filter(s=>!s.parentId||!state.sessions.has(s.parentId));
    for(const session of roots){const option=el('option','',`${sourceDef(session.source).label} · ${clip(session.label||session.id,75)}`);option.value=session.id;$('session-filter').append(option);}
    for(const flow of topology.flows||[]){const option=el('option','',`${flow.label||flow.name||flow.id} · ${flow.nodes?.length||0} nodes · ${flow.availableFrom?shortFormat.format(Date.parse(flow.availableFrom)):'snapshot'}`);option.value=flow.id;$('flow-filter').append(option);}
    state.graph=new window.HistoryGraphScene(canvas,{
      onSelect:hit=>{pause();if(hit.type==='event'&&state.eventById.has(hit.id))openEvent(state.eventById.get(hit.id));else inspectSystem(hit);},
      onInspect:(hit,point)=>{const tip=$('canvas-tooltip');tip.hidden=!hit;if(!hit)return;tip.textContent=`${hit.label} · click for recorded evidence`;tip.style.left=`${clamp(point.x+12,5,state.width-Math.min(260,state.width-10))}px`;tip.style.top=`${clamp(point.y+15,5,state.height-65)}px`;}
    });state.graph.setData({...state.data,events:state.events});
    // Keep narration visible with its replay controls and related graph.
    document.querySelector('.player-section').insertBefore($('narrative-stage'),document.querySelector('.flight-deck'));
  }
  function inspectSystem(hit) {
    const item=hit.item||{};$('system-inspector').hidden=false;$('inspector-title').textContent=hit.label||item.label||item.title||hit.id;
    const facts=[item.description,item.basis,item.startBasis,item.endBasis,item.graphBasis,item.statusBasis].filter(Boolean);
    if(item.provider)facts.unshift(`${item.provider} · ${item.location||item.region||'Location not recorded'}`);
    if(item.parentId)facts.unshift(`Parent: ${state.sessions.get(item.parentId)?.label||item.parentId}`);
    if(item.startedAt)facts.push(`Started: ${timeLabel(Date.parse(item.startedAt))}. Last recorded activity: ${timeLabel(Date.parse(item.lastActivityAt||item.startedAt))}.`);
    $('inspector-summary').textContent=facts.join(' ')||'Select the cited records to inspect this relationship and its provenance.';
    $('inspector-data').textContent=JSON.stringify(item,null,2);const evidence=$('inspector-evidence');evidence.replaceChildren();
    const ids=(hit.eventIds||[]).filter(id=>state.eventById.has(id));
    const events=ids.map(id=>state.eventById.get(id));const before=events.filter(e=>e.ms<=state.now).slice(-5);const shown=before.length?before:events.slice(0,5);
    for(const event of shown){const button=el('button','',`${sourceDef(event.source).label} · ${clip(event.title,90)} · ${shortFormat.format(event.ms)}`);button.type='button';button.addEventListener('click',()=>openEvidence([event.id],event.ms));evidence.append(button);}
    if(ids.length>shown.length)evidence.append(el('span','subtle',`${number(ids.length)} linked records in this structure.`));
    $('system-inspector').scrollIntoView({behavior:reducedMotion.matches?'instant':'smooth',block:'nearest'});
  }
  function configureSources() {
    const supplied = Array.isArray(state.data.sources) ? state.data.sources : [];
    const ids=[...new Set([...Object.keys(SOURCE_DEFAULTS),...supplied.map(s=>s.id),...state.events.map(e=>e.source)])];
    state.sources=ids.map(id=>{
      const original=supplied.find(s=>s.id===id)||{};
      const defaults=SOURCE_DEFAULTS[id]||{label:id,color:'#c4d1e5'};
      const count=state.events.reduce((n,e)=>n+(e.source===id),0);
      return {...original,id,label:defaults.label,color:defaults.color,eventCount:count,status:original.status|| (count?'ok':'unavailable'),notes:Array.isArray(original.notes)?original.notes:[]};
    });
    state.enabled=new Set(ids);
    $('source-legend').replaceChildren();$('archive-filters').replaceChildren();
    const all=el('button','filter-button','All sources');all.type='button';all.dataset.source='all';all.addEventListener('click',()=>{state.enabled=new Set(state.sources.map(s=>s.id));applyFilters();});$('archive-filters').append(all);
    for(const source of state.sources){
      const legend=el('button','source-toggle');legend.type='button';legend.dataset.source=source.id;legend.append(dot(source.id),el('span','',source.label),el('span','legend-count',number(source.eventCount)));
      legend.title=`Toggle ${source.label} events`;legend.addEventListener('click',()=>toggleSource(source.id));$('source-legend').append(legend);
      const filter=el('button','filter-button');filter.type='button';filter.dataset.source=source.id;filter.append(dot(source.id),el('span','',source.label));filter.addEventListener('click',()=>{
        if(state.enabled.size===1 && state.enabled.has(source.id)) state.enabled=new Set(state.sources.map(s=>s.id));
        else state.enabled=new Set([source.id]);
        applyFilters();
      });$('archive-filters').append(filter);
    }
  }
  function toggleSource(id) {state.enabled.has(id)?state.enabled.delete(id):state.enabled.add(id);applyFilters();}
  function renderCoverage() {
    $('coverage-list').replaceChildren();
    for(const source of state.sources){
      const item=el('section','coverage-item');const header=el('header');const name=el('span','coverage-name');name.append(dot(source.id),document.createTextNode(source.label));header.append(name,el('span','coverage-count',number(source.eventCount)));item.append(header);
      const status=source.status==='ok'?'CAPTURED':source.status==='partial'?'PARTIAL CAPTURE':'UNAVAILABLE';
      item.append(el('div',`coverage-status ${source.status}`,`${source.status==='ok'?'✓':source.status==='partial'?'◐':'—'} ${status}`));
      if(source.notes.length){const details=el('details');details.append(el('summary','',`${source.notes.length} coverage note${source.notes.length===1?'':'s'}`));const list=el('ul');for(const note of source.notes) list.append(el('li','',str(note)));details.append(list);item.append(details);}
      $('coverage-list').append(item);
    }
    const ok=state.sources.filter(s=>s.status==='ok').length;
    const available=state.sources.filter(s=>s.eventCount>0).length;
    $('coverage-summary').textContent=`${available} sources captured · ${ok===state.sources.length?'all available sources complete':`${state.sources.length-ok} with coverage notes`}`;
    $('generated-at').textContent=timeLabel(safeTimestamp(state.data.generatedAt));
    const excluded=state.events.filter(e=>e.metadata?.developmentRelevant===false).length;
    $('dataset-size').textContent=excluded?`${number(excluded)} non-development records available under “All captured activity”.`:'Original messages and event bodies are available in the full record.';
  }
  function configureWorkstreams() {
    const keys=new Set(state.events.flatMap(e=>Array.isArray(e.workstreams)?e.workstreams:[]));
    for(const key of [...new Set([...Object.keys(WORKSTREAMS),...keys])]){
      const option=el('option','',WORKSTREAMS[key]||key);option.value=key;$('workstream-filter').append(option);
    }
  }
  function configureChapters() {
    const provided=Array.isArray(state.data.chapters)?state.data.chapters:[];
    state.chapters=provided.map((c,i)=>({...c,id:c.id||`chapter-${i}`,ms:safeTimestamp(c.timestamp)})).filter(c=>c.ms!==null).sort((a,b)=>a.ms-b.ms);
    if(!state.chapters.length){
      const days=new Map();
      for(const event of state.events){if(event.metadata?.developmentRelevant===false)continue;const date=dateFormat.format(event.ms);if(!days.has(date))days.set(date,{id:`day-${date}`,title:`${shortFormat.format(event.ms)} · Development`,ms:event.ms,timestamp:event.timestamp,description:'Events recorded on this day.'});}
      state.chapters=[...days.values()];
    }
    $('chapter-select').replaceChildren(el('option','','All chapters'));
    for(const chapter of state.chapters){const option=el('option','',`${shortFormat.format(chapter.ms)} · ${chapter.title}`);option.value=chapter.id;$('chapter-select').append(option);}
    $('chapter-list').replaceChildren();
    if(!state.chapters.length){$('chapter-list').append(el('p','chapter-empty','Chapters appear once the archive contains timestamped events.'));return;}
    // Every narrative chapter remains visible, including supervision and self-governed development.
    const shown=state.chapters;
    for(const chapter of shown){const button=el('button','chapter-card');button.type='button';button.dataset.chapter=chapter.id;button.title=str(chapter.description);const date=el('time','',shortFormat.format(chapter.ms));date.dateTime=chapter.timestamp;button.append(date,el('strong','',str(chapter.title)),el('span','chapter-number',String(state.chapters.indexOf(chapter)+1).padStart(2,'0')));button.addEventListener('click',()=>jumpChapter(chapter));$('chapter-list').append(button);}
  }
  function jumpChapter(chapter) {
    if(!state.filtered.length)return;
    pause();
    if(state.playbackMode==='story'){
      const i=state.episodes.findIndex(e=>e.chapter.id===chapter.id);
      if(i>=0){state.position=state.episodes[i].start;renderNarrative();selectIndex(indexAtPosition(state.position),{reveal:true,announce:true,keepPosition:true});return;}
    }
    const evidence=Array.isArray(chapter.evidenceIds)?chapter.evidenceIds:[];
    let index=state.filtered.findIndex(e=>evidence.includes(e.id));if(index<0)index=nearestIndex(chapter.ms);
    selectIndex(index,{reveal:true,announce:true});
  }
  function nearestIndex(ms) {
    let lo=0,hi=state.filtered.length;
    while(lo<hi){const mid=(lo+hi)>>1;if(state.filtered[mid].ms<ms)lo=mid+1;else hi=mid;}
    return clamp(lo,0,state.filtered.length-1);
  }
  function applyFilters() {
    pause();const oldId=state.filtered[state.selected]?.id;
    state.filtered=state.events.filter(event=>{
      if(!state.enabled.has(event.source)||(!state.includeAll&&event.metadata?.developmentRelevant===false))return false;
      if(state.workstream&&!(Array.isArray(event.workstreams)&&event.workstreams.includes(state.workstream)))return false;
      if(!state.search)return true;
      let search=state.searchCache.get(event.id);
      if(search===undefined){search=[event.title,event.body,event.actor,event.kind,...(Array.isArray(event.tags)?event.tags:[])].map(str).join(' ').toLowerCase();state.searchCache.set(event.id,search);}
      return state.search.split(/\s+/).every(word=>search.includes(word));
    });
    state.page=0;state.min=state.filtered[0]?.ms||0;state.max=state.filtered.at(-1)?.ms||state.min;
    state.engine.configure(state.filtered.length,state.dwell);state.duration=state.engine.snapshot().duration;state.eventProgress=0;
    buildStory();
    let index=state.filtered.findIndex(e=>e.id===oldId);if(index<0)index=state.filtered.length?0:-1;
    state.position=0;state.episode=-1;if(state.playbackMode==='story'&&state.filtered.length)index=indexAtPosition(0);
    state.selected=-1;
    for(const button of $('source-legend').querySelectorAll('button'))button.setAttribute('aria-pressed',String(state.enabled.has(button.dataset.source)));
    for(const button of $('archive-filters').querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.source==='all'?state.enabled.size===state.sources.length:state.enabled.size===1&&state.enabled.has(button.dataset.source)));
    $('result-count').textContent=`${number(state.filtered.length)} ${state.includeAll?'captured':'development'} events`;
    $('scene-empty').hidden=state.filtered.length>0;
    for(const id of ['play-button','scrubber','restart-button'])$(id).disabled=!state.filtered.length;
    $('axis-start').textContent=state.min?shortFormat.format(state.min):'—';$('axis-end').textContent=state.max?shortFormat.format(state.max):'—';
    renderNarrative();rebuildScene();selectIndex(index,{reveal:false});renderList();renderConnections();
  }
  function buildStory() {
    const ids=new Map(state.filtered.map((e,i)=>[e.id,i]));let start=0;
    state.episodes=state.chapters.map(chapter=>{
      const narration=chapter.narration||{heading:chapter.title,paragraphs:[chapter.description],view:'activity'};
      const indices=(chapter.evidenceIds||[]).map(id=>ids.get(id)).filter(i=>i!==undefined);
      const words=(narration.paragraphs||[]).join(' ').split(/\s+/).length;
      const duration=Math.max(18000,words/2.9*1000);
      const episode={chapter,narration,indices:indices.length?indices:[nearestIndex(chapter.ms)],start,duration};start+=duration;return episode;
    });
    if(state.playbackMode==='story')state.duration=start;
    $('narrative-stage').hidden=state.playbackMode!=='story'||!state.filtered.length;$('event-dwell').disabled=state.playbackMode==='story';
  }
  function episodeAt(position) {return state.episodes.findIndex((episode,i)=>position<episode.start+episode.duration||i===state.episodes.length-1);}
  function indexAtPosition(position) {
    if(state.playbackMode!=='story')return clamp(Math.floor(position/state.dwell),0,state.filtered.length-1);
    const episode=state.episodes[episodeAt(position)];if(!episode)return 0;
    const progress=clamp((position-episode.start)/episode.duration,0,.999999);
    return episode.indices[Math.floor(progress*episode.indices.length)]??0;
  }
  function renderNarrative() {
    if(state.playbackMode!=='story'||!state.filtered.length){state.episode=-1;return;}
    const index=episodeAt(state.position),episode=state.episodes[index];if(!episode)return;
    const progress=clamp((state.position-episode.start)/episode.duration,0,1);$('narrative-progress').style.width=`${progress*100}%`;
    if(index===state.episode)return;state.episode=index;
    $('narrative-number').textContent=String(index+1).padStart(2,'0');$('narrative-heading').textContent=episode.narration.heading;
    $('narrative-date').textContent=`${timeLabel(episode.chapter.ms)} · ${index+1} / ${state.episodes.length}`;
    $('narrative-body').replaceChildren(...(episode.narration.paragraphs||[]).map(p=>el('p','',p)));
    $('narrative-evidence').replaceChildren();
    for(const id of episode.chapter.evidenceIds||[]){const event=state.eventById.get(id);if(!event)continue;const b=el('button','',`${sourceDef(event.source).label} · ${clip(readable(event.title),75)}`);b.type='button';b.addEventListener('click',()=>{pause();openEvent(event);});$('narrative-evidence').append(b);}
    switchView(episode.narration.view||'activity');
  }
  function selectIndex(index,{reveal=false,announce=false,keepPosition=false,render=true}={}) {
    if(!state.filtered.length)renderChatMedia({metadata:{}},$('focus-media'),$('focus-reactions'));
    if(!state.filtered.length){clearTimeout(state.focusTimer);state.focusToken++;document.querySelector('.event-focus').dataset.app='docs';$('source-app-name').textContent='Archive';$('source-app-context').textContent='No matching records';$('source-chat-context').replaceChildren();$('source-thread-context').replaceChildren();state.selected=-1;state.position=0;state.now=0;$('focus-title').textContent='No events in this view.';$('focus-date').textContent='Adjust the archive filters to continue.';$('focus-body').textContent='All captured sources remain available in the coverage panel.';$('focus-source').textContent='ARCHIVE';$('focus-position').textContent='000 / 000';$('focus-byline').replaceChildren();$('focus-kind').textContent='NO MATCHING RECORDS';$('read-event').disabled=true;$('focus-prev').disabled=true;$('focus-next').disabled=true;updateTransport();draw();return;}
    index=clamp(index,0,state.filtered.length-1);const changed=state.selected!==index;state.selected=index;
    if(!keepPosition){
      if(state.playbackMode==='all'){const snapshot=state.engine.seek(index);state.position=snapshot.position;state.eventProgress=0;}
      else {const episode=state.episodes.find(e=>e.indices.includes(index))||state.episodes[state.episode]||state.episodes[0];state.position=episode?.start||0;renderNarrative();}
    }
    const event=state.filtered[index];state.now=event.ms;
    if(changed){
      const source=sourceDef(event.source);document.querySelector('.event-focus').style.setProperty('--focus-color',source.color);
      $('focus-source').textContent=source.label;$('focus-position').textContent=`${number(index+1).padStart(3,'0')} / ${number(state.filtered.length)}`;
      $('focus-date').textContent=timeLabel(event.ms);$('focus-title').textContent=readable(event.title)||'Untitled record';byline($('focus-byline'),event);
      $('focus-body').textContent=chatBody(event);renderSourceApp(event);if(state.playing&&state.speed<=4&&!reducedMotion.matches)$('focus-body').animate([{opacity:.25,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],{duration:140,easing:'ease-out'});$('focus-kind').textContent=str(event.kind).replace(/[_-]/g,' ').toUpperCase()||'EVENT';$('read-event').disabled=false;
      $('focus-prev').disabled=index===0;$('focus-next').disabled=index===state.filtered.length-1;
      for(const row of $('event-list').querySelectorAll('.event-row')){const selected=row.dataset.event===event.id;row.classList.toggle('selected',selected);row.setAttribute('aria-current',selected?'true':'false');}
      if(announce)$('announcer').textContent=`${source.label}. ${event.title}. ${timeLabel(event.ms)}.`;
      updateChapter();
    }
    if(reveal){state.page=Math.floor(index/PAGE_SIZE);renderList();}
    if(render){updateTransport();draw();}
  }
  function updateChapter() {
    const chapter=state.chapters.filter(c=>c.ms<=state.now).at(-1);
    for(const card of $('chapter-list').querySelectorAll('button'))card.classList.toggle('active',card.dataset.chapter===chapter?.id);
    $('chapter-select').value=chapter?.id||'';
  }
  function updateTransport() {
    const progress=state.duration?state.position/state.duration:0;$('scrubber').value=String(Math.round(progress*10000));$('scrubber').style.setProperty('--progress',`${progress*100}%`);
    $('play-time').textContent=`${durationLabel(state.position)} / ${durationLabel(state.duration)}`;
    $('playhead-time').textContent=state.now?`${shortFormat.format(state.now)} · ${timeFormat.format(state.now)} COT`:'—';
    $('play-icon').textContent=state.playing?'Ⅱ':'▶';$('play-button').setAttribute('aria-label',state.playing?'Pause development history':'Play development history');
    $('play-caption').textContent=state.playing?(state.playbackMode==='story'?'The narrated build':'Every record, in order'):'Play the build';
    $('compression-label').textContent=state.playbackMode==='story'?`CHAPTER ${Math.max(1,state.episode+1)} / ${state.episodes.length} · AUTHORED NARRATION`:`RECORD ${number(Math.max(0,state.selected+1))} / ${number(state.filtered.length)} · 0 SKIPPED BY PLAYBACK`;
    $('scrubber').setAttribute('aria-valuetext',state.now?`${Math.round(progress*100)} percent. ${timeLabel(state.now)}`:'No events');
  }
  function pause() {state.playing=false;state.previousFrame=0;if(state.raf){cancelAnimationFrame(state.raf);state.raf=0;}updateTransport();draw();}
  function play() {
    if(!state.filtered.length)return;
    if(state.position>=state.duration||state.engine.finished){state.position=0;state.engine.configure(state.filtered.length,state.dwell);state.selected=-1;state.episode=-1;renderNarrative();selectIndex(indexAtPosition(0),{keepPosition:true});}
    state.playing=true;state.previousFrame=0;updateTransport();state.raf=requestAnimationFrame(tick);
  }
  function tick(time) {
    if(!state.playing)return;
    const delta=state.previousFrame?Math.min(time-state.previousFrame,100):0;state.previousFrame=time;
    let finished;
    if(state.playbackMode==='all'){
      const snapshot=state.engine.advance(delta,state.speed);state.position=snapshot.position;state.eventProgress=snapshot.progress;finished=snapshot.finished;
      selectIndex(snapshot.index,{keepPosition:true,render:false});
    }else {
      state.position=Math.min(state.duration,state.position+delta*state.speed);renderNarrative();
      const index=indexAtPosition(state.position),episode=state.episodes[state.episode];
      state.eventProgress=episode?((state.position-episode.start)/episode.duration*episode.indices.length)%1:0;
      selectIndex(index,{keepPosition:true,render:false});finished=state.position>=state.duration;
    }
    updateTransport();draw(time);
    if(finished){pause();renderConnections();return;}
    state.raf=requestAnimationFrame(tick);
  }
  function renderList() {
    const start=state.page*PAGE_SIZE, end=Math.min(start+PAGE_SIZE,state.filtered.length);const list=$('event-list');list.replaceChildren();
    if(!state.filtered.length)list.append(el('div','archive-empty',state.events.length?'No records match your search and source filters. Try clearing the search or enabling another source.':'The archive has no events yet. Run the rebuild script and refresh this page.'));
    const fragment=document.createDocumentFragment();
    for(let i=start;i<end;i++){
      const event=state.filtered[i],source=sourceDef(event.source);const button=el('button',`event-row${i===state.selected?' selected':''}`);button.type='button';button.dataset.event=event.id;button.style.setProperty('--source-color',source.color);button.setAttribute('aria-current',i===state.selected?'true':'false');button.setAttribute('aria-label',`${source.label}, ${event.title}, ${timeLabel(event.ms)}`);
      const date=el('time','',shortFormat.format(event.ms));date.dateTime=event.timestamp;date.append(el('span','',`${timeFormat.format(event.ms)} COT`));
      const sourceNode=el('span','row-source');sourceNode.append(dot(event.source),document.createTextNode(source.label));
      const content=el('span','row-content');content.dataset.source=source.label;content.append(el('strong','',readable(event.title)||'Untitled record'),el('span','',`${str(event.actor)||'Unattributed'} · ${str(event.kind).replace(/[_-]/g,' ')}`));
      button.append(date,sourceNode,content,el('span','row-arrow','↗'));button.addEventListener('click',()=>{pause();selectIndex(i,{announce:true});openEvent(event);});fragment.append(button);
    }
    list.append(fragment);$('page-label').textContent=state.filtered.length?`${number(start+1)}–${number(end)} of ${number(state.filtered.length)}`:'0 records';
    $('page-prev').disabled=state.page===0;$('page-next').disabled=end>=state.filtered.length;
  }
  async function fullBody(event) {
    if(!event.bodyRef)return visibleBody(event);
    const shard=str(event.bodyRef);
    if(!/^[A-Za-z0-9_-]+(?:\.js)?$/.test(shard))throw new Error('This record has an invalid body shard reference.');
    window.DEV_HISTORY_BODY_SHARDS=window.DEV_HISTORY_BODY_SHARDS||{};
    if(!window.DEV_HISTORY_BODY_SHARDS[shard]){
      let promise=state.bodyLoads.get(shard);
      if(!promise){promise=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src=`data/bodies/${encodeURIComponent(shard.endsWith('.js')?shard:shard+'.js')}`;script.onload=()=>resolve();script.onerror=()=>{state.bodyLoads.delete(shard);script.remove();reject(new Error('The full event body could not be loaded.'));};document.head.append(script);});state.bodyLoads.set(shard,promise);}
      await promise;
    }
    const body=window.DEV_HISTORY_BODY_SHARDS[shard]?.[event.id];
    if(body===undefined)throw new Error('The body shard does not contain this event.');
    return str(body);
  }
  async function openEvent(event=state.filtered[state.selected]) {
    if(!event)return;pause();const source=sourceDef(event.source);const dialog=$('event-dialog');dialog.style.setProperty('--focus-color',source.color);
    $('dialog-source').textContent=source.label;$('dialog-date').textContent=timeLabel(event.ms);$('dialog-title').textContent=str(event.title)||'Untitled record';byline($('dialog-byline'),event);
    renderChatMedia(event,$('dialog-media'),$('dialog-reactions'));
    $('dialog-body').classList.remove('loading');$('dialog-body').removeAttribute('aria-busy');$('dialog-body').textContent=visibleBody(event);$('dialog-id').textContent=`RECORD ${event.id}`;
    $('dialog-tags').replaceChildren();for(const tag of [...(Array.isArray(event.tags)?event.tags:[]),...(Array.isArray(event.workstreams)?event.workstreams.map(s=>WORKSTREAMS[s]||s):[])])$('dialog-tags').append(el('span','',str(tag)));
    const metadata={timestamp:event.timestamp,source:event.source,kind:event.kind,threadId:event.threadId||null,...event.metadata};$('dialog-metadata').textContent=JSON.stringify(metadata,null,2);$('event-metadata').open=false;
    const url=safeUrl(event.url);$('dialog-url').hidden=!url;if(url)$('dialog-url').href=url;
    if(!dialog.open)dialog.showModal();dialog.scrollTop=0;
    const request=++state.bodyRequest;
    if(event.bodyRef){$('dialog-body').classList.add('loading');$('dialog-body').setAttribute('aria-busy','true');$('dialog-body').textContent='Loading the complete original event…';
      try{const body=await fullBody(event);if(request!==state.bodyRequest)return;$('dialog-body').textContent=body;$('announcer').textContent='Full event body loaded.';}
      catch(error){if(request!==state.bodyRequest)return;$('dialog-body').textContent=`${visibleBody(event)}\n\n[The full body could not be loaded. Rebuild the archive and refresh to restore missing body shards.]`;$('announcer').textContent='Full body unavailable. The preview is shown.';console.error(error);}
      finally{if(request===state.bodyRequest){$('dialog-body').classList.remove('loading');$('dialog-body').removeAttribute('aria-busy');}}
    }
  }
  function resize() {
    const rect=$('canvas-wrap').getBoundingClientRect();state.width=Math.max(1,rect.width);state.height=Math.max(1,rect.height);state.dpr=Math.min(devicePixelRatio||1,2);
    canvas.width=Math.round(state.width*state.dpr);canvas.height=Math.round(state.height*state.dpr);ctx.setTransform(state.dpr,0,0,state.dpr,0,0);rebuildScene();draw();
  }
  function plotX(ms) {return state.plotLeft+(state.max===state.min ? .5 : (ms-state.min)/(state.max-state.min))*(state.width-state.plotLeft-state.plotRight);}
  function rebuildScene() {
    const base=state.base;base.width=Math.round(state.width*state.dpr);base.height=Math.round(state.height*state.dpr);const b=base.getContext('2d');b.setTransform(state.dpr,0,0,state.dpr,0,0);b.clearRect(0,0,state.width,state.height);
    const w=state.width,h=state.height;
    // Deterministic stars do not make the captured data look like invented events.
    for(let i=0;i<80;i++){const x=((i*137.37+19)%997)/997*w,y=((i*97.53+33)%991)/991*h;b.fillStyle=i%7===0?'#7995ab52':'#7995ab24';b.fillRect(x,y,i%7===0?1.3:1,i%7===0?1.3:1);}
    if(state.view==='landscape')return;
    const visibleSources=state.sources;state.laneY=visibleSources.map((_,i)=>26+i*(h-64)/Math.max(1,visibleSources.length-1));
    const plotW=Math.max(1,w-state.plotLeft-state.plotRight),bins=Math.ceil(plotW);const counts=visibleSources.map(()=>new Uint32Array(bins));
    const sourceIndices=new Map(visibleSources.map((s,i)=>[s.id,i]));
    for(const event of state.filtered){const lane=sourceIndices.get(event.source);if(lane===undefined)continue;const bin=clamp(Math.floor(plotX(event.ms)-state.plotLeft),0,bins-1);counts[lane][bin]++;}
    b.lineWidth=1;b.strokeStyle='#586d8625';b.setLineDash([2,7]);for(let i=0;i<=4;i++){const x=state.plotLeft+plotW*i/4;b.beginPath();b.moveTo(x,5);b.lineTo(x,h-23);b.stroke();}b.setLineDash([]);
    for(let lane=0;lane<visibleSources.length;lane++){
      const source=visibleSources[lane],y=state.laneY[lane],active=state.enabled.has(source.id);b.globalAlpha=active?1:.18;b.font='11px '+getComputedStyle(document.body).getPropertyValue('--mono');b.fillStyle=source.color;b.fillText(source.label.toUpperCase(),0,y+3);
      b.strokeStyle=source.color+'28';b.beginPath();b.moveTo(state.plotLeft,y);b.lineTo(w-state.plotRight,y);b.stroke();
      const points=counts[lane];b.beginPath();b.moveTo(state.plotLeft,y);
      for(let x=0;x<bins;x++){const activity=points[x];const amplitude=activity?Math.min(20,3+Math.log2(activity+1)*3):0;b.lineTo(state.plotLeft+x,y-amplitude);}
      b.lineTo(w-state.plotRight,y);b.closePath();const gradient=b.createLinearGradient(0,y-25,0,y);gradient.addColorStop(0,source.color+'45');gradient.addColorStop(1,source.color+'02');b.fillStyle=gradient;b.fill();
      for(let x=0;x<bins;x++)if(points[x]){b.fillStyle=source.color+(points[x]>3?'ba':'68');b.beginPath();b.arc(state.plotLeft+x,y,Math.min(3.8,.8+Math.log2(points[x]+1)*.45),0,Math.PI*2);b.fill();}
    }b.globalAlpha=1;
  }
  function draw(time=0) {
    if(!state.width)return;ctx.clearRect(0,0,state.width,state.height);ctx.drawImage(state.base,0,0,state.width,state.height);
    if(state.view!=='activity'){
      const result=state.graph?.render({view:state.view,now:state.now,selectedEvent:state.filtered[state.selected],eventCursor:state.selected,playing:state.playing,progress:state.eventProgress,reducedMotion:reducedMotion.matches,sessionFilter:state.sessionFilter,flowId:state.flowId,sourceFilter:[...state.enabled],allLinks:state.allLinks});
      if(result?.caption)$('landscape-caption').textContent=result.caption;return;
    }
    if(state.graph)state.graph.lastState={view:'activity'};
    if(!state.filtered.length||state.selected<0)return;const event=state.filtered[state.selected],x=plotX(state.now||event.ms);
    const gradient=ctx.createLinearGradient(x-32,0,x+1,0);gradient.addColorStop(0,'#c7ff5e00');gradient.addColorStop(1,'#c7ff5e09');ctx.fillStyle=gradient;ctx.fillRect(x-32,3,33,state.height-24);
    ctx.strokeStyle='#c7ff5e80';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,3);ctx.lineTo(x,state.height-23);ctx.stroke();
    ctx.fillStyle='#c7ff5e';ctx.beginPath();ctx.moveTo(x-3,3);ctx.lineTo(x+3,3);ctx.lineTo(x,8);ctx.fill();
    const source=sourceDef(event.source),lane=state.sources.findIndex(s=>s.id===event.source),y=state.laneY[lane];
    if(y!==undefined){const eventX=plotX(event.ms);const radius=state.playing&&!reducedMotion.matches?9+Math.sin(time/260)*2:10;ctx.strokeStyle=source.color+'60';ctx.beginPath();ctx.arc(eventX,y,radius,0,Math.PI*2);ctx.stroke();ctx.shadowBlur=15;ctx.shadowColor=source.color;ctx.fillStyle=source.color;ctx.beginPath();ctx.arc(eventX,y,3.7,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;}
  }

  function renderConnections() {
    const container=$('connection-list');container.replaceChildren();const edges=Array.isArray(state.data?.landscape?.edges)?state.data.landscape.edges:[];
    const nodes=new Map((state.data?.landscape?.nodes||[]).map(n=>[n.id,n]));
    for(const node of nodes.values()){
      const ms=safeTimestamp(node.firstTimestamp)??0,active=ms<=(state.now||state.events[0]?.ms||0);const button=el('button','connection-button');button.type='button';
      button.append(document.createTextNode(node.label||node.id),el('span','',`${str(node.description)||'Captured system component'} · ${active?'active':'appears'} ${ms?shortFormat.format(ms):'undated'}`));
      button.addEventListener('click',()=>openEvidence(node.evidenceIds||[],ms));container.append(button);
    }
    for(const edge of edges){
      const ms=safeTimestamp(edge.firstTimestamp)??0,active=ms<=(state.now||state.events[0]?.ms||0);const button=el('button','connection-button');button.type='button';button.disabled=!active;
      button.append(document.createTextNode(`${nodes.get(edge.from)?.label||edge.from} → ${nodes.get(edge.to)?.label||edge.to}`),el('span','',`${str(edge.label)} · ${ms?shortFormat.format(ms):'undated'}${active?'':' · appears later'} · ${str(edge.basis)||'Captured evidence'}`));
      const ids=Array.isArray(edge.evidenceIds)?edge.evidenceIds:[];button.title=ids.length?`${ids.length} evidence record${ids.length===1?'':'s'}`:'No linked evidence';button.addEventListener('click',()=>openEvidence(ids,ms));container.append(button);
    }
    if(!edges.length)container.append(el('p','subtle','No connections were captured.'));
  }
  function openEvidence(ids,ms) {
    const event=ids.map(id=>state.eventById.get(id)).find(Boolean);
    if(event){const index=state.filtered.findIndex(e=>e.id===event.id);if(index>=0)selectIndex(index,{reveal:true});openEvent(event);}
    else if(state.filtered.length){pause();selectIndex(nearestIndex(ms),{reveal:true,announce:true});}
  }
  function switchView(view) {
    state.view=view;state.connectionStamp='';
    for(const name of ['activity','landscape','agents','flows','infrastructure'])$(`${name}-view`).setAttribute('aria-pressed',String(view===name));
    const graph=view!=='activity';$('scene-instruction').hidden=graph;$('canvas-wrap').classList.toggle('landscape-mode',graph);$('source-legend').hidden=graph;$('landscape-caption').hidden=!graph;
    $('landscape-evidence').hidden=view!=='landscape';$('landscape-links-label').hidden=view!=='landscape';$('scene-tools').hidden=!graph;$('scene-tools').classList.toggle('compact-tools',!['agents','flows'].includes(view));
    for(const id of ['session-filter','session-filter-label'])$(id).hidden=view!=='agents';
    for(const id of ['flow-filter','flow-filter-label'])$(id).hidden=view!=='flows';
    const names={activity:'THE DEVELOPMENT SIGNAL',landscape:'THE SYSTEM, EVOLVING',agents:'PARALLEL CHATS & AGENT HANDOFFS',flows:'FLUJO · RECORDED EXECUTION GRAPHS',infrastructure:'MACHINES · BUILDS · DEPLOYMENTS'};
    $('scene-heading').textContent=names[view];$('scene-instruction').textContent=graph?'DRAG TO PAN · CTRL + SCROLL TO ZOOM · CLICK FOR EVIDENCE':'CLICK A SIGNAL TO EXPLORE ↗';
    canvas.setAttribute('aria-label',`${names[view]}. Timestamped evidence follows the shared clock. Select records in the archive or inspect graph nodes.`);resize();renderConnections();
  }
  function hitTest(x,y) {
    if(state.view!=='activity')return null;
    if(!state.filtered.length)return null;const ms=state.min+clamp((x-state.plotLeft)/(state.width-state.plotLeft-state.plotRight),0,1)*(state.max-state.min);const mid=nearestIndex(ms);let best=null,distance=24;
    for(let i=Math.max(0,mid-90);i<Math.min(state.filtered.length,mid+90);i++){
      const event=state.filtered[i],lane=state.sources.findIndex(s=>s.id===event.source),d=Math.hypot(plotX(event.ms)-x,(state.laneY[lane]||0)-y);if(d<distance){distance=d;best={event,index:i};}
    }return best;
  }
  function bind() {
    $('play-button').addEventListener('click',()=>state.playing?pause():play());$('restart-button').addEventListener('click',()=>{pause();selectIndex(0,{reveal:true,announce:true});});
    $('focus-prev').addEventListener('click',()=>{pause();selectIndex(state.selected-1,{reveal:true,announce:true});});$('focus-next').addEventListener('click',()=>{pause();selectIndex(state.selected+1,{reveal:true,announce:true});});
    $('read-event').addEventListener('click',()=>openEvent());$('close-dialog').addEventListener('click',()=>$('event-dialog').close());$('event-dialog').addEventListener('click',event=>{if(event.target===$('event-dialog')){const rect=event.target.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();}});
    $('scrubber').addEventListener('input',()=>{const value=Number($('scrubber').value);pause();state.position=value/10000*state.duration;const index=indexAtPosition(state.position);if(state.playbackMode==='all'){state.position=state.engine.seek(index).position;state.eventProgress=0;}renderNarrative();selectIndex(index,{keepPosition:true,announce:false});});$('scrubber').addEventListener('change',()=>{renderConnections();$('announcer').textContent=timeLabel(state.now);});
    $('playback-speed').addEventListener('change',()=>{state.speed=Number($('playback-speed').value);});$('playback-mode').addEventListener('change',()=>{state.playbackMode=$('playback-mode').value;applyFilters();});
    let debounce;$('event-search').addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(()=>{state.search=$('event-search').value.trim().toLowerCase();applyFilters();},180);});
    $('workstream-filter').addEventListener('change',()=>{state.workstream=$('workstream-filter').value;applyFilters();});$('include-all').addEventListener('change',()=>{state.includeAll=$('include-all').checked;applyFilters();});
    $('chapter-select').addEventListener('change',()=>{const chapter=state.chapters.find(c=>c.id===$('chapter-select').value);if(chapter)jumpChapter(chapter);});
    $('page-prev').addEventListener('click',()=>{state.page--;renderList();});$('page-next').addEventListener('click',()=>{state.page++;renderList();});
    for(const view of ['activity','landscape','agents','flows','infrastructure'])$(`${view}-view`).addEventListener('click',()=>switchView(view));
    $('event-dwell').addEventListener('change',()=>{state.dwell=Number($('event-dwell').value);applyFilters();});
    $('session-filter').addEventListener('change',()=>{state.sessionFilter=$('session-filter').value;draw();});
    $('flow-filter').addEventListener('change',()=>{state.flowId=$('flow-filter').value;draw();});
    $('reset-camera').addEventListener('click',()=>{state.graph?.fitView();});
    $('cinema-toggle').addEventListener('click',()=>{const active=document.body.classList.toggle('cinema-mode');$('cinema-toggle').setAttribute('aria-pressed',String(active));$('cinema-toggle').textContent=active?'Exit cinema':'Cinema';resize();});
    $('close-inspector').addEventListener('click',()=>{$('system-inspector').hidden=true;});
    $('landscape-all-links').addEventListener('change',()=>{state.allLinks=$('landscape-all-links').checked;draw();});
    canvas.addEventListener('pointermove',event=>{
      if(state.view!=='activity')return;
      const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,hit=hitTest(x,y);const tip=$('canvas-tooltip');tip.hidden=!hit;canvas.style.cursor=hit?'pointer':'crosshair';if(!hit)return;
      tip.textContent=hit.event?`${sourceDef(hit.event.source).label} · ${clip(str(hit.event.title),100)} · ${timeFormat.format(hit.event.ms)}`:hit.node?`${hit.node.label} · ${hit.node.active?'active':'appears'} ${shortFormat.format(hit.node.ms)} · ${clip(str(hit.node.description),120)}`:`${hit.connection.edge.label} · ${hit.connection.active?'open evidence':'appears later'}`;
      tip.style.left=`${clamp(x+12,5,state.width-Math.min(260,state.width-10))}px`;tip.style.top=`${clamp(y+15,5,state.height-65)}px`;
    });canvas.addEventListener('pointerleave',()=>{$('canvas-tooltip').hidden=true;});
    canvas.addEventListener('click',event=>{if(state.view!=='activity')return;const rect=canvas.getBoundingClientRect(),hit=hitTest(event.clientX-rect.left,event.clientY-rect.top);if(!hit)return;pause();if(hit.event)selectIndex(hit.index,{reveal:true,announce:true});else if(hit.node){openEvidence(hit.node.evidenceIds||[],hit.node.ms);}else if(hit.connection)openEvidence(hit.connection.edge.evidenceIds||[],safeTimestamp(hit.connection.edge.firstTimestamp)||0);});
    document.addEventListener('keydown',event=>{
      const tag=event.target.tagName;if(event.key==='Escape'&&document.body.classList.contains('cinema-mode')){document.body.classList.remove('cinema-mode');$('cinema-toggle').setAttribute('aria-pressed','false');$('cinema-toggle').textContent='Cinema';resize();return;}
      if(['INPUT','TEXTAREA','SELECT','BUTTON','A','SUMMARY'].includes(tag)||event.ctrlKey||event.metaKey||event.altKey||$('event-dialog').open)return;
      if(event.code==='Space'){event.preventDefault();state.playing?pause():play();}
      else if(event.key==='ArrowRight'){event.preventDefault();pause();selectIndex(state.selected+1,{reveal:true,announce:true});}
      else if(event.key==='ArrowLeft'){event.preventDefault();pause();selectIndex(state.selected-1,{reveal:true,announce:true});}
      else if(event.key==='/'){event.preventDefault();$('event-search').focus();}
    });
    document.addEventListener('visibilitychange',()=>{if(document.hidden&&state.playing)pause();});
    new ResizeObserver(resize).observe($('canvas-wrap'));
  }
  async function load() {
    try {
      $('load-state').className='load-state visible';$('load-state').textContent='Opening the captured development history…';
      let data=window.DEV_HISTORY;
      if(!data&&window.DEV_HISTORY_READY){try{data=await window.DEV_HISTORY_READY;}catch(error){console.warn('Compressed archive unavailable; trying JSON fallback.',error);}}
      if(!data){const response=await fetch('data/history.json',{cache:'no-store'});if(!response.ok)throw new Error(`History returned HTTP ${response.status}`);data=await response.json();}
      if(!data||!Array.isArray(data.events))throw new Error('The history dataset does not contain an events array.');
      state.data=data;timezone=str(data.project?.timezone)||'America/Bogota';formatters();
      state.events=data.events.map((event,i)=>({...event,id:str(event.id)||`record-${i}`,source:str(event.source)||'docs',ms:safeTimestamp(event.timestamp)})).filter(e=>e.ms!==null).sort((a,b)=>a.ms-b.ms||a.id.localeCompare(b.id));
      state.eventById=new Map(state.events.map(e=>[e.id,e]));
      const invalid=data.events.length-state.events.length;
      $('total-events').textContent=number(state.events.filter(e=>e.metadata?.developmentRelevant!==false).length);
      const development=state.events.filter(e=>e.metadata?.developmentRelevant!==false);
      if(development.length)$('date-range').textContent=`${dateFormat.format(development[0].ms)} → ${dateFormat.format(development.at(-1).ms)}`;
      $('project-description').textContent=`${str(data.project?.name)||'SAVIA'} · One shared clock for the messages, agents, code, and machines behind the build.`;
      const repo=safeUrl(data.project?.repo?.startsWith('http')?data.project.repo:`https://github.com/${data.project?.repo||''}`);if(repo&&data.project?.repo){$('repo-link').href=repo;$('repo-link').target='_blank';$('repo-link').rel='noopener noreferrer';$('repo-link').replaceChildren(document.createTextNode('Project repository'),el('span','','↗'));}
      configureSources();renderCoverage();configureWorkstreams();configureChapters();configureSystem();bind();applyFilters();resize();$('load-state').className='load-state';
      if(invalid){$('load-state').className='load-state visible';$('load-state').textContent=`${number(invalid)} records have no valid timestamp and are omitted from playback. Source coverage notes preserve collection limitations.`;}
      if(!state.events.length){$('load-state').className='load-state visible';$('load-state').textContent='The archive is empty. Run python scripts/build_dev_history.py, then refresh this page.';}
      if(!data.landscape?.nodes?.length){$('landscape-view').disabled=true;$('landscape-view').title='The rebuild did not capture a system landscape.';}
    }catch(error){
      formatters();$('load-state').className='load-state visible error';$('load-state').textContent='The history dataset could not be loaded. Run python scripts/build_dev_history.py, then open this page again. A local preview is available with python scripts/serve_dev_history.py.';
      $('focus-title').textContent='The archive is waiting.';$('focus-body').textContent='The interface is ready. The rebuild script writes timestamped source records into data/history-data.js and data/history.json.';$('date-range').textContent='No dataset loaded';$('coverage-summary').textContent='Source coverage unavailable';$('total-events').textContent='0';$('result-count').textContent='0 events';$('scene-empty').hidden=false;console.error('Development history:',error);
    }
  }
  load();
})();
