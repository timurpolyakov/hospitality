'use strict';
const $ = s => document.querySelector(s);
const IS_WORKER = location.pathname === '/worker.html' || location.pathname === '/worker' || location.pathname.startsWith('/worker/');
const WORKER_ID = new URLSearchParams(location.search).get('worker') || (location.pathname.startsWith('/worker/') ? location.pathname.split('/')[2] : 'mike');
const PORTAL_ACTOR = IS_WORKER ? WORKER_ID : 'agent';
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const S = {data:null, tab:'jobs', filter:'all', search:'', history:false, connected:true, panel:null, busy:false, alert:'', known:null};
S.sortBy={jobs:'priority',stays:'priority'};
S.sortDirection={jobs:1,stays:1};
const statusLabel = {new:'Unassigned', queued:'Queued', on_way:'On the way', working:'In progress', closed:'Completed'};
const time = n => new Date(n*1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'});
const liveTime = n => new Date(n*1000).toLocaleTimeString([], {hour:'numeric',minute:'2-digit',second:'2-digit',timeZone:'America/New_York'});
const hotelNow = () => S.data.now + (performance.now() - S.syncedAt) / 1000;
const reportedAgo = n => {const m=Math.max(0,Math.floor((hotelNow()-n)/60));return m<60?`${m} min`:`${Math.floor(m/60)}h ${m%60}m`;};
function tickClock(){if(!S.data)return;const now=hotelNow();document.querySelectorAll('[data-live-clock]').forEach(el=>{el.textContent=liveTime(now);el.dateTime=new Date(now*1000).toISOString();});document.querySelectorAll('[data-reported-at]').forEach(el=>{el.textContent=`Reported ${reportedAgo(Number(el.dataset.reportedAt))} ago`;});}
const ago = n => {const m=Math.max(0,Math.floor((S.data.now-n)/60)); return m<60?`${m} min`:`${Math.floor(m/60)}h ${m%60}m`;};
const wait = n => `${Math.max(0,Math.round((n-S.data.now)/60))} min`;
const checkoutLine = g => g.checkout>S.data.now?`Checkout in ${wait(g.checkout)}`:`Checkout passed ${ago(g.checkout)} ago`;
const cat = t => S.data.categories[t.category];
const worker = id => S.data.workers.find(w=>w.id===id);
const open = t => t.status!=='closed'&&t.status!=='cancelled';

async function api(path,body){
 const r=await fetch(path,{method:body?'POST':'GET',credentials:'same-origin',headers:body?{'Content-Type':'application/json','X-Eisen-Actor':PORTAL_ACTOR}:{'X-Eisen-Actor':PORTAL_ACTOR},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(10000)});
 const d=await r.json(); if(!r.ok){const e=new Error(d.error||'Something went wrong.');e.status=r.status;throw e;}return d;
}
let toastTimer;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,6000);}
function live(){return `<span class="live ${S.connected?'':'offline'}"><i class="live-dot"></i>${S.connected?`Live · <time data-live-clock class="mono" title="Hotel time · America/New_York" datetime="${new Date(hotelNow()*1000).toISOString()}">${liveTime(hotelNow())}</time>`:'Connection lost · retrying'}</span>`;}
function renderUnavailable(message='Unable to open this portal.'){
 $('#app').innerHTML=`<main class="worker-shell"><div class="logo">eisen<span class="brand-dot"></span></div><div class="errorbox" role="alert">${esc(message)}</div><p class="quiet">Start the local Eisen server, then open your portal.</p><div class="actions"><button data-action="retry">Try again</button></div></main>`;
}
function preserveRender(fn){
 const focus=document.activeElement, id=focus?.id, start=focus?.selectionStart,end=focus?.selectionEnd;
 fn();
 if(id&&$('#'+id)&&!$('#panel').open){const el=$('#'+id);el.focus({preventScroll:true});if(typeof start==='number'&&el.setSelectionRange)el.setSelectionRange(start,end);}
}
function agentShell(){
 const d=S.data, jobs=d.issues.filter(open);
 const recovery=Object.values(d.guests).filter(g=>g.recovery.trigger).length;
 const active=d.workers.filter(w=>jobs.some(t=>t.worker_id===w.id&&['on_way','working'].includes(t.status))).length;
 $('#app').innerHTML=`<div class="shell"><aside class="sidebar"><div class="logo">eisen<span class="brand-dot"></span></div><div class="hotel"><div class="eyebrow">Property</div><strong>Waldorf Astoria<br>Ithaca</strong></div><nav class="nav" aria-label="Workspace"><button data-tab="jobs" class="${S.tab==='jobs'?'selected':''}">Issue review <span class="quiet">${jobs.length}</span></button><button data-tab="team" class="${S.tab==='team'?'selected':''}">Workers & queues</button><button data-tab="stays" class="${S.tab==='stays'?'selected':''}">Guest stays</button></nav><div class="sidebottom"><p class="quiet">Global Solutions for Cornell Hospitality Hackathon 2026</p></div></aside><main class="main"><div class="topline"><span class="eyebrow">Hotel agent workspace</span><div class="actions">${live()}</div></div><div class="heading"><div><h1>${S.tab==='jobs'?'Issue review':S.tab==='team'?'Workers & queues':'Guest stays'}</h1></div><button class="primary" data-action="create">+ Report issue</button></div>${S.tab==='team'?`<div class="summary"><div class="stat"><b>${active}</b><span>working</span></div><div class="stat"><b>${d.workers.length-active}</b><span>available</span></div><div class="stat"><b>${jobs.filter(t=>t.status==='queued').length}</b><span>queued job${jobs.filter(t=>t.status==='queued').length===1?'':'s'}</span></div></div>`:`<div class="summary"><div class="stat"><b>${jobs.length}</b><span>open issues</span></div><div class="stat"><b>${jobs.filter(t=>t.status==='new').length}</b><span>awaiting assignment</span></div><div class="stat"><b>${recovery}</b><span>recovery decision${recovery===1?'':'s'}</span></div><div class="stat"><b>${active}/${d.workers.length}</b><span>workers active</span></div></div>`}<div id="workspace">${S.tab==='jobs'?board():S.tab==='team'?team():stays()}</div></main></div>`;
}

