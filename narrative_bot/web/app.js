'use strict';
const $=id=>document.getElementById(id);
const labels={pending:'Pendiente',sent:'Aceptada por Telegram',sending:'En curso',failed:'Error',uncertain:'Resultado incierto',skipped:'Saltado',acknowledged:'Resuelta por el anfitrión'};
let state=null,selected=null,gameId=null,busy=false,currentView='overview';
const openMessages=new Set();
const roleChoices=new Map();
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function showView(view){currentView=view;for(const v of ['overview','people','phases'])$('view-'+v).hidden=v!==view;document.querySelectorAll('[data-view]').forEach(b=>{if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});$('view-title').textContent={overview:'Partida',people:'Asignaciones',phases:'Mensajes'}[view];history.replaceState(null,'','#'+view);}
function render(data){
 state=data;const g=data.game;
 if(gameId!==g?.id){gameId=g?.id;selected=g?.phase??0;openMessages.clear();}
 $('assignment-state').textContent=g&&g.status!=='finished'?(g.assignments_open?'Asignación pendiente':'Asignación completada') : '';
 $('story-title').textContent=data.draft?.title||g?.title||'Todavía no hay una historia preparada.';
 $('phase-title').textContent=g?(g.status==='finished'?'Partida terminada':g.phase===0?'Preparación':`Fase ${g.phase} · ${data.phases.find(p=>p.number===g.phase)?.title||''}`):'Preparar partida';
 const story=data.messages.filter(m=>m.phase>0),done=story.filter(m=>m.status==='completed').length,skipped=story.filter(m=>m.status==='skipped').length;
 $('progress').replaceChildren();for(const [n,cls] of [[done,'done'],[skipped,'skipped']]){const part=el('span',undefined,cls);part.style.width=`${story.length?100*n/story.length:0}%`;$('progress').append(part);}
 $('progress').setAttribute('aria-label',`${done} completados, ${skipped} saltados de ${story.length}`);
 $('progress-text').textContent=g?`${done} de ${story.length} mensajes completados${skipped?` · ${skipped} saltados`:''}`:'';
 $('main-action').disabled=!g&&!data.draft;
 $('main-action').textContent=data.draft?'Iniciar partida':!g?'Esperando historia':g.status==='finished'?'Volver a jugar':g.phase===0?(g.assignments_open?'Ver asignaciones':'Iniciar partida'):'Ver mensajes';
 $('next-step').textContent=data.draft?`${data.draft.characters} personajes · ${data.draft.phases} fases. No se enviarán mensajes al iniciar.`:g?.status==='finished'?'Puedes volver a jugar con la misma historia.':g?.phase===0?(g.assignments_open?'Asigna y confirma los personajes en Asignaciones.':'Siguiente paso: iniciar la fase 1 y enviar el mensaje de bienvenida.'):g?'Los envíos se autorizan desde Telegram.':'';
 $('close-game').hidden=!g||g.status==='finished';
 renderPeople(data);renderMessages(data);
}
function renderPeople(data){
 $('confirm-roles').hidden=!data.game?.assignments_open;
 $('confirm-roles').disabled=!data.players.length||data.players.some(p=>p.person_id===null);
 $('people-list').replaceChildren(...(data.people||[]).map(p=>{
  const c=data.players.find(c=>c.code===p.code),row=el('div',undefined,'person'),info=el('div',undefined,'person-info');
  info.append(el('div',`${p.name} → ${c?c.character:'Sin personaje'}`,'person-name'),el('div',`Telegram · ID ${p.id}`,'telegram-id'));
  const remove=el('button','Quitar');remove.disabled=!!c&&data.game?.status!=='finished';
  remove.title=remove.disabled?'Libera el personaje o termina la partida.':'Quitar de la lista';
  remove.addEventListener('click',()=>{actionRequest={action:'remove_person',person:p.id,game:data.game?.id||0,revision:data.game?.revision||0,confirmed:true};$('confirm-title').textContent=`¿Quitar a ${p.name}?`;$('confirm-description').textContent='Podrá volver enviando /start. El historial se conserva.';$('confirm-pending').textContent='';$('execute-action').textContent='Sí, quitar';$('action-error').textContent='';$('confirm-action').showModal();});
  row.append(info);
  if(data.game?.assignments_open){
   if(c){
    const release=el('button','Liberar');release.addEventListener('click',()=>confirmRole('unassign',p,c,data));row.append(release);
   }else{
    const select=el('select');select.className='role-select';select.setAttribute('aria-label','Personaje para '+p.name);
    const placeholder=el('option','Elegir personaje');placeholder.value='';select.append(placeholder);
    for(const role of data.players.filter(r=>r.person_id===null)){const option=el('option',role.character+(role.planned_person?' · Previsto: '+role.planned_person:''));option.value=role.code;select.append(option);}
    select.value=roleChoices.get(p.id)||'';
    const assign=el('button','Asignar','primary');assign.disabled=!select.value;
    select.addEventListener('change',()=>{roleChoices.set(p.id,select.value);assign.disabled=!select.value;});
    assign.addEventListener('click',()=>{const role=data.players.find(r=>r.code===select.value);if(role)confirmRole('assign',p,role,data);});
    row.append(select,assign);
   }
  }
  row.append(remove);return row;
 }));
 if(!data.people?.length)$('people-list').append(el('p','Para aparecer aquí, envía /start al bot.'));
 const free=data.players.filter(p=>p.person_id===null).map(p=>p.character+(p.planned_person?' (previsto: '+p.planned_person+')':''));$('unassigned').textContent=data.game&&!data.game.assignments_open&&data.game.status!=='finished'?'Personajes confirmados. No se pueden cambiar hasta terminar la partida.':free.length?'Personajes sin asignar: '+free.join(', '):'';
}
function phaseState(data,number){
 const rows=data.messages.filter(m=>m.phase===number),done=rows.filter(m=>m.status==='completed').length;
 const skipped=rows.filter(m=>m.status==='skipped').length;
 const attention=rows.some(m=>m.deliveries.some(d=>['failed','uncertain','acknowledged'].includes(d.status)));
 const status=number>(data.game?.phase??0)?'Sin iniciar':attention?'Necesita atención':rows.length&&done===rows.length?'Completada':skipped?'Cerrada con mensajes saltados':data.game?.status==='finished'?'Cerrada sin completar':'Pendiente';
 return `${status} · ${done}/${rows.length} completados`;
}
function renderMessages(data){
 $('phase-state').textContent=data.game?phaseState(data,Number(selected)):'';
 $('phase-select').replaceChildren(...data.phases.map(p=>{const o=el('option',(p.number===0?'Fichas privadas':`Fase ${p.number} · ${p.title}`)+' — '+phaseState(data,p.number));o.value=p.number;return o;}));$('phase-select').value=selected;
 const messages=data.messages.filter(m=>m.phase===Number(selected));
 $('messages').replaceChildren(...messages.map(m=>{
  const key=`${gameId}:${m.phase}:${m.position}`,row=el('details',undefined,'message');row.open=openMessages.has(key);
  row.addEventListener('toggle',()=>{if(!row.isConnected)return;if(row.open)openMessages.add(key);else openMessages.delete(key);});
  const sent=m.status==='completed'&&m.deliveries.length>0&&m.deliveries.every(d=>d.status==='sent');
  const attention=m.status==='skipped'||m.deliveries.some(d=>['failed','uncertain','acknowledged'].includes(d.status));
  const summary=el('summary');summary.append(el('span',`${m.position}. ${m.title}`,'message-title'),el('span',sent?'Enviado':attention?'Necesita atención':'Pendiente',`badge ${sent?'sent':attention?'attention':''}`));row.append(summary);
  row.append(el('div',`Para: ${m.recipients}`,'delivery'));
  if(m.status==='skipped')row.append(el('div','Mensaje saltado. No se enviará.','delivery'));
  for(const d of m.deliveries){const p=data.players.find(p=>p.code===d.code);row.append(el('div',`${p?.name||d.code} · ${labels[d.status]||d.status}${d.read_at?' · ✅ Lectura confirmada':d.status==='sent'?' · Lectura sin confirmar':''}${d.error?' · '+d.error:''}`,'delivery'));}
  if(!m.deliveries.length)row.append(el('div','Los destinatarios se fijarán al abrir la fase.','delivery'));
  return row;
 }));
 if(!messages.length)$('messages').append(el('p',data.game?'Todavía no hay mensajes en esta fase.':'Primero prepara una partida.'));
}
async function refresh(){if(busy)return;busy=true;try{const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error();render(await r.json());$('error').hidden=true;$('connection').textContent='Actualizado';}catch(e){$('connection').textContent='Sin conexión';$('error').textContent='No se pudo actualizar. Los datos pueden estar desactualizados.';$('error').hidden=false;}finally{busy=false;}}
let actionRequest=null;
function confirmAction(action){
 if(!state?.game)return;
 const g=state.game;
 actionRequest={action,game:g.id,revision:g.revision,confirmed:true};
 $('execute-action').textContent=action==='close'?'Sí, terminar':'Sí, reiniciar';
 $('confirm-title').textContent=action==='close'?'¿Seguro que quieres terminar esta partida?':'¿Reiniciar desde cero?';
 $('confirm-description').textContent=action==='close'?'La partida se cerrará y podrás importar otra historia. No se enviarán mensajes.':'Se cerrará esta partida y se creará otra con la MISMA historia, sin personajes asignados ni entregas. Los usuarios registrados seguirán disponibles. No se enviarán mensajes.';
 const pending=state.messages.filter(m=>m.status==='pending');
 $('confirm-pending').textContent=pending.length?'Mensajes incompletos que se marcarán como saltados:\n'+pending.map(m=>`Fase ${m.phase} · ${m.position}. ${m.title}\n`+m.deliveries.filter(d=>!['sent','acknowledged'].includes(d.status)).map(d=>`  ${d.code}: ${labels[d.status]||d.status}`).join('\n')).join('\n'):'No hay mensajes iniciados pendientes.';
 $('action-error').textContent='';$('confirm-action').showModal();
}
function startDraft(){
 if(!state?.draft)return;
 actionRequest={action:'start',game:state.game?.id||0,revision:state.game?.revision||0,draft:state.draft.id,confirmed:true};
 $('confirm-title').textContent='¿Preparar esta nueva partida?';
 $('confirm-description').textContent=`${state.draft.title} · ${state.draft.characters} personajes · ${state.draft.phases} fases`;
 $('confirm-pending').textContent='Después, asigna los personajes y autoriza las fichas desde Telegram. No se enviará ningún mensaje al confirmar.';
 $('execute-action').textContent='Sí, iniciar';$('action-error').textContent='';$('confirm-action').showModal();
}
$('close-game').addEventListener('click',()=>confirmAction('close'));

