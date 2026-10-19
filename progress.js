(() => {
  const $ = s => document.querySelector(s), form = $('#prForm');
  const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const headers = () => ({'X-Admin-Key':localStorage.getItem('xle-admin') || ''});
  const fileSize = n => n<1024 ? n+' bytes' : n<1024*1024 ? (n/1024).toFixed(1)+' KB' : (n/1024/1024).toFixed(2)+' MB';
  const syncMessage = (text,state='') => {const el=$('#prSync');if(!el)return;const span=el.querySelector('span');if(span&&span.textContent!==text)span.textContent=text;el.className='sync '+(state==='connected'?'ok':state==='error'?'bad':'');};
  let items = [], matched = new Set(), admin = false, showReportIds = false, exportAll = false, auditAll = false, request = 0, timer;
  let pendingLoads = 0, lastSnapshot = '', taskFilter = '';
  let taskOptions = [];
  const draftFields = () => JSON.stringify(['reporter','subject','content'].map(k=>form.elements[k].value.trim()));
  let submittedFields = draftFields(), skipLeaveOnce=false;
  const hasDraft = () => !form.hidden && (draftFields()!==submittedFields || form.elements.files.files.length>0);
  const mayLeave = async () => !hasDraft() || !!(await xleDialog({title:'尚未送出的回報',message:'目前填寫的內容與附件不會自動儲存。確定放棄並離開嗎？',danger:true,label:'放棄草稿'}));
  const showForm = () => {form.hidden=false;$('#prNew').hidden=true;};
  const hideForm = () => {form.hidden=true;$('#prNew').hidden=false;};
  const resetForm = () => {form.reset();cancel();submittedFields=draftFields();$('#prUploadSize').textContent='';hideForm();};
  window.addEventListener('beforeunload',e=>{if(hasDraft()){e.preventDefault();e.returnValue='';}});
  window.addEventListener('xle-before-view-change',e=>{
    if(e.detail.from!=='progress'||e.detail.to==='progress')return;
    if(skipLeaveOnce){skipLeaveOnce=false;return;}
    if(!hasDraft()){hideForm();return;}
    e.preventDefault();
    const target=e.detail.to;
    mayLeave().then(ok=>{if(ok){resetForm();skipLeaveOnce=true;document.querySelector('.tabs [data-view="'+target+'"]')?.click();}});
  });
  $('#prNew').onclick=()=>{resetForm();showForm();form.elements.reporter.focus();};
  const date = s => new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(s));
  async function api(url,options={}) {
    const readTimeout = !options.method || options.method==='GET' ? {signal:AbortSignal.timeout(15000)} : {};
    const response = await fetch(url,{cache:'no-store',...readTimeout,...options});
    const data = await response.json();
    if(!response.ok) throw Error(data.error || '操作失敗');
    return data;
  }
  const showId = () => admin || showReportIds;
  async function loadTasks(){
    try {
      const d=await api('/api/tasks/options');
      taskOptions=d.items||[];
      const sel=$('#prTask'),flt=$('#prTaskFilter');
      const old=sel.value,oldFilter=flt.value;
      const options='<option value="">不關聯工作項目</option>'+taskOptions.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.name)+'</option>').join('');
      $('#prExportTask').innerHTML=taskOptions.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.name)+'</option>').join('');
      sel.innerHTML=options; sel.value=old;
      flt.innerHTML='<option value="">全部工作</option><option value="__none">未關聯工作</option>'+taskOptions.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.name)+'</option>').join('');
      flt.value=oldFilter||taskFilter;
    } catch(e){console.warn('工作項目載入失敗',e);}
  }
  function card(r) {
    const files=r.files||[];
    return `<article class="blk pr-report ${r.status==='void'?'pr-void':''}" id="report-${r.id}">
      <div class="pr-report-head"><div><h3>${esc(r.subject)} · 第 ${r.version} 次回報</h3><p class="muted">${esc(date(r.created))}${r.parent_id?' · 接續第 '+(r.version-1)+' 次回報':''}${showId()?' · 回報編號 #'+r.id:''}</p><p class="muted">回報人：${esc(r.reporter)}　｜　關聯工作：${esc(r.task_display||'未關聯')}</p></div><span class="tag">${r.status==='valid'?'有效':'已作廢'}</span></div>
      <div class="pr-report-section"><h4>回報內容</h4><div class="pr-content">${esc(r.content)||'（無文字內容）'}</div>${r.status==='void'? `<p class="pr-reason">作廢原因：${esc(r.void_reason)}<br>${esc(date(r.void_at))}</p>`:''}</div>
      <div class="pr-report-section"><h4>附件（${files.length} 個）</h4><ul class="pr-files">${files.map(f=>`<li>${f.removed_at?`<span>${esc(f.name)}（已移除：${esc(f.reason)}）</span>`:`<a href="${f.url}">${esc(f.name)}</a><span class="muted">${fileSize(f.size)}</span>${admin?`<button class="btn ghost" data-remove="${f.id}" data-report="${r.id}">移除附件</button>`:''}`}</li>`).join('')||'<li class="muted">沒有附件</li>'}</ul></div>
      <div class="pr-report-section"><h4>回報操作</h4><div class="pr-actions">
      ${r.status==='valid'?`<button class="btn ghost" data-continue="${r.id}">接續回報</button>`:''}
      ${admin?`<button class="btn ghost" data-relink="${r.id}">修正工作關聯</button>`:''}
      ${(admin||exportAll)?`<button class="btn ghost" data-export="${r.id}">匯出本筆</button>`:''}
      ${admin?(r.status==='valid'?`<button class="btn ghost" data-void="${r.id}">作廢</button>`:`<button class="btn ghost" data-restore="${r.id}">恢復有效</button>`):''}
      ${(admin||auditAll)?`<button class="btn ghost" data-audit="${r.id}">操作紀錄</button>`:''}
      ${admin?`<button class="btn ghost pr-danger-action" data-trash="${r.id}">移至垃圾桶</button>`:''}
      </div><div class="pr-audit" data-audit-list="${r.id}"></div></div></article>`;
  }
  function render() {
    const closed = new Set([...$('#prItems').querySelectorAll('.pr-topic:not([open])')].map(el=>el.dataset.root));
    const asc=$('#prSort').value==='asc', sorter=(a,b)=>(asc?1:-1)*(a.id-b.id);
    const shown=items.filter(r=>matched.has(r.id) && (!taskFilter || (taskFilter==="__none"?!r.task_id:r.task_id===taskFilter)));
    $('#prCount').textContent=`符合 ${shown.length} 筆回報；主題檢視會保留完整版本歷程。`;
    if($('#prView').value==='time') $('#prItems').innerHTML=shown.sort(sorter).map(card).join('');
    else {
      const groups=new Map();
      items.filter(r=>!taskFilter || (taskFilter==="__none"?!r.task_id:r.task_id===taskFilter)).forEach(r=>{if(!groups.has(r.root_id))groups.set(r.root_id,[]);groups.get(r.root_id).push(r);});
      $('#prItems').innerHTML=[...groups.values()].sort((a,b)=>sorter(a.at(-1),b.at(-1))).map(g=>{
        const latest=g.at(-1);
        return `<details class="pr-topic" data-root="${latest.root_id}" ${closed.has(String(latest.root_id))?'':'open'}><summary>${esc(latest.subject)} <span class="muted">· 共 ${g.length} 次回報 · 最近 ${esc(date(latest.created))}</span></summary>${g.sort(sorter).map(card).join('')}</details>`;
      }).join('');
    }
    if(!shown.length) $('#prItems').innerHTML='<p class="muted">沒有符合條件的回報。</p>';
  }
  async function load(background=false) {
    if(background===true && pendingLoads)return;
    pendingLoads++;
    if(!background && !lastSnapshot && visible())syncMessage('連線中…','syncing');
    const seq=++request;
    try {
      const query=new URLSearchParams({q:$('#prSearch').value,reporter:$('#prReporter').value,status:$('#prStatus').value});
      const d=await api('/api/progress?'+query,{headers:headers()});
      if(seq!==request)return;
      const snapshot=JSON.stringify(d);
      if(snapshot!==lastSnapshot){
        items=d.items; matched=new Set(d.matched_ids); admin=d.admin; showReportIds=!!d.show_report_ids; exportAll=!!d.export_all; auditAll=!!d.audit_all;
        if(auditPermission && admin && document.activeElement!==auditPermission)auditPermission.checked=auditAll;
        $('#prExportPanel').hidden=!(admin||exportAll);
        $('#prTrashOpen').hidden=!admin;
        $('#prTrashCount').textContent=admin?'（'+(d.trash_count||0)+'）':'';
        if(!admin)$('#prTrashPanel').hidden=true;
        if(exportPermission && admin && document.activeElement!==exportPermission)exportPermission.value=exportAll?'all':'admin';
        if(settingsToggle && admin && document.activeElement!==settingsToggle)settingsToggle.checked=showReportIds;
        const selected=$('#prReporter').value;
        $('#prReporter').innerHTML='<option value="">全部姓名</option>'+d.reporters.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');
        $('#prReporter').value=selected; render();lastSnapshot=snapshot;
      }
      const clock=new Date().toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
      syncMessage('已連線・全組即時同步（最後同步 '+clock+'）','connected');
    } catch(e) {
      if(seq===request)syncMessage('連線中斷，正在重試…','error');
    } finally {pendingLoads--;}
  }
  function cancel() {
    form.elements.parent_id.value=''; form.elements.subject.readOnly=false;form.elements.task_id.disabled=false;
    $('#prFormTitle').textContent='新增回報'; $('#prParentHint').textContent='';
  }
  $('#prCancel').onclick=async()=>{if(await mayLeave())resetForm();};
  form.elements.files.onchange=()=>{
    const files=[...form.elements.files.files],size=files.reduce((n,f)=>n+f.size,0);
    $('#prUploadSize').textContent=`已選擇 ${files.length} / 20 個檔案，合計 ${(size/1024/1024).toFixed(2)} / 50 MB`;
  };
  form.onsubmit=async e=>{
    e.preventDefault(); const button=form.querySelector('[type=submit]');
    const files=[...form.elements.files.files];
    if(files.length>20 || files.reduce((n,f)=>n+f.size,0)>50*1024*1024){$('#prMessage').textContent='每筆最多 20 個附件，合計上限 50MB';return;}
    if(!form.elements.content.value.trim()){ $('#prMessage').textContent='請填寫回報內容';form.elements.content.focus();return; }
    const linked=taskOptions.find(t=>t.id===form.elements.task_id.value);
    button.disabled=true;
    try{
      const size=files.reduce((n,f)=>n+f.size,0);
      const confirmed=await xleDialog({title:'確認送出進度回報',message:'回報人：'+form.elements.reporter.value+'\n回報主題：'+form.elements.subject.value+'\n關聯工作：'+(linked?linked.name:'未關聯工作')+'\n\n回報內容：\n'+form.elements.content.value+'\n\n附件：'+files.length+' 個，合計 '+fileSize(size)+'\n送出後無法修改原始內容，後續請使用接續回報。',label:'確認送出'});
      if(!confirmed)return;
    }catch(e){$('#prMessage').textContent='無法開啟確認視窗：'+e.message;return;}
    finally{button.disabled=false;}
    const body=new FormData(form);
    if(form.elements.parent_id.value)body.set('task_id',form.elements.task_id.value);
    button.disabled=true; $('#prMessage').textContent='上傳並儲存中，請勿重複送出…';
    try {
      const d=await api('/api/progress',{method:'POST',body});
      resetForm();
      $('#prMessage').textContent=`已送出第 ${d.version} 次回報${showId()?'（#'+d.id+'）':''}`; await load();
    } catch(e) {$('#prMessage').textContent=e.message+'；若連線中斷，請先重新整理確認是否已建立，避免重複送出。';}
    finally {button.disabled=false;}
  };
  $('#prItems').onclick=async e=>{
    const b=e.target.closest('button'); if(!b)return;
    if(b.dataset.export){await doExport('single',Number(b.dataset.export));return;}
    if(b.dataset.continue){
      const r=items.find(x=>x.id===Number(b.dataset.continue));
      if(!r || r.status!=='valid')return;
      if(!await mayLeave())return;
      resetForm();showForm();
      form.elements.parent_id.value=r.id; form.elements.subject.value=r.subject;form.elements.subject.readOnly=true;
      form.elements.task_id.value=r.task_id||'';form.elements.task_id.disabled=true;
      form.elements.content.value='';form.elements.files.value='';$('#prUploadSize').textContent='';
      submittedFields=draftFields();
      $('#prFormTitle').textContent='接續第 '+r.version+' 次回報';$('#prParentHint').textContent='同一主題下新增回報，保留接續來源；舊附件不會帶入。';
      form.scrollIntoView({behavior:'smooth'});form.elements.reporter.focus();return;
    }
    b.disabled=true;
    try {
      if(b.dataset.trash){
        const r=items.find(x=>x.id===Number(b.dataset.trash));
        const reason=await xleDialog({title:'移至垃圾桶',message:'回報：'+(r?.subject||'')+' · 第 '+(r?.version||'')+' 次回報\n回報與附件將從一般列表隱藏，管理員可以在垃圾桶還原。',kind:'reason',requireReason:true,label:'下一步'});
        if(reason===null)return;
        const ok=await xleDialog({title:'確認移至垃圾桶',message:'確定移動此筆回報嗎？此操作不會永久刪除資料或附件。',label:'移至垃圾桶',danger:true});
        if(!ok)return;
        await api('/api/progress/'+b.dataset.trash+'/trash',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({reason})});
        await load();return;
      }
      if(b.dataset.relink){
        const r=items.find(x=>x.id===Number(b.dataset.relink));
        const chosen=await xleDialog({title:'修正關聯工作',message:'請選擇正確的工作主題',options:[{value:'',label:'不關聯工作'}].concat(taskOptions.map(t=>({value:t.id,label:t.name}))),value:r?.task_id||'',label:'下一步'});
        if(chosen===null)return;
        const reason=await xleDialog({title:'修正原因',message:'此操作會保留關聯變更紀錄。',kind:'reason',requireReason:true,label:'確認修正'});
        if(reason===null)return;
        await api('/api/progress/'+b.dataset.relink+'/relink',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({task_id:chosen,reason})});
        await load();
      } else if(b.dataset.audit){
        const d=await api('/api/progress/'+b.dataset.audit+'/audit',{headers:headers()});
        document.querySelector(`[data-audit-list="${b.dataset.audit}"]`).innerHTML=d.items.map(a=>`<p>${esc(date(a.created))} · ${esc(a.action)} · ${esc(a.actor)} ${esc(a.reason)}</p>`).join('');
      } else if(b.dataset.void || b.dataset.remove || b.dataset.restore){
        const removing=!!b.dataset.remove;
        const reason=await xleDialog({title:b.dataset.restore?'恢復進度回報':removing?'永久移除附件':'作廢進度回報',message:b.dataset.restore?'請填寫恢復原因；已刪除的附件無法恢復。':removing?'檔案將永久移除，操作原因與紀錄會保留。':'原始回報會保留，並標示為已作廢。',kind:'reason',requireReason:true,ack:removing,danger:removing,label:removing?'確認永久移除':'確認'});
        if(reason===null)return;
        const rid=b.dataset.void || b.dataset.restore || b.dataset.report;
        const d=await api('/api/progress/'+rid+'/'+(b.dataset.void?'void':b.dataset.restore?'restore':'remove-file'),{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({reason,file_id:b.dataset.remove})});
        if(d.warning)await xleDialog({title:'操作提醒',message:d.warning,kind:'notice'}); await load();
      }
    } catch(e){await xleDialog({title:'操作失敗',message:e.message,kind:'notice'});} finally {b.disabled=false;}
  };
  async function loadTrash(){
    if(!admin)return;
    const panel=$('#prTrashItems');
    panel.textContent='讀取中…';
    try{
      const d=await api('/api/progress/trash',{headers:headers()});
      panel.innerHTML=d.items.length?d.items.map(r=>`<article class="pr-trash-item"><div><strong>${esc(r.subject)} · 第 ${r.version} 次回報</strong><p class="muted">回報人：${esc(r.reporter)} · 移除時間：${esc(date(r.trash_at))}</p><p>移除原因：${esc(r.trash_reason)}</p><p class="muted">附件：${r.files.length} 個 · 原狀態：${r.trash_previous_status==='void'?'已作廢':'有效'}</p></div><div class="pr-actions"><button class="btn ghost" data-untrash="${r.id}">還原</button><button class="btn ghost pr-danger-action" data-delete="${r.id}">永久刪除</button></div></article>`).join(''):'<p class="muted">垃圾桶目前沒有回報。</p>';
      $('#prDeletedAudit').innerHTML=d.deleted.map(r=>`<p class="muted">#${r.report_id} · ${esc(r.subject)} · ${esc(date(r.created))} · ${esc(r.reason)}</p>`).join('')||'<p class="muted">尚無永久刪除紀錄。</p>';
    }catch(e){panel.textContent='讀取垃圾桶失敗：'+e.message;}
  }
  $('#prTrashOpen').onclick=()=>{$('#prTrashPanel').hidden=false;loadTrash();$('#prTrashPanel').scrollIntoView({behavior:'smooth'});};
  $('#prTrashClose').onclick=()=>{$('#prTrashPanel').hidden=true;};
  $('#prTrashItems').onclick=async e=>{
    const b=e.target.closest('button');if(!b)return;
    b.disabled=true;
    try{
      const rid=b.dataset.untrash||b.dataset.delete;
      if(!rid)return;
      if(b.dataset.untrash){
        const reason=await xleDialog({title:'還原進度回報',message:'還原後會重新出現在進度回報列表，並恢復原本的有效或作廢狀態。',kind:'reason',requireReason:true,label:'確認還原'});
        if(reason===null)return;
        await api('/api/progress/'+rid+'/untrash',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({reason})});
      }else{
        const reason=await xleDialog({title:'永久刪除進度回報',message:'此操作會永久刪除回報內容與附件，無法還原。若有接續回報，系統會拒絕刪除。',kind:'reason',requireReason:true,label:'下一步',danger:true});
        if(reason===null)return;
        const confirmed=await xleDialog({title:'最後確認：永久刪除',message:'請確認要永久刪除此筆回報及其附件。僅保留管理員刪除稽核紀錄。',ack:true,danger:true,label:'確認永久刪除'});
        if(!confirmed)return;
        const d=await api('/api/progress/'+rid+'/delete',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({reason})});
        if(d.warning)await xleDialog({title:'清理提醒',message:d.warning,kind:'notice'});
      }
      await load();await loadTrash();
    }catch(err){await xleDialog({title:'操作失敗',message:err.message,kind:'notice'});}
    finally{b.disabled=false;}
  };
  $('#prSearch').oninput=()=>{clearTimeout(timer);timer=setTimeout(load,250);};
  ['prReporter','prStatus'].forEach(id=>$('#'+id).onchange=load);
  $('#prTaskFilter').onchange=()=>{taskFilter=$('#prTaskFilter').value;render();};
  ['prSort','prView'].forEach(id=>$('#'+id).onchange=render);

  $('[data-view="progress"]').addEventListener('click',()=>{loadTasks();load();});
  window.addEventListener('xle-progress-task',e=>{
    taskFilter=e.detail.openForm?'':e.detail.taskId;
    $('#prTaskFilter').value=taskFilter;
    if(e.detail.openForm){
      (async()=>{if(!await mayLeave())return;resetForm();showForm();form.elements.task_id.value=e.detail.taskId;form.scrollIntoView({behavior:'smooth'});})();
    }else render();
  });
  const exportPermission=$('#prExportPermission'),exportPermissionMsg=$('#prExportPermissionMsg');
  if(exportPermission)exportPermission.onchange=async()=>{
    exportPermission.disabled=true;exportPermissionMsg.textContent='儲存中…';
    try{
      await api('/api/progress/settings',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({export_all:exportPermission.value==='all'})});
      exportPermissionMsg.textContent='已儲存';await load();
    }catch(e){exportPermission.value=exportAll?'all':'admin';exportPermissionMsg.textContent='儲存失敗：'+e.message;}
    finally{exportPermission.disabled=false;}
  };
  $('#prExportScope').onchange=()=>{$('#prExportTaskWrap').hidden=$('#prExportScope').value!=='task';};
  async function doExport(scope,id=0){
    const msg=$('#prExportMsg'),button=$('#prExportGo');
    const payload={scope,format:$('#prExportFormat').value};
    if(scope==='single')payload.report_id=id;
    if(scope==='task')payload.task_id=$('#prExportTask').value;
    if(scope==='filtered')payload.ids=items.filter(r=>matched.has(r.id)&&(!taskFilter||(taskFilter==='__none'?!r.task_id:r.task_id===taskFilter))).map(r=>r.id);
    button.disabled=true;msg.textContent='正在整理 PDF 與附件，請稍候…';
    try{
      const response=await fetch('/api/progress/export',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if(!response.ok){let d;try{d=await response.json();}catch{}throw Error(d?.error||'匯出失敗');}
      const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');
      a.href=url;a.download='XLeRobot_進度回報.'+(payload.format==='pdf'?'pdf':'zip');
      document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
      msg.textContent='匯出完成';
    }catch(e){msg.textContent='匯出失敗：'+e.message;}
    finally{button.disabled=false;}
  }
  $('#prExportGo').onclick=()=>doExport($('#prExportScope').value);
  const auditPermission=$('#prAuditPermission'),auditPermissionMsg=$('#prAuditPermissionMsg');
  if(auditPermission)auditPermission.onchange=async()=>{
    auditPermission.disabled=true;auditPermissionMsg.textContent='儲存中…';
    try{
      await api('/api/progress/settings',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({audit_all:auditPermission.checked})});
      auditPermissionMsg.textContent='已儲存';await load();
    }catch(e){auditPermission.checked=!auditPermission.checked;auditPermissionMsg.textContent='儲存失敗：'+e.message;}
    finally{auditPermission.disabled=false;}
  };
  const settingsToggle=$('#progressShowIds'),settingsMsg=$('#progressShowIdsMsg');
  if(settingsToggle)settingsToggle.onchange=async()=>{
    settingsToggle.disabled=true;settingsMsg.textContent='儲存中…';
    try{
      await api('/api/progress/settings',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({show_report_ids:settingsToggle.checked})});
      settingsMsg.textContent='已儲存';await load();
    }catch(e){settingsToggle.checked=!settingsToggle.checked;settingsMsg.textContent='儲存失敗：'+e.message;}
    finally{settingsToggle.disabled=false;}
  };
  window.addEventListener('xle-admin-change',load);
  window.addEventListener('storage',e=>{if(e.key==='xle-admin')load();});
  const visible = () => !document.hidden && $('#progress').classList.contains('on');
  setInterval(()=>{if(visible())load(true);},5000);
  document.addEventListener('visibilitychange',()=>{if(visible())load(true);});
  window.addEventListener('online',()=>{if(visible())load(true);});
  // Staging: accessible custom dropdowns, native selects remain the source of truth.
  function setupCustomSelect(select){
    if(select.dataset.customReady)return;
    select.dataset.customReady='1';
    const wrap=document.createElement('div');wrap.className='pr-select-wrap';
    select.parentNode.insertBefore(wrap,select);wrap.appendChild(select);
    const trigger=document.createElement('button');trigger.type='button';trigger.className='pr-select-trigger';trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
    const label=document.createElement('span');label.className='pr-select-label';
    const arrow=document.createElement('span');arrow.className='pr-select-arrow';arrow.setAttribute('aria-hidden','true');arrow.innerHTML='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    trigger.append(label,arrow);wrap.appendChild(trigger);
    const popup=document.createElement('div');popup.className='pr-select-popup';popup.setAttribute('role','listbox');popup.hidden=true;document.body.appendChild(popup);
    let active=-1;
    function close(){popup.hidden=true;trigger.setAttribute('aria-expanded','false');}
    function options(){return [...select.options].filter(o=>!o.disabled&&!o.hidden);}
    function sync(){label.textContent=select.selectedOptions[0]?.textContent||'請選擇';trigger.disabled=select.disabled;}
    function position(){
      const r=trigger.getBoundingClientRect(),space=window.innerHeight-r.bottom;
      const max=Math.min(360,Math.max(160,space-12));
      popup.style.left=Math.max(8,Math.min(r.left,window.innerWidth-Math.max(r.width,260)-8))+'px';
      popup.style.width=Math.min(Math.max(r.width,260),window.innerWidth-16)+'px';
      popup.style.maxHeight=max+'px';
      popup.style.top=(space>=170?r.bottom+4:Math.max(8,r.top-Math.min(360,window.innerHeight-32)-4))+'px';
    }
    function choose(value){select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));sync();close();trigger.focus();}
    function open(){
      document.querySelectorAll('.pr-select-popup:not([hidden])').forEach(p=>{p.hidden=true;p._trigger?.setAttribute('aria-expanded','false');});
      popup.replaceChildren();const opts=options();
      opts.forEach((o,i)=>{const b=document.createElement('button');b.type='button';b.className='pr-select-option';b.setAttribute('role','option');b.setAttribute('aria-selected',String(o.value===select.value));b.textContent=o.textContent;b.onclick=()=>choose(o.value);popup.appendChild(b);});
      active=Math.max(0,opts.findIndex(o=>o.value===select.value));popup.hidden=false;trigger.setAttribute('aria-expanded','true');position();
      popup.children[active]?.scrollIntoView({block:'nearest'});
    }
    popup._trigger=trigger;
    trigger.onclick=()=>popup.hidden?open():close();
    trigger.onkeydown=e=>{
      if(['ArrowDown','ArrowUp','Enter',' '].includes(e.key)){e.preventDefault();if(popup.hidden)open();else if(e.key==='Enter'||e.key===' ')popup.children[active]?.click();else{active=Math.max(0,Math.min(popup.children.length-1,active+(e.key==='ArrowDown'?1:-1)));popup.children[active]?.focus();}}
      if(e.key==='Escape')close();
    };
    popup.onkeydown=e=>{
      if(e.key==='Escape'){e.preventDefault();close();trigger.focus();}
      if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();const all=[...popup.children];active=Math.max(0,Math.min(all.length-1,all.indexOf(document.activeElement)+(e.key==='ArrowDown'?1:-1)));all[active]?.focus();}
    };
    document.addEventListener('pointerdown',e=>{if(!popup.hidden&&!popup.contains(e.target)&&!wrap.contains(e.target))close();});
    window.addEventListener('resize',()=>{if(!popup.hidden)position();});
    window.addEventListener('scroll',()=>{if(!popup.hidden)position();},true);
    select.addEventListener('change',sync);
    new MutationObserver(sync).observe(select,{childList:true,subtree:true,attributes:true});
    sync();
  }
  document.querySelectorAll('#progress select').forEach(setupCustomSelect);
  loadTasks();
  if(location.hash==='#progress') $('[data-view="progress"]').click();
})();
