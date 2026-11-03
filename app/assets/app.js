'use strict';
const KEY=document.querySelector('meta[name="mochi-key"]').content;
const el=id=>document.getElementById(id);
const mode=()=>document.querySelector('input[name="mode"]:checked').value;
let busy=false,qualitiesBusy=false, lastState='ready', restoredPending=false;
let transcriptCache=null, transcriptFolder='';
let updatePhase='idle', updateTarget='', updateChecking=false, upgradeWatching=false;
const updating=()=>['downloading','staging','restarting'].includes(updatePhase);
async function api(route,body){
  const options={headers:{'X-Mochi-Key':KEY}};
  if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body)}
  const response=await fetch(route,options);
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'Something went wrong.');
  return data;
}
function selectedMode(){
  document.querySelectorAll('.choice').forEach(node=>node.classList.toggle('is-selected',node.querySelector('input').checked));
  el('video-options').classList.toggle('hidden',mode()!=='video');
  el('audio-options').classList.toggle('hidden',mode()!=='audio');
  const speech=mode()==='subtitles'||mode()==='transcript';
  el('speech-options').classList.toggle('hidden',!speech);
  el('language-options').classList.toggle('hidden',!speech);
}
document.querySelectorAll('[name="mode"]').forEach(node=>node.addEventListener('change',selectedMode));
// Each utility has one working control in the responsive sidebar.
document.querySelectorAll('[data-open-downloads]').forEach(button=>button.addEventListener('click',async()=>{
  try{await api('/api/open-downloads',{})}catch(e){note(e.message)}
}));
el('paste').addEventListener('click',async()=>{
  try{el('url').value=(await navigator.clipboard.readText()).trim();el('url').focus()}catch(e){el('url').focus();note('Paste using Ctrl+V (or Cmd+V) in the link box.','error')}
});
function note(message,state='error'){
  el('activity').classList.remove('hidden');el('status-heading').textContent=state==='error'?'A tiny hiccup':'Working on it';
  el('status-text').textContent=message;el('percent').textContent='';el('results').classList.add('hidden');
  el('cancel').classList.add('hidden');el('again').classList.remove('hidden');el('repair').disabled=busy;
}
function optionData(){return{mode:mode(),height:el('height').value==='best'?'best':Number(el('height').value),audio_format:el('audio-format').value,speech_quality:el('speech-quality').value,language:el('language').value}};
el('find-qualities').addEventListener('click',async()=>{
  if(qualitiesBusy||busy||updating())return;
  qualitiesBusy=true;el('find-qualities').disabled=true;el('find-qualities').textContent='Checking…';
  try{
    const info=await api('/api/qualities',{url:el('url').value.trim()});
    const s=el('height');s.replaceChildren();
    s.add(new Option('✨ Highest available','best'));
    for(const height of info.heights)s.add(new Option(`${height}p (up to)`,String(height)));
    if(!info.heights.length)note('No separate resolution list was found. Highest available still works.','hint');
  }catch(e){note(e.message,'error')}
  finally{qualitiesBusy=false;el('find-qualities').disabled=false;el('find-qualities').textContent='See options'}
});
el('start').addEventListener('click',async()=>{
  if(busy||updating())return;
  try{
    await api('/api/start',{url:el('url').value.trim(),options:optionData()});
    resetTranscript();
    busy=true;el('repair').disabled=true;el('activity').classList.remove('hidden');el('activity').scrollIntoView({behavior:'smooth',block:'nearest'});
    await refresh();
  }catch(e){note(e.message,'error')}
});
el('cancel').addEventListener('click',async()=>{el('cancel').disabled=true;try{await api('/api/cancel',{});el('status-text').textContent='Stopping safely…'}catch(e){note(e.message)}});
el('again').addEventListener('click',()=>{el('activity').classList.add('hidden');el('url').focus()});
el('repair').addEventListener('click',async()=>{if(busy||updating())return;el('repair').disabled=true;try{await api('/api/repair',{});busy=true;await refresh()}catch(e){busy=false;note(e.message)}finally{el('repair').disabled=busy}});
el('open-folder').addEventListener('click',async()=>{try{await api('/api/open',{})}catch(e){note(e.message)}});

