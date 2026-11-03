'use strict';
const KEY=document.querySelector('meta[name="mochi-key"]').content;
const el=id=>document.getElementById(id);
const mode=()=>document.querySelector('input[name="mode"]:checked').value;
let busy=false,qualitiesBusy=false, lastState='ready', restoredPending=false;
let transcriptCache=null, transcriptFolder='';
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
// Sidebar and header shortcuts share the same working actions.
document.querySelectorAll('[data-go-settings]').forEach(button=>button.addEventListener('click',()=>{
  el('finishing').scrollIntoView({behavior:'smooth',block:'center'});
}));
document.querySelectorAll('[data-repair]').forEach(button=>button.addEventListener('click',()=>el('repair').click()));
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
  if(qualitiesBusy||busy)return;
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
  if(busy)return;
  try{
    await api('/api/start',{url:el('url').value.trim(),options:optionData()});
    resetTranscript();
    busy=true;el('repair').disabled=true;el('activity').classList.remove('hidden');el('activity').scrollIntoView({behavior:'smooth',block:'nearest'});
    await refresh();
  }catch(e){note(e.message,'error')}
});
el('cancel').addEventListener('click',async()=>{el('cancel').disabled=true;try{await api('/api/cancel',{});el('status-text').textContent='Stopping safely…'}catch(e){note(e.message)}});
el('again').addEventListener('click',()=>{el('activity').classList.add('hidden');el('url').focus()});
el('repair').addEventListener('click',async()=>{if(busy)return;el('repair').disabled=true;try{await api('/api/repair',{});busy=true;await refresh()}catch(e){busy=false;note(e.message)}finally{el('repair').disabled=busy}});
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
    if(st.state==='ready'){busy=false;el('repair').disabled=false;return;}
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
    el('start').disabled=busy;el('start').textContent=busy?'Working its magic…':'Make it happen ✦';
    el('cancel').classList.toggle('hidden',!busy);el('cancel').disabled=false;
    el('again').classList.toggle('hidden',busy);
    el('repair').disabled=busy;el('repair').textContent=st.state==='repairing'?'🛠 Fixing…':'🛠 Fix my tools';
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
// New versions are checked locally through Mochi's authenticated server.
// Never send the browser's private key or transcripts to GitHub.
let updatePhase='idle', updateTarget='', waitingForUpgrade=false, checkingUpdate=false;
const updateLabel=el('update-message');
function updateView(state){
  updatePhase=state.phase||'idle';
  updateLabel.textContent=state.message||'Your files stay on this computer.';
  if(state.current)el('update-current').textContent='Installed '+state.current;
  if(state.latest)updateTarget=state.latest;
  el('install-update').classList.toggle('hidden',updatePhase!=='available');
  el('cancel-update').classList.toggle('hidden',!['downloading','staging'].includes(updatePhase));
  if(!['downloading','staging'].includes(updatePhase))el('cancel-update').disabled=false;
  const inProgress=['downloading','staging','restarting'].includes(updatePhase);
  el('check-update').disabled=inProgress||checkingUpdate;
  el('install-update').disabled=inProgress||checkingUpdate;
  if(inProgress&&Number.isFinite(state.percent)){
    updateLabel.textContent=(state.message||'Updating…')+' '+state.percent+'%';
  }
}
async function checkForUpdate(){
  if(checkingUpdate||['downloading','staging','restarting'].includes(updatePhase))return;
  checkingUpdate=true;el('check-update').disabled=true;
  updateLabel.textContent='Checking Mochi releases…';
  try{updateView(await api('/api/update/check'))}
  catch(err){updateLabel.textContent='Could not check updates. Try again when online.'}
  finally{checkingUpdate=false;el('check-update').disabled=false}
}
el('check-update').addEventListener('click',checkForUpdate);
el('install-update').addEventListener('click',async()=>{
  if(updatePhase!=='available')return;
  try{
    await api('/api/update/start',{});
    updateView({phase:'downloading',message:'Preparing your update safely…',percent:0});
  }catch(err){updateLabel.textContent=err.message}
});
el('cancel-update').addEventListener('click',async()=>{
  try{
    await api('/api/update/cancel',{});
    el('cancel-update').disabled=true;
    updateLabel.textContent='Stopping the update safely…';
  }catch(err){updateLabel.textContent=err.message}
});
async function watchUpgrade(){
  if(waitingForUpgrade)return;
  waitingForUpgrade=true;
  for(let i=0;i<60;i++){
    await new Promise(resolve=>setTimeout(resolve,1500));
    try{
      const health=await api('/api/health');
      if(updateTarget&&health.version===''+updateTarget.replace(/^v/,'')){
        window.location.reload();
        return;
      }
      const st=await api('/api/update/status');
      if(['failed','rolled-back','error'].includes(st.phase)){
        updateLabel.textContent=st.message||'Update was not completed. Your files are safe.';
        waitingForUpgrade=false;
        return;
      }
    }catch(err){/* Server is restarting; try the same private loopback URL. */}
  }
  updateLabel.textContent='Could not reconnect. Open Run Mochi Now to recover or retry.';
  waitingForUpgrade=false;
}
async function pollUpdate(){
  if(!['downloading','staging','restarting'].includes(updatePhase))return;
  try{
    const state=await api('/api/update/status');
    updateView(state);
    if(state.phase==='restarting')watchUpgrade();
  }catch(err){if(updatePhase==='restarting')watchUpgrade()}
}
async function bookmarkInfo(){
  try{
    const health=await api('/api/health');
    el('update-current').textContent='Installed v'+health.version;
    if(!health.bookmark_stable){
      const hint=document.querySelector('.bookmark-help small');
      if(hint)hint.textContent='A temporary local port is being used. Use Run Mochi Now to reconnect after restarting.';
    }
  }catch(err){}
}
selectedMode();refresh();setInterval(refresh,850);
bookmarkInfo();checkForUpdate();setInterval(pollUpdate,1500);


