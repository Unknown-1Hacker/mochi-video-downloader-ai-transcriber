'use strict';
const KEY=document.querySelector('meta[name="mochi-key"]').content;
const el=id=>document.getElementById(id);
const mode=()=>document.querySelector('input[name="mode"]:checked').value;
let busy=false,qualitiesBusy=false, lastState='ready';
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
    busy=true;el('repair').disabled=true;el('activity').classList.remove('hidden');el('activity').scrollIntoView({behavior:'smooth',block:'nearest'});
    await refresh();
  }catch(e){note(e.message,'error')}
});
el('cancel').addEventListener('click',async()=>{el('cancel').disabled=true;try{await api('/api/cancel',{});el('status-text').textContent='Stopping safely…'}catch(e){note(e.message)}});
el('again').addEventListener('click',()=>{el('activity').classList.add('hidden');el('url').focus()});
el('repair').addEventListener('click',async()=>{if(busy)return;el('repair').disabled=true;try{await api('/api/repair',{});busy=true;await refresh()}catch(e){busy=false;note(e.message)}finally{el('repair').disabled=busy}});
el('open-folder').addEventListener('click',async()=>{try{await api('/api/open',{})}catch(e){note(e.message)}});
async function refresh(){
  try{
    const st=await api('/api/status');
    if(st.state==='ready'){busy=false;el('repair').disabled=false;return;}
    lastState=st.state;
    el('activity').classList.remove('hidden');
    el('status-heading').textContent=st.state==='done'?'A little magic, completed!':st.state==='error'?'Almost! Let’s fix this':st.state==='cancelled'?'Cancelled':st.state==='repaired'?'Mochi is ready again!':st.state==='repairing'?'Fixing your tools…':'Making your video…';
    el('status-text').textContent=st.message;
    const pct=Number(st.percent)||0;el('percent').textContent=pct+'%';el('progress-fill').style.width=pct+'%';el('progress').setAttribute('aria-valuenow',String(pct));
    busy=st.state==='working'||st.state==='repairing';
    el('start').disabled=busy;el('start').textContent=busy?'Working its magic…':'Make it happen ✦';
    el('cancel').classList.toggle('hidden',!busy);el('cancel').disabled=false;
    el('again').classList.toggle('hidden',busy);
    el('repair').disabled=busy;el('repair').textContent=st.state==='repairing'?'🛠 Fixing…':'🛠 Fix my tools';
    const done=st.state==='done';el('results').classList.toggle('hidden',!done);
    if(done){const container=el('file-list');container.replaceChildren();for(const item of st.files){const span=document.createElement('span');span.textContent='📄 '+item;container.appendChild(span)}}
  }catch(err){if(busy){el('status-text').textContent='App connection was lost. Double-click Run Mochi Now to reconnect.';busy=false;el('start').disabled=false}}
}
selectedMode();refresh();setInterval(refresh,850);