// The text stays local until the user explicitly copies it or uploads the TXT.
function resetTranscript(){
  transcriptCache=null;transcriptFolder='';
  el('transcript-preview').classList.add('hidden');el('transcript-text').value='';
  el('transcript-feedback').textContent='';
}
async function transcriptText(){
  if(transcriptCache!==null)return transcriptCache;
  const folder=transcriptFolder;
  const result=await api('/api/transcript');
  if(folder!==transcriptFolder)throw new Error('This result changed. Open the new transcript instead.');
  transcriptCache=result.text;
  return transcriptCache;
}
function showTranscript(text){
  el('transcript-text').value=text;
  el('transcript-preview').classList.remove('hidden');
  el('transcript-preview').scrollIntoView({behavior:'smooth',block:'nearest'});
}
el('open-transcript').addEventListener('click',async()=>{
  try{showTranscript(await transcriptText());el('transcript-feedback').textContent=''}
  catch(e){el('transcript-feedback').textContent=e.message}
});
el('close-transcript').addEventListener('click',()=>el('transcript-preview').classList.add('hidden'));
el('copy-transcript').addEventListener('click',async()=>{
  try{
    const text=await transcriptText();
    if(!navigator.clipboard||!navigator.clipboard.writeText)throw new Error('Clipboard unavailable');
    try{
      await navigator.clipboard.writeText(text);
      el('transcript-feedback').textContent='Copied! Paste into ChatGPT, Claude, or any AI.';
    }catch(e){
      showTranscript(text);el('transcript-text').focus();el('transcript-text').select();
      el('transcript-feedback').textContent='Clipboard blocked. Text selected: press Ctrl+C or Cmd+C instead.';
    }
  }catch(e){
    if(e.message==='Clipboard unavailable'){
      showTranscript(transcriptCache);el('transcript-text').focus();el('transcript-text').select();
      el('transcript-feedback').textContent='Select text and press Ctrl+C or Cmd+C, or upload the TXT file.';
    }else{
      el('transcript-feedback').textContent=e.message;
    }
  }
});
async function refresh(){
  try{
    const st=await api('/api/status');
    if(st.state==='ready'){
      busy=false;el('start').disabled=updating();el('repair').disabled=updating();
      return;
    }
    if(st.state==='interrupted' && st.pending && !restoredPending){
      restoredPending=true;
      el('url').value=st.pending.url;
      const opts=st.pending.options||{};
      const radio=document.querySelector('input[name="mode"][value="'+opts.mode+'"]');
      if(radio)radio.checked=true;
      for(const [id,value] of [['audio-format',opts.audio_format],['speech-quality',opts.speech_quality],['language',opts.language]]){
        if(value!=null && [...el(id).options].some(opt=>opt.value===String(value)))el(id).value=String(value);
      }
      selectedMode();
    }
    lastState=st.state;
    el('activity').classList.remove('hidden');
    el('status-heading').textContent=st.state==='done'?'A little magic, completed!':st.state==='error'?'Almost! Let’s fix this':st.state==='cancelled'?'Cancelled':st.state==='repaired'?'Mochi is ready again!':st.state==='repairing'?'Fixing your tools…':st.state==='interrupted'?'Ready to continue':'Making your video…';
    el('status-text').textContent=st.message;
    const pct=Number(st.percent)||0;el('percent').textContent=pct+'%';el('progress-fill').style.width=pct+'%';el('progress').setAttribute('aria-valuenow',String(pct));
    busy=st.state==='working'||st.state==='repairing';
    el('start').disabled=busy||updating();el('start').textContent=busy?'Working its magic…':'Make it happen ✦';
    el('cancel').classList.toggle('hidden',!busy);el('cancel').disabled=false;
    el('again').classList.toggle('hidden',busy);
    el('repair').disabled=busy||updating();el('repair').textContent=st.state==='repairing'?'🛠 Fixing…':'🛠 Fix my tools';
    const done=st.state==='done';el('results').classList.toggle('hidden',!done);
    const hasTranscript=done&&Array.isArray(st.files)&&st.files.includes('Transcript.txt');
    if(!hasTranscript||transcriptFolder!==st.folder){
      resetTranscript();
      if(hasTranscript)transcriptFolder=st.folder;
    }
    el('open-transcript').classList.toggle('hidden',!hasTranscript);
    el('copy-transcript').classList.toggle('hidden',!hasTranscript);
    if(done){const container=el('file-list');container.replaceChildren();for(const item of st.files){const span=document.createElement('span');span.textContent='📄 '+item;container.appendChild(span)}}
  }catch(err){if(busy){el('status-text').textContent='App connection was lost. Double-click Run Mochi Now to reconnect.';busy=false;el('start').disabled=false}}
}