const statusOrder = {new:0,queued:1,on_way:2,working:3,closed:4,cancelled:5};
function sortHeading(key,label){
 const selected=S.sortBy[S.tab]===key,dir=S.sortDirection[S.tab];
 return `<div role="columnheader" aria-sort="${selected?(dir===1?'ascending':'descending'):'none'}"><button class="sort-heading ${selected?'selected':''}" data-sort="${key}" aria-label="Sort by ${label}${selected?`, ${dir===1?'ascending':'descending'}`:''}">${label}<span aria-hidden="true">${selected?(dir===1?'↑':'↓'):'↕'}</span></button></div>`;
}

function compareJobs(a,b){
 const mode=S.sortBy.jobs;
 const primary=mode==='status'?statusOrder[a.status]-statusOrder[b.status]:mode==='elapsed'?b.reported_at-a.reported_at:mode==='location'?a.room.localeCompare(b.room,undefined,{numeric:true}):a.task_priority.value-b.task_priority.value;
 return primary*S.sortDirection.jobs||a.task_priority.value-b.task_priority.value||a.review.tier-b.review.tier||b.metrics.priority-a.metrics.priority||a.reported_at-b.reported_at;
}

function board(){
 let jobs=S.data.issues.filter(t=>S.history?t.status==='closed':open(t));
 if(S.filter!=='all')jobs=jobs.filter(t=>S.filter==='new'?t.status==='new':cat(t).team===S.filter);
 const q=S.search.toLowerCase();jobs=jobs.filter(t=>`${t.room} ${t.description} ${t.id}`.toLowerCase().includes(q));
 jobs.sort(compareJobs);
 return `<div class="toolbar"><div class="filters" aria-label="Job filters">${[['all','All jobs'],['new','Unassigned'],['Maintenance','Maintenance'],['Housekeeping','Housekeeping']].map(([v,l])=>`<button data-filter="${v}" class="${S.filter===v?'selected':''}">${l}</button>`).join('')}<button data-action="history" class="${S.history?'selected':''}">${S.history?'✓ ':''}Completed</button></div><div class="list-tools"><input id="search" class="search" type="search" placeholder="Search room or issue" aria-label="Search room or issue" value="${esc(S.search)}"></div></div><div class="board"><div class="tablehead" role="row">${sortHeading('location','Issue / location')}${sortHeading('priority','Priority')}${sortHeading('status','Status')}${sortHeading('elapsed','Time elapsed')}<span></span></div>${jobs.map((t,index)=>{
 const g=S.data.guests[t.guest_id],w=t.worker_id?worker(t.worker_id):null;
 return `<article class="jobrow"><div class="issue-cell"><div><div class="location">Room ${esc(t.room)} · ${esc(cat(t).team)} <span class="quiet">/ ${t.id}</span></div><p class="title">${esc(t.description)}</p>${t.status!=='closed'?`<div class="review-reason ${t.review.tier<=2?'attention':''}">${esc(t.review.reason)}</div>`:''}</div></div><div class="task-priority"><span class="priority-badge priority-${t.task_priority.value}" aria-label="Priority ${t.task_priority.value} of 5, ${esc(t.task_priority.label)}">${t.task_priority.value}<span> / 5</span></span><small>${esc(t.task_priority.label)}</small></div><div class="status"><span class="badge ${t.status==='new'?'warn':t.status==='closed'?'gray':''}">${statusLabel[t.status]}</span>${w?`<small>${esc(w.name)}${t.status==='queued'?' · queued':''}</small>`:''}${t.metrics.urgent?'<small class="recover-flag">Urgent leak</small>':t.metrics.stay.severe?'<small class="recover-flag">Severe stay impact</small>':''}</div><div class="elapsed-cell">${ago(t.reported_at)}</div><button class="small ${t.status==='new'||g.recovery.trigger?'primary':''}" data-job="${t.id}">${t.status==='new'?'Review →':'Details →'}</button></article>`;
 }).join('')||'<div class="empty">No jobs here. You’re all caught up.</div>'}</div>`;
}
function team(){return `<div class="teamgrid">${S.data.workers.map(w=>{
 const active=S.data.issues.find(t=>t.worker_id===w.id&&['on_way','working'].includes(t.status));
 const queue=S.data.issues.filter(t=>t.worker_id===w.id&&t.status==='queued').sort((a,b)=>a.queue_order-b.queue_order);
 return `<section class="worker-card team-card worker-state-${active?active.status:'available'}" aria-label="${esc(w.name)}"><div class="worker-head"><div><h2 class="worker-name">${esc(w.name)}</h2><p class="quiet">${esc(w.team)}${active?'':` · Floor ${w.floor}`}</p></div><span class="badge ${active?'':'gray'}">${active?(active.status==='on_way'?'On the way':'Working'):'Available'}</span></div>${active?`<div class="current-assignment"><div><h3>Room ${active.room}</h3><p>${esc(active.description)}</p></div><button class="small" data-job="${active.id}" aria-label="Review current job for ${esc(w.name)}">→</button></div>`:''}${queue.length?`<div class="queue-label">Up next · ${queue.length}</div>${queue.map((t,i)=>`<div class="queue-item"><span class="queue-order">${i+1}</span><div class="queue-copy"><p>Room ${t.room}</p><small>${esc(t.description)}</small></div><div class="queue-buttons"><button data-job="${t.id}" aria-label="Review ${t.id}">→</button></div></div>`).join('')}`:''}</section>`;
 }).join('')}</div>`;}