$('cancel-action').addEventListener('click',()=>$('confirm-action').close());
$('execute-action').addEventListener('click',async()=>{
 if(!actionRequest)return;
 $('execute-action').disabled=true;
 try{
  const res=await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(actionRequest)});
  const data=await res.json();if(!res.ok)throw Error(data.error||'No se pudo completar la operación.');
  if(actionRequest.action==='begin')selected=1;actionRequest=null;$('confirm-action').close();await refresh();
 }catch(e){$('action-error').textContent=e.message+' Cierra esta ventana y actualiza antes de volver a confirmar.';}
 finally{$('execute-action').disabled=false;}
});


$('main-action').addEventListener('click',()=>{if(state?.draft)startDraft();else if(state?.game?.status==='finished')confirmAction('restart');else if(state?.game?.phase===0&&!state.game.assignments_open)confirmBegin();else showView(state?.game?.phase===0?'people':'phases');});
$('phase-select').addEventListener('change',e=>{selected=Number(e.target.value);if(state)renderMessages(state);});
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>showView(b.dataset.view)));
showView(['overview','people','phases'].includes(location.hash.slice(1))?location.hash.slice(1):'overview');
refresh();setInterval(refresh,5000);

function confirmRole(action,person,role,data){
 actionRequest={action,person:person.id,code:role.code,game:data.game.id,revision:data.game.revision,confirmed:true};
 $('confirm-title').textContent=action==='assign'?`¿Asignar ${role.character} a ${person.name}?`:`¿Liberar a ${person.name} de ${role.character}?`;
 $('confirm-description').textContent='No se enviará ninguna ficha ni mensaje.';
 $('confirm-pending').textContent='';$('execute-action').textContent=action==='assign'?'Sí, asignar':'Sí, liberar';$('action-error').textContent='';$('confirm-action').showModal();
}