function updateView(state){
  updatePhase=state.phase||'idle';
  if(state.latest)updateTarget=state.latest;
  const current=state.current||'unknown';
  const latest=state.latest||'';
  el('update-versions').textContent='Installed '+current+(latest?' · Latest '+latest:'');
  el('update-message').textContent=state.message||'Check the official GitHub release.';
  const canInstall=updatePhase==='available'&&!busy;
  el('install-update').classList.toggle('hidden',updatePhase!=='available');
  el('install-update').disabled=!canInstall;
  el('cancel-update').classList.toggle('hidden',!['downloading','staging'].includes(updatePhase));
  el('cancel-update').disabled=updatePhase==='restarting';
  el('check-update-again').disabled=updateChecking||updating();
  if(updating()&&Number.isFinite(state.percent))
    el('update-message').textContent=(state.message||'Updating…')+' '+state.percent+'%';
  if(updatePhase==='restarting'){
    el('update-message').textContent='Restarting Mochi. A fresh local browser tab should open. If it does not, use Run Mochi Now.';
    watchUpdateRestart();
  }
}
async function checkForUpdates(){
  const dialog=el('update-dialog');
  if(!dialog.open)dialog.showModal();
  if(updateChecking||updating())return;
  updateChecking=true;
  el('check-update-again').disabled=true;
  el('update-message').textContent='Checking the official Mochi release…';
  try{ updateView(await api('/api/update/check')); }
  catch(error){ el('update-message').textContent='Could not check updates. Try again when online.'; }
  finally{ updateChecking=false;el('check-update-again').disabled=updating(); }
}
document.querySelectorAll('[data-check-updates]').forEach(button=>button.addEventListener('click',checkForUpdates));
el('check-update-again').addEventListener('click',checkForUpdates);
el('close-updates').addEventListener('click',()=>el('update-dialog').close());
el('install-update').addEventListener('click',async()=>{
  if(updatePhase!=='available'||busy)return;
  el('install-update').disabled=true;
  try{
    await api('/api/update/start',{});
    updateView({phase:'downloading',message:'Downloading the verified ZIP…',percent:0});
  }catch(error){
    el('update-message').textContent=error.message||'Could not start the update.';
    el('install-update').disabled=false;
  }
});
el('cancel-update').addEventListener('click',async()=>{
  el('cancel-update').disabled=true;
  try{await api('/api/update/cancel',{});el('update-message').textContent='Cancelling safely…';}
  catch(error){el('update-message').textContent=error.message}
});
async function pollAppUpdate(){
  if(!updating())return;
  try{updateView(await api('/api/update/status'));}
  catch(error){
    if(updatePhase==='restarting')watchUpdateRestart();
    else el('update-message').textContent='Connection lost. Reopen Run Mochi Now to recover.';
  }
}
async function watchUpdateRestart(){
  if(upgradeWatching)return;
  upgradeWatching=true;
  // Old bookmarks can expire; the detached helper opens the NEW private URL.
  for(let attempt=0;attempt<35;attempt++){
    await new Promise(resolve=>setTimeout(resolve,1400));
    try{
      const status=await api('/api/update/status');
      if(status.phase==='updated'){
        location.reload();return;
      }
      if(['failed','rolled-back'].includes(status.phase)){
        updateView(status);upgradeWatching=false;return;
      }
    }catch(error){/* server may have changed its private loopback port */ }
  }
  el('update-message').textContent='Open Run Mochi Now if the new Mochi tab did not appear.';
  upgradeWatching=false;
}

selectedMode();refresh();setInterval(refresh,850);
setInterval(pollAppUpdate,1500);


