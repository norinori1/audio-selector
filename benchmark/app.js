'use strict';
let session, labels, page = 0;
const memory = new Map();
let saving = Promise.resolve();
let moving = false;
const status = document.querySelector('#status');
function state(q, clip) {
  const key = q.id + ':' + clip.clip_id;
  if (!memory.has(key)) memory.set(key, {query_id:q.id, clip_id:clip.clip_id, relevance:null, audition_seconds:0, play_count:0, notes:''});
  return memory.get(key);
}
async function save() {
  document.querySelectorAll('audio').forEach(a => a.pause());
  const payload = {package_id:session.package_id, judgments:[...memory.values()].filter(x => x.relevance)};
  const response = await fetch('/labels', {method:'POST', headers:{'Content-Type':'application/json','X-Audition-Token':session.save_token}, body:JSON.stringify(payload)});
  if (!response.ok) throw new Error(await response.text());
  status.textContent = 'Saved ' + payload.judgments.length + ' of ' + session.queries.reduce((n,q) => n+q.clips.length,0) + ' judgments. Unsure decisions need another listen.';
}
function render() {
  document.querySelectorAll('audio').forEach(a => a.pause());
  const q = session.queries[page];
  document.querySelector('#prompt').textContent = 'Request ' + (page+1) + ' of ' + session.queries.length + ': ' + q.prompt;
  document.querySelector('#clips').replaceChildren();
  q.clips.forEach((clip, i) => {
    const s = state(q,clip), row = document.createElement('article');
    const title = document.createElement('h3'); title.textContent = 'Clip ' + (i+1); row.append(title);
    const a = document.createElement('audio'); a.controls=true; a.preload='metadata'; a.src='/clip/'+clip.clip_id; a.setAttribute('aria-label','Listen to clip '+(i+1)); row.append(a);
    let clock = null, excerptEnd = null;
    function tick() { if(clock !== null) { s.audition_seconds += (performance.now()-clock)/1000; clock = performance.now(); } }
    a.addEventListener('play', () => { document.querySelectorAll('audio').forEach(other => { if(other!==a) other.pause(); }); s.play_count++; });
    a.addEventListener('playing', () => { clock=performance.now(); select.disabled=false; });
    a.addEventListener('waiting', () => { tick(); clock=null; });
    a.addEventListener('pause', () => { tick(); clock=null; });
    a.addEventListener('ended', () => { tick(); clock=null; });
    a.addEventListener('timeupdate', () => { if(excerptEnd !== null && a.currentTime >= excerptEnd) { a.pause(); excerptEnd=null; } });
    if(clip.duration > 20) {
      [[0,'Start'],[Math.max(0,clip.duration/2-5),'Middle'],[Math.max(0,clip.duration-10),'End']].forEach(([offset,word]) => {
        const b=document.createElement('button'); b.textContent=word+' · 10 seconds'; b.onclick=()=>{ a.currentTime=offset; excerptEnd=Math.min(offset+10,clip.duration); a.play().catch(e=>status.textContent=e.message); }; row.append(b);
      });
      const b=document.createElement('button'); b.textContent='Explore full track'; b.onclick=()=>{ excerptEnd=null; a.play().catch(e=>status.textContent=e.message); }; row.append(b);
    }
    const label=document.createElement('label'); label.textContent='Does this clip match the request? ';
    const select=document.createElement('select'); select.setAttribute('aria-label','Relevance for clip '+(i+1));
    [['','Listen, then decide'],['relevant','Relevant'],['irrelevant','Not relevant'],['unsure','Unsure — revisit']].forEach(([value,text])=>{const o=document.createElement('option');o.value=value;o.textContent=text;select.append(o);});
    select.value=s.relevance || ''; select.disabled=s.play_count===0;
    select.onchange=()=>{tick(); s.relevance=select.value || null;}; label.append(select); row.append(label);
    const nl=document.createElement('label'); nl.textContent='Optional notes: fit, fatigue, taste, or mismatch';
    const notes=document.createElement('textarea'); notes.setAttribute('aria-label','Notes for clip '+(i+1)); notes.value=s.notes; notes.oninput=()=>s.notes=notes.value; nl.append(notes); row.append(nl);
    document.querySelector('#clips').append(row);
  });
  document.querySelector('#prev').disabled=page===0; document.querySelector('#next').disabled=page===session.queries.length-1;
}
async function change(delta) {if(moving)return; moving=true;try {await save(); page+=delta; render(); document.querySelector('#prompt').focus();} catch(e) {status.textContent='Save failed: '+e.message;} finally{moving=false;}}
document.querySelector('#prev').onclick=()=>change(-1);
document.querySelector('#next').onclick=()=>change(1);
document.querySelector('#save').onclick=()=>{saving=saving.then(save).catch(e=>status.textContent='Save failed: '+e.message);};
document.querySelector('#export').onclick=async()=>{try{await save(); const blob=await(await fetch('/labels')).blob();const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download='audition-labels.json';link.click();URL.revokeObjectURL(url);}catch(e){status.textContent=e.message;}};
window.addEventListener('beforeunload',e=>{e.preventDefault();e.returnValue='Save your progress before leaving.';});
Promise.all([fetch('/session').then(r=>r.json()),fetch('/labels').then(r=>r.json())]).then(([s,l])=>{session=s;labels=l; l.judgments.forEach(j=>memory.set(j.query_id+':'+j.clip_id,j));render();status.textContent='Ready. Progress is saved when you press Save or change requests.';}).catch(e=>status.textContent=e.message);