$('confirm-roles').addEventListener('click',()=>{
 if(!state?.game?.assignments_open)return;
 actionRequest={action:'confirm_roles',game:state.game.id,revision:state.game.revision,confirmed:true};
 $('confirm-title').textContent='¿Confirmar todos los personajes?';
 $('confirm-description').textContent='Las asignaciones quedarán bloqueadas hasta terminar la partida. No se enviará ningún mensaje ahora.';
 $('confirm-pending').textContent=state.players.map(p=>`${p.name} → ${p.character}`).join('\n');
 $('execute-action').textContent='Sí, confirmar personajes';$('action-error').textContent='';$('confirm-action').showModal();
});

function confirmBegin(){
 const g=state.game,preview=state.first_message;
 if(!preview){$('error').hidden=false;$('error').textContent='Actualiza la página para ver el mensaje antes de iniciar.';return;}
 actionRequest={action:'begin',game:g.id,revision:g.revision,confirmed:true};
 $('confirm-title').textContent='¿Iniciar la partida?';
 $('confirm-description').textContent='Se abrirá la fase 1 y se enviará su primer mensaje. Los siguientes mensajes se enviarán cuando los autorices.';
 $('confirm-pending').textContent=`${preview.title}\nPara: ${preview.recipients}\n\n${preview.text}`;
 $('execute-action').textContent='Sí, iniciar y enviar';$('action-error').textContent='';$('confirm-action').showModal();
}
