(() => {
  const $ = s => document.querySelector(s), form = $('#prForm');
  const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const headers = () => ({'X-Admin-Key':localStorage.getItem('xle-admin') || ''});
  const fileSize = n => n<1024 ? n+' bytes' : n<1024*1024 ? (n/1024).toFixed(1)+' KB' : (n/1024/1024).toFixed(2)+' MB';
  const syncMessage = text => {if($('#prSync').textContent!==text)$('#prSync').textContent=text;};
  let items = [], matched = new Set(), admin = false, request = 0, timer;
  let pendingLoads = 0, lastSnapshot = '';
  const draftFields = () => JSON.stringify(['reporter','subject','content','parent_id'].map(k=>form.elements[k].value));
  let submittedFields = draftFields();
  const hasDraft = () => draftFields()!==submittedFields || form.elements.files.files.length>0;
  const mayLeave = () => !hasDraft() || confirm('有尚未送出的回報。確定離開或放棄目前輸入？本網站不會保存草稿。');
  window.addEventListener('beforeunload',e=>{
    if(hasDraft()){e.preventDefault();e.returnValue='';}
  });
  window.addEventListener('xle-before-view-change',e=>{
    if(e.detail.from==='progress' && e.detail.to!=='progress' && !mayLeave())e.preventDefault();
  });
  const date = s => new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(s))+'（台灣）';
  async function api(url,options={}) {
    const readTimeout = !options.method || options.method==='GET' ? {signal:AbortSignal.timeout(15000)} : {};
    const response = await fetch(url,{cache:'no-store',...readTimeout,...options});
    const data = await response.json();
    if(!response.ok) throw Error(data.error || '操作失敗');
    return data;
  }
  function card(r) {
    return `<article class="blk pr-report ${r.status==='void'?'pr-void':''}" id="report-${r.id}">
      <header><h3>#${r.id} · v${r.version}　${esc(r.subject)}</h3><span class="tag">${r.status==='valid'?'有效':'已作廢'}</span></header>
      <p class="muted">${esc(r.reporter)} · ${esc(date(r.created))}${r.parent_id?' · 接續 #'+r.parent_id:''}</p>
      <div class="pr-content">${esc(r.content) || '（無文字內容）'}</div>
      ${r.status==='void'?`<p class="pr-reason">作廢原因：${esc(r.void_reason)}<br>${esc(date(r.void_at))}</p>`:''}
      <ul class="pr-files">${r.files.map(f=>`<li>${f.removed_at?`<span>${esc(f.name)}（已移除：${esc(f.reason)}）</span>`:`<a href="${f.url}">${esc(f.name)}</a> · ${fileSize(f.size)}${admin && r.status==='void'?` <button class="btn ghost" data-remove="${f.id}" data-report="${r.id}">移除附件</button>`:''}`}</li>`).join('')}</ul>
      <div class="pr-actions">${r.status==='valid'?`<button class="btn ghost" data-continue="${r.id}">接續此回報</button>`:''}
      ${admin?`${r.status==='valid'?`<button class="btn ghost" data-void="${r.id}">作廢（填原因）</button>`:`<button class="btn ghost" data-restore="${r.id}">恢復有效（填原因）</button>`}<button class="btn ghost" data-audit="${r.id}">操作紀錄</button>`:''}</div>
      <div class="pr-audit" data-audit-list="${r.id}"></div></article>`;
  }
  function render() {
    const closed = new Set([...$('#prItems').querySelectorAll('.pr-topic:not([open])')].map(el=>el.dataset.root));
    const asc=$('#prSort').value==='asc', sorter=(a,b)=>(asc?1:-1)*(a.id-b.id);
    const shown=items.filter(r=>matched.has(r.id));
    $('#prCount').textContent=`符合 ${shown.length} 筆回報；主題檢視會保留完整版本歷程。`;
    if($('#prView').value==='time') $('#prItems').innerHTML=shown.sort(sorter).map(card).join('');
    else {
      const groups=new Map();
      items.forEach(r=>{if(!groups.has(r.root_id))groups.set(r.root_id,[]);groups.get(r.root_id).push(r);});
      $('#prItems').innerHTML=[...groups.values()].sort((a,b)=>sorter(a.at(-1),b.at(-1))).map(g=>{
        const latest=g.at(-1);
        return `<details class="pr-topic" data-root="${latest.root_id}" ${closed.has(String(latest.root_id))?'':'open'}><summary>${esc(latest.subject)} <span class="muted">· ${g.length} 個版本 · 最近 ${esc(date(latest.created))}</span></summary>${g.sort(sorter).map(card).join('')}</details>`;
      }).join('');
    }
    if(!shown.length) $('#prItems').innerHTML='<p class="muted">沒有符合條件的回報。</p>';
  }
  async function load(background=false) {
    if(background===true && pendingLoads)return;
    pendingLoads++;
    const seq=++request;
    try {
      const query=new URLSearchParams({q:$('#prSearch').value,reporter:$('#prReporter').value,status:$('#prStatus').value});
      const d=await api('/api/progress?'+query,{headers:headers()});
      if(seq!==request)return;
      const snapshot=JSON.stringify(d);
      if(snapshot!==lastSnapshot){
        items=d.items; matched=new Set(d.matched_ids); admin=d.admin;
        const selected=$('#prReporter').value;
        $('#prReporter').innerHTML='<option value="">全部姓名</option>'+d.reporters.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');
        $('#prReporter').value=selected; render();lastSnapshot=snapshot;
      }
      syncMessage('自動同步中：每 5 秒更新，保留正在填寫的內容與附件。');
    } catch(e) {
      if(seq===request)syncMessage('同步暫時失敗，稍後會自動重試：'+e.message);
    } finally {pendingLoads--;}
  }
  function cancel() {
    form.elements.parent_id.value=''; form.elements.subject.readOnly=false;
    $('#prFormTitle').textContent='新增回報'; $('#prParentHint').textContent=''; $('#prCancel').hidden=true;
  }
  $('#prCancel').onclick=()=>{
    if(!mayLeave())return;
    const reporter=form.elements.reporter.value;form.reset();form.elements.reporter.value=reporter;
    cancel();submittedFields=draftFields();$('#prUploadSize').textContent='';
  };
  form.elements.files.onchange=()=>{
    const files=[...form.elements.files.files],size=files.reduce((n,f)=>n+f.size,0);
    $('#prUploadSize').textContent=`${files.length} 個附件，共 ${(size/1024/1024).toFixed(2)} / 50 MB`;
  };
  form.onsubmit=async e=>{
    e.preventDefault(); const button=form.querySelector('[type=submit]');
    const files=[...form.elements.files.files];
    if(files.length>20 || files.reduce((n,f)=>n+f.size,0)>50*1024*1024){$('#prMessage').textContent='每筆最多 20 個附件，合計上限 50MB';return;}
    if(!confirm('確認送出？送出後不可修改，可接續建立新版本。'))return;
    const body=new FormData(form); button.disabled=true; $('#prMessage').textContent='上傳並儲存中，請勿重複送出…';
    try {
      const d=await api('/api/progress',{method:'POST',body});
      const reporter=form.elements.reporter.value;form.reset();form.elements.reporter.value=reporter;cancel();
      submittedFields=draftFields();
      $('#prUploadSize').textContent=''; $('#prMessage').textContent=`已送出 #${d.id} · v${d.version}`; await load();
    } catch(e) {$('#prMessage').textContent=e.message+'；若連線中斷，請先重新整理確認是否已建立，避免重複送出。';}
    finally {button.disabled=false;}
  };
  $('#prItems').onclick=async e=>{
    const b=e.target.closest('button'); if(!b)return;
    if(b.dataset.continue){
      const r=items.find(x=>x.id===Number(b.dataset.continue));
      if(!r || r.status!=='valid')return;
      if(!mayLeave())return;
      form.elements.parent_id.value=r.id; form.elements.subject.value=r.subject;form.elements.subject.readOnly=true;
      form.elements.content.value='';form.elements.files.value='';$('#prUploadSize').textContent='';
      submittedFields=draftFields();
      $('#prFormTitle').textContent='接續回報 #'+r.id;$('#prParentHint').textContent='同一主題下新增版本，保留接續來源；舊附件不會帶入。';
      $('#prCancel').hidden=false;form.scrollIntoView({behavior:'smooth'});form.elements.reporter.focus();return;
    }
    b.disabled=true;
    try {
      if(b.dataset.audit){
        const d=await api('/api/progress/'+b.dataset.audit+'/audit',{headers:headers()});
        document.querySelector(`[data-audit-list="${b.dataset.audit}"]`).innerHTML=d.items.map(a=>`<p>${esc(date(a.created))} · ${esc(a.action)} · ${esc(a.actor)} ${esc(a.reason)}</p>`).join('');
      } else if(b.dataset.void || b.dataset.remove || b.dataset.restore){
        const reason=prompt(b.dataset.restore?'恢復有效的原因（已永久移除的附件無法恢復）':b.dataset.remove?'移除附件的原因（檔案將永久移除，保留紀錄）':'作廢原因（必填，保留原始回報）');
        if(!reason || !reason.trim())return;
        if(b.dataset.remove && !confirm('確認永久移除此附件？此操作無法復原。'))return;
        const rid=b.dataset.void || b.dataset.restore || b.dataset.report;
        const d=await api('/api/progress/'+rid+'/'+(b.dataset.void?'void':b.dataset.restore?'restore':'remove-file'),{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({reason,file_id:b.dataset.remove})});
        if(d.warning)alert(d.warning); await load();
      }
    } catch(e){alert(e.message);} finally {b.disabled=false;}
  };
  $('#prSearch').oninput=()=>{clearTimeout(timer);timer=setTimeout(load,250);};
  ['prReporter','prStatus'].forEach(id=>$('#'+id).onchange=load);
  ['prSort','prView'].forEach(id=>$('#'+id).onchange=render);
  $('#prRefresh').onclick=load;
  $('[data-view="progress"]').addEventListener('click',load);
  window.addEventListener('xle-admin-change',load);
  window.addEventListener('storage',e=>{if(e.key==='xle-admin')load();});
  const visible = () => !document.hidden && $('#progress').classList.contains('on');
  setInterval(()=>{if(visible())load(true);},5000);
  document.addEventListener('visibilitychange',()=>{if(visible())load(true);});
  window.addEventListener('online',()=>{if(visible())load(true);});
  if(location.hash==='#progress') $('[data-view="progress"]').click();
})();