function stays(){
 const summary=g=>{const issues=S.data.issues.filter(t=>t.guest_id===g.id&&open(t));return {priority:issues.length?Math.min(...issues.map(t=>t.task_priority.value)):6,status:issues.length?Math.min(...issues.map(t=>statusOrder[t.status])):4,elapsed:issues.length?S.data.now-Math.min(...issues.map(t=>t.reported_at)):-1};};
 const guests=Object.values(S.data.guests).map(g=>({g,...summary(g)})).sort((a,b)=>(S.sortBy.stays==='location'?a.g.room.localeCompare(b.g.room,undefined,{numeric:true}):a[S.sortBy.stays]-b[S.sortBy.stays])*S.sortDirection.stays||a.priority-b.priority||a.g.room.localeCompare(b.g.room)).map(row=>row.g);
 return `<div class="stay-sort" role="row">${sortHeading('location','Room')}${sortHeading('priority','Priority')}${sortHeading('status','Status')}${sortHeading('elapsed','Time elapsed')}</div><div class="history-list">${guests.map(g=>{const count=S.data.issues.filter(t=>t.guest_id===g.id&&open(t)).length;return `<section class="worker-card"><div class="split"><div><h2 class="stay-room">Room ${esc(g.room)}</h2><p class="stay-guest">${esc(g.name)} · ${count} open issue${count===1?'':'s'}</p><p class="quiet">Checkout ${time(g.checkout)} · ${wait(g.checkout)} remaining</p></div><div><span class="badge ${g.estimate.severe?'red':'gray'}">${g.estimate.severe?'Severely affected':'Stay overview'}</span><p class="quiet">Estimated Stay Score ${g.estimate.low}–${g.estimate.high} / 100</p></div></div><div class="actions"><button class="small" data-guest="${g.id}">Stay details →</button>${g.recovery.trigger?'<span class="offer-pill">Recovery suggested</span>':g.recovery.pending?'<span class="offer-pill">Recovery in progress</span>':''}</div></section>`;}).join('')}</div>`;}
function workerShell(){
 const d=S.data,w=d.worker,active=d.issues.find(t=>['working','on_way'].includes(t.status)),queue=d.issues.filter(t=>t.status==='queued').sort((a,b)=>a.queue_order-b.queue_order),done=d.issues.filter(t=>t.status==='closed').length;
 $('#app').innerHTML=`<main class="worker-shell"><header class="worker-top"><div class="logo">eisen<span class="brand-dot"></span></div><label class="worker-switch">Worker<select id="worker-select" aria-label="Worker">${d.workers.map(person=>`<option value="${person.id}" ${person.id===w.id?'selected':''}>${esc(person.name)}</option>`).join('')}</select></label></header><div class="worker-welcome"><div class="eyebrow">${esc(d.property)} · Sample hotel</div><div class="split"><h1>Your shift, ${esc(w.name)}.</h1>${live()}</div><p class="quiet">${esc(w.team)} · ${done} completed</p></div>${S.alert?`<div class="alertstrip" role="alert"><span>${esc(S.alert)}</span><button class="small" data-action="dismiss">Got it</button></div>`:''}${active?`<section class="activejob"><div class="eyebrow">${statusLabel[active.status]}</div><h2>Room ${active.room}</h2><p>Floor ${active.floor} · ${esc(cat(active).label)}</p><h3>${esc(active.description)}</h3>${active.note?`<p class="note">${esc(active.note)}</p>`:''}<button class="primary" data-progress="${active.id}" data-step="${active.status==='on_way'?'start':'done'}">${active.status==='on_way'?'Start job':'Done ✓'}</button><p class="fineprint">${active.status==='on_way'?'This job stays with you while you head there.':'Finishing closes this issue and returns you to your latest queue.'}</p></section>`:queue.length?`<section class="activejob"><div class="eyebrow">Next approved job</div><h2>Room ${queue[0].room}</h2><p>Floor ${queue[0].floor} · ${esc(cat(queue[0]).label)}</p><h3>${esc(queue[0].description)}</h3>${queue[0].note?`<p class="note">${esc(queue[0].note)}</p>`:''}<button class="primary" data-progress="${queue[0].id}" data-step="head">Head there →</button></section>`:`<section class="phone-empty"><div class="eyebrow">All clear</div><h2>No jobs queued.</h2><p>Keep this page open. Your next approved assignment will appear here with an alert.</p></section>`}${active||queue.length?`<div class="sectiontitle"><h3>${active?'Your stack':'After this job'}</h3><span class="quiet">${Math.max(0,queue.length-(active?0:1))} queued</span></div><div class="worker-queue">${(active?queue:queue.slice(1)).map((t,i)=>`<article class="queue-item"><span class="queue-order">${i+1}</span><div class="queue-copy"><p>Room ${t.room} · Floor ${t.floor}</p><small>${esc(t.description)}</small>${t.note?`<small>${esc(t.note)}</small>`:''}</div><span class="badge">Approved</span></article>`).join('')||'<p class="quiet">No upcoming jobs.</p>'}</div>`:''}<p class="footer">Your stack updates by priority. Finish your current job, then follow the next one.</p></main>`;
}
function render(){if(!S.data)return;preserveRender(()=>S.data.actor.role==='agent'?agentShell():workerShell());}
async function refresh(){
 try{const d=await api('/api/state');S.connected=true;
  if(d.dev_revision){
   if(S.devRevision && S.devRevision!==d.dev_revision){
    sessionStorage.setItem('eisen-dev-view',JSON.stringify({tab:S.tab,filter:S.filter,search:S.search,history:S.history,sortBy:S.sortBy,sortDirection:S.sortDirection,panel:S.panel?{mode:S.panel.mode,id:S.panel.id}:null}));
    location.reload();return;
   }
   S.devRevision=d.dev_revision;
  }
  if(d.actor.role==='worker'){
   const current=new Map(d.issues.filter(open).map(t=>[t.id,t]));
   if(S.known){const newJobs=[...current.keys()].filter(id=>!S.known.has(id));const reordered=[...current.values()].some(t=>S.known.has(t.id)&&t.status==='queued'&&S.known.get(t.id).queue_order!==t.queue_order);
    if(newJobs.length||reordered){S.alert=newJobs.length?`${newJobs.length} new job${newJobs.length>1?'s':''} approved. Your stack is updated.`:'Your stack was reordered by priority.';toast(S.alert);}}
   S.known=current;
  }
  const panelGuest=S.panel?.mode==='job'&&S.data?.guests[S.data.issues.find(t=>t.id===S.panel.id)?.guest_id];
  const crossedCheckout=panelGuest&&S.data.now<panelGuest.checkout&&d.now>=panelGuest.checkout;
  S.data=d;S.syncedAt=performance.now();
  const restored=d.dev_revision?sessionStorage.getItem('eisen-dev-view'):null;
  if(restored){
   sessionStorage.removeItem('eisen-dev-view');
   try{const view=JSON.parse(restored);if(view.sortBy)S.sortBy=view.sortBy;if(view.sortDirection)S.sortDirection=view.sortDirection;Object.assign(S,{tab:view.tab,filter:view.filter,search:view.search,history:view.history});render();
    if(d.actor.role==='agent'&&view.panel?.mode==='guest'&&d.guests[view.panel.id])guestPanel(view.panel.id);
    else if(d.actor.role==='agent'&&view.panel?.mode==='job'&&d.issues.some(t=>t.id===view.panel.id))await jobPanel(view.panel.id);
   }catch{render();}
  }else{render();if(crossedCheckout&&!S.busy)await jobPanel(S.panel.id);}
 }catch(e){S.connected=false;if(S.data)render();else renderUnavailable(e.status===400?e.message:'Start the local Eisen server to open the demo.');}
}
function panel(title,body,eyebrow='Eisen',context={}){S.panel=context;$('#panel').classList.toggle('guest-experience',['guest','job'].includes(context.mode));$('#panel').classList.toggle('task-experience',context.mode==='job');$('#panel').innerHTML=`<header class="panelhead"><div><div class="eyebrow">${eyebrow}</div><h2 id="panel-title">${title}</h2></div><button class="close" data-action="close" aria-label="Close">×</button></header><div class="panelbody">${body}</div>`;if(!$('#panel').open)$('#panel').showModal();}
async function jobPanel(id){
 const t=S.data.issues.find(t=>t.id===id);if(!t)return;const g=S.data.guests[t.guest_id],stayEnded=g.checkout<=S.data.now;let rec=null;
 if(['new','queued'].includes(t.status)&&(!stayEnded||t.metrics.urgent)){try{rec=await api('/api/recommendations?id='+encodeURIComponent(id));}catch(e){toast(e.message);await refresh();return;}}
 let situation=`<div><span class="priority-badge priority-${t.task_priority.value}">Priority ${t.task_priority.value} · ${esc(t.task_priority.label)}</span> <span class="badge">${statusLabel[t.status]}</span><p class="task-description">${esc(t.description)}</p><p class="reported-time" data-reported-at="${t.reported_at}">Reported ${reportedAgo(t.reported_at)} ago</p>${t.note?`<p class="quiet">${esc(t.note)}</p>`:''}</div><div class="split"><div><div class="eyebrow">Stay Score decrease so far</div><div class="estimate">−${t.metrics.loss.toFixed(1)} pts</div></div><div><div class="eyebrow">Further decrease · next 30 min</div><div class="estimate">−${t.metrics.delay_loss.toFixed(1)} pts</div></div></div><div class="stayline"><div><b>${esc(g.name)}</b><p class="quiet">${Object.keys(g.sensitivity).includes(t.category)?'Relevant previous complaints · ':''}${checkoutLine(g)}</p></div><button data-guest="${g.id}">Stay & recovery →</button></div>`;
 let actions=stayEnded?`<section class="context followup-card"><h3>Guest follow-up</h3><p>The stay has ended. Review the guest’s experience and ${g.recovery.pending?'the existing recovery offer':'recovery options'}.</p><button class="primary" data-guest="${g.id}">Review stay & recovery →</button></section><div class="maintenance-note"><p class="quiet">${t.status==='closed'?'Room maintenance completed.':`Room maintenance remains open for the next stay.${t.worker_id?` ${esc(worker(t.worker_id)?.name||'The assigned worker')} ${t.status==='queued'?'is already queued.':'is already committed.'}`:''}`}</p><div class="actions"><button class="small ghost" data-edit="${t.id}">Edit details</button></div></div>`:'';
 if(!stayEnded&&g.recovery.trigger){actions+=`<section class="context"><h3>Guest recovery first</h3><p>${esc(g.recovery.reason)}</p><button data-guest="${g.id}">Review guest recovery →</button></section>`;}
 if(rec?.options.length){actions+=`<section>${rec.options.map((o,i)=>{
  const person=worker(o.worker_id),active=S.data.issues.find(job=>job.worker_id===o.worker_id&&['working','on_way'].includes(job.status));
  const locationLabel=active?(active.status==='on_way'?'Heading to':'Committed'):'Available';
  return `<div class="recommendation dispatch-option ${i===0?'best':''}"><div class="eyebrow">${i===0?'Recommended':'Alternative'}</div><h3>${esc(o.name)}</h3><dl class="dispatch-facts"><div><dt>${locationLabel}</dt><dd>${active?'Room':'Floor'} ${esc(active?active.room:person.floor)}</dd></div><div><dt>Starts in</dt><dd>${o.start}<small> min</small></dd></div><div><dt>Queue position</dt><dd>${o.position+1}</dd></div></dl><button class="${i===0?'primary':''}" data-assign="${o.worker_id}" data-position="${o.position}">Approve · ${esc(o.name)}</button></div>`;
 }).join('')}<div class="actions">${t.status==='queued'?`<button class="small" data-unassign="${t.id}">Return to unassigned</button>`:''}<button class="small ghost" data-edit="${t.id}">Edit details</button></div></section>`;}
 if(t.status==='closed'&&!stayEnded)actions+=`<section><h3>Guest says it is still unresolved?</h3><form id="reopen" class="formgrid"><label>Guest feedback<input name="reason" required minlength="3" maxlength="500" placeholder="What is still wrong?"></label><button type="submit">Reopen issue</button></form></section>`;

 if(!actions)actions=`<p class="quiet">${esc(worker(t.worker_id)?.name||'Worker')} is ${t.status==='on_way'?'on the way':'working on this issue'}.</p>`;
 const body=`<div class="guest-layout"><section class="guest-situation" aria-labelledby="situation-title"><h3 class="guest-section-title" id="situation-title">Situation</h3>${situation}</section><section class="guest-actions" aria-labelledby="actions-title"><h3 class="guest-section-title" id="actions-title">Actions</h3>${actions}</section></div>`;
 panel(`<span class="task-room">Room ${esc(t.room)}</span><span class="task-category">${esc(cat(t).label)}</span>`,body,`Floor ${t.floor} · Task ${esc(t.id)}`,{mode:'job',id,rec,version:t.version});
}
function curve(t){
 const m=t.metrics,c=cat(t),g=S.data.guests[t.guest_id],sensitivity=g.sensitivity[t.category]||1;
 // Visual is explicitly schematic; server snapshots supply the actual numeric estimates.
 const vals=Array.from({length:31},(_,i)=>{const x=i*4,y=100*(1-Math.exp(-x*sensitivity/c.tau));return `${i?'L':'M'}${30+i*15},${112-y}`;}).join(' ');
 return `<svg class="curve" viewBox="0 0 500 140" role="img" aria-label="Schematic Stay Score decrease curve: decrease grows with unresolved time"><line x1="30" y1="112" x2="480" y2="112"/><path d="${vals}"/><text x="30" y="135">Report</text><text x="380" y="135">120 min unresolved →</text><text x="30" y="12">Schematic · increasing loss</text></svg>`;
}
function guestPanel(id){
 const g=S.data.guests[id],r=g.recovery,issues=S.data.issues.filter(t=>t.guest_id===id),outcome=S.data.outcomes.find(o=>o.guest_id===id);
 let situation=`<div class="split"><div><div class="eyebrow">Estimated Stay Score</div><div class="estimate">${g.estimate.low}–${g.estimate.high} / 100</div></div><span class="badge ${g.estimate.severe?'red':'gray'}">${g.estimate.severe?'Severely affected':'Combined stay estimate'}</span></div><p class="fineprint">Stay Score out of 100 · provisional demo estimates.</p><p class="quiet">${esc(g.name)} · Checkout ${time(g.checkout)} · ${wait(g.checkout)} remaining</p><section><h3>This stay’s issues</h3>${issues.map(t=>`<div class="history-row split"><div>Room ${t.room} · ${esc(t.description)}<p>${statusLabel[t.status]} · −${t.metrics.loss.toFixed(1)} Stay Score points estimated</p></div><button class="small" data-job="${t.id}">View</button></div>`).join('')}</section>`;
 let actions=`<section><h3>${r.trigger?'First action: contact the guest':'Recovery'}</h3>${r.trigger?`<p class="muted">${esc(r.reason)}</p>${r.options.map((o,i)=>`<div class="recommendation ${i===0?'best':''}"><div class="eyebrow">${i===0?'Recommended':'Alternative'}</div><h3>${esc(o.label)}</h3><p>${o.kind===g.preferred_offer?'Matches the sample guest preference and recovery history.':'An alternative gesture within the demo catalog.'}</p><button class="${i===0?'primary':''}" data-offer="${o.kind}" data-guest-id="${g.id}">Approve ${esc(o.label.toLowerCase())}</button></div>`).join('')}`:r.policy_limited?'<p class="muted">Demo policy limit reached. No further offer is available within the configured limits.</p>':r.pending?'<p class="muted">An approved recovery offer is in progress.</p>':r.suppressed?'<p class="muted">A previous offer was handled. Eisen will suggest another if estimated loss worsens by at least 5 Stay Score points.</p>':'<p class="muted">No recovery offer is needed under the current demo rules.</p>'}<p class="fineprint">Illustrative demo policy: up to ${S.data.policy.max_offers_per_stay} offers, $${S.data.policy.max_cost_per_stay} catalog value and ${S.data.policy.max_points_per_stay.toLocaleString()} points per stay. Offers require approval; acceptance and fulfillment are recorded separately.</p>${r.previous.map(o=>`<div class="history-row"><b>${esc(S.data.offers[o.kind].label)}</b> · ${esc(o.status)}<p>Approved ${time(o.at)} · ${esc(o.approved_by)}</p><div class="actions">${o.status==='approved'?`<button class="small" data-offer-id="${o.id}" data-offer-status="offered">Mark offered</button>`:o.status==='offered'?`<button class="small" data-offer-id="${o.id}" data-offer-status="accepted">Guest accepted</button><button class="small" data-offer-id="${o.id}" data-offer-status="declined">Guest declined</button>`:o.status==='accepted'?`<button class="small" data-offer-id="${o.id}" data-offer-status="fulfilled">Mark fulfilled</button>`:''}</div></div>`).join('')}</section>`;
 situation+=`<details><summary>Previous stays & preferences</summary>${g.history.map(h=>`<div class="history-row"><b>${esc(h.property)}</b><p>${esc(h.issue)}</p><p>Historical review estimate ${h.expected}/5 · Actual review rating ${h.actual}/5</p><p>${esc(h.sentiment)}</p><p>${esc(S.data.offers[h.offer]?.label||h.offer)} · ${h.accepted?'accepted':'declined'}</p></div>`).join('')||'<p class="quiet">No previous stays recorded. Estimates rely on category and property patterns.</p>'}<p class="fineprint">Seeded examples, not real guest records. Historical differences do not prove that an offer caused a rating change.</p></details>`;
 if(!issues.some(open))actions+=`<details><summary>Record actual stay outcome</summary>${outcome?`<p>Actual review rating ${outcome.rating}/5 · ${esc(outcome.sentiment)}</p><p>${esc(outcome.review)}</p><p class="quiet">Estimated Stay Score before recording: ${outcome.expected_before_outcome.low}–${outcome.expected_before_outcome.high} / 100 (demo)</p>`:`<form id="outcome" class="formgrid"><label>Actual review rating<select name="rating">${[1,2,3,4,5].map(v=>`<option>${v}</option>`).join('')}</select></label><label>Review sentiment<select name="sentiment"><option>Positive</option><option>Mixed</option><option>Negative</option></select></label><label>Review text (optional)<textarea name="review" maxlength="2000"></textarea></label><button type="submit">Save actual outcome</button></form>`}</details>`;
 const body=`<div class="guest-layout"><section class="guest-situation" aria-labelledby="situation-title"><h3 class="guest-section-title" id="situation-title">Situation</h3>${situation}</section><section class="guest-actions" aria-labelledby="actions-title"><h3 class="guest-section-title" id="actions-title">Actions</h3>${actions}</section></div>`;
 panel(`Room ${g.room} · ${esc(g.name)}`,body,'Guest experience',{mode:'guest',id,revision:S.data.revision});
}
function createPanel(){panel('Report an issue',`<form id="report" class="formgrid"><label>Room<select name="guest_id">${Object.values(S.data.guests).map(g=>`<option value="${g.id}">${g.room} · ${esc(g.name)}</option>`).join('')}</select></label><label>What needs attention?<textarea name="description" id="description" required minlength="3" maxlength="500" placeholder="For example: AC runs but the room stays warm"></textarea></label><label>Issue type · suggested from your description<select name="category" id="category">${Object.entries(S.data.categories).map(([key,c])=>`<option value="${key}">${esc(c.label)} · ${esc(c.team)}</option>`).join('')}</select></label><details><summary>Add a useful note</summary><textarea name="note" maxlength="500" placeholder="Anything the worker should know" aria-label="Worker note"></textarea></details><button class="primary" type="submit">Add & review dispatch →</button><p class="fineprint">Guest context is loaded from the room. No worker is assigned until you approve.</p></form>`,'Agent workspace',{mode:'create'});}
function editPanel(id){const t=S.data.issues.find(t=>t.id===id);panel('Edit issue details',`<form id="edit" class="formgrid"><label>Description<textarea name="description" required minlength="3" maxlength="500">${esc(t.description)}</textarea></label><label>Worker note<textarea name="note" maxlength="500">${esc(t.note)}</textarea></label><button class="primary" type="submit">Save details</button></form>`,t.id,{mode:'edit',id,version:t.version});}
function about(){panel('A model we can improve.',`<p>Eisen estimates how an unresolved issue affects a guest’s stay, using an issue-specific decay curve, sample property patterns, and guest sensitivity.</p><p>The board uses priority 1 (highest) through 5 (lowest), with provisional Eisen thresholds. Stay Score is out of 100. Demo weights remain provisional pending hotel calibration. The board balances additional harm from delay with severe combined stay experiences. Active water leaks take precedence. A worker already travelling or working is not interrupted.</p><p>Dispatch compares completion time and the estimated extra harm to other queued jobs. The agent approves assignments. Upcoming stacks then reorder by live priority; work already started or being travelled to stays protected.</p><p>Recovery offers come from an illustrative capped catalog. Only fulfilled gestures affect the scenario estimate; no offer is assumed to erase the harm.</p><details><summary>Sample property evidence</summary>${S.data.property_history.map(h=>`<p>${h.count} sample incidents · ${esc(h.summary)}</p>`).join('')}</details><p class="fineprint">${esc(S.data.model)} · All parameters, histories, and recovery effects are illustrative. This MVP does not claim validated forecasts, causal compensation effects, or official Hilton eligibility. Predictions and actions are saved for later evaluation.</p>`,'About estimates',{mode:'about'});}
async function mutate(body,message,after){
 if(S.busy)return;S.busy=true;document.querySelectorAll('button[type="submit"],#panel button[data-assign],button[data-progress],button[data-offer]').forEach(b=>b.disabled=true);
 try{const result=await api('/api/action',body);await refresh();if(after)await after(result);else{$('#panel').close();S.panel=null;}toast(message);}
 catch(e){toast(e.message);await refresh();if(S.panel?.mode==='job')await jobPanel(S.panel.id);else if(S.panel?.mode==='guest')guestPanel(S.panel.id);}
 finally{S.busy=false;document.querySelectorAll('button:disabled').forEach(b=>b.disabled=false);}
}
document.addEventListener('click',async event=>{
 const b=event.target.closest('button');if(!b||b.disabled)return;const d=b.dataset;
 if(d.tab){S.tab=d.tab;render();return;}if(d.filter){S.filter=d.filter;render();return;}
 if(d.job){await jobPanel(d.job);return;}if(d.guest){guestPanel(d.guest);return;}if(d.edit){editPanel(d.edit);return;}
 if(d.sort){if(S.sortBy[S.tab]===d.sort)S.sortDirection[S.tab]*=-1;else{S.sortBy[S.tab]=d.sort;S.sortDirection[S.tab]=d.sort==='elapsed'?-1:1;}render();return;}
 if(d.action==='close'){$('#panel').close();S.panel=null;return;}
 if(d.action==='retry'){await refresh();return;}
 if(d.action==='create'){createPanel();return;}if(d.action==='model'){about();return;}
 if(d.action==='dismiss'){S.alert='';render();return;}
 if(d.action==='history'){S.history=!S.history;render();return;}
 if(d.action==='advance'){await mutate({action:'advance'},'Demo clock advanced. Work is still completed by workers.');return;}
 if(d.assign){const p=S.panel;await mutate({action:'assign',id:p.id,version:p.rec.version,revision:p.rec.revision,worker_id:d.assign,position:Number(d.position)},'Assignment approved. The worker’s page will update.');return;}
 if(d.unassign){const t=S.data.issues.find(t=>t.id===d.unassign);await mutate({action:'unassign',id:t.id,version:t.version},'Returned to the unassigned pool.');return;}
 if(d.reorder){const t=S.data.issues.find(t=>t.id===d.reorder);await mutate({action:'reorder',id:t.id,version:t.version,revision:S.data.revision,direction:Number(d.dir)},'Queue updated. Current work is protected.');return;}
 if(d.progress){const t=S.data.issues.find(t=>t.id===d.progress);await mutate({action:d.step,id:t.id,version:t.version},d.step==='done'?'Job complete. Check your updated stack.':d.step==='head'?'Heading to the job.':'Work started.');return;}
 if(d.offer){await mutate({action:'offer',guest_id:d.guestId,kind:d.offer,revision:S.panel.revision},'Recovery offer approved.',()=>guestPanel(d.guestId));return;}
 if(d.offerId){const id=S.panel.id;await mutate({action:'offer_status',offer_id:d.offerId,status:d.offerStatus},'Recovery updated.',()=>guestPanel(id));}
});
document.addEventListener('input',event=>{
 if(event.target.id==='search'){S.search=event.target.value;render();}
 if(event.target.id==='description'&&!$('#category').dataset.manual){const text=event.target.value.toLowerCase();const type=/leak|flood/.test(text)?'leak':/towel|linen|bedding|pillow/.test(text)?'linen':/clean|dirty|stain|smell/.test(text)?'clean':/shower|toilet|water|drain/.test(text)?'water':/lamp|light|tv|socket/.test(text)?'light':'ac';$('#category').value=type;}
});
document.addEventListener('change',e=>{if(e.target.id==='category')e.target.dataset.manual='1';if(e.target.id==='worker-select')location.href='/worker.html?worker='+encodeURIComponent(e.target.value);});
document.addEventListener('submit',async event=>{
 event.preventDefault();const form=event.target,values=Object.fromEntries(new FormData(form));
 if(form.id==='report'){await mutate({action:'create',...values},'Issue added. Review the dispatch recommendation.',async r=>jobPanel(r.id));return;}
 const p=S.panel;
 if(form.id==='edit'){await mutate({action:'edit',id:p.id,version:p.version,...values},'Details saved.',()=>jobPanel(p.id));return;}
 if(form.id==='reopen'){await mutate({action:'reopen',id:p.id,version:p.version,...values},'Issue reopened with its history intact.',()=>jobPanel(p.id));return;}
 if(form.id==='outcome'){await mutate({action:'outcome',guest_id:p.id,...values,rating:Number(values.rating)},'Actual outcome recorded.',()=>guestPanel(p.id));}
});
$('#panel').addEventListener('close',()=>{S.panel=null;});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&S.data)refresh();});
refresh();setInterval(tickClock,250);setInterval(()=>{if(!document.hidden&&!S.busy)refresh();},2500);
