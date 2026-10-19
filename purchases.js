(() => {
  const $=s=>document.querySelector(s), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const API=location.protocol==='file:'?'http://localhost:8000':location.origin;
  const key=()=>localStorage.getItem('xle-admin')||'';
  const headers=()=>key()?{'X-Admin-Key':key()}:{};
  let purchases=[],editId=null,admin=false,perms={refund_view:false,refund_edit:false};
  const msg=s=>$('#buyMsg').textContent=s;
  async function req(path,method='GET',body){const r=await fetch(API+path,{method,headers:{...headers(),...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'伺服器錯誤');return d;}
  const money=v=>Number(v||0).toLocaleString('zh-TW');
  function render(){
    $('#buyCount').textContent=purchases.length+' 項';
    $('#buyTotal').textContent='NT$ '+money(purchases.filter(p=>p.status!=='不需採購').reduce((s,p)=>s+Number(p.qty)*Number(p.price),0));
    $('#buyItems').innerHTML=purchases.length?purchases.map(p=>`<article class="hw">
      <header><h3>${esc(p.name)}</h3><span class="tag ${p.status==='已到貨'?'ta':p.status==='待採購'?'tb':'tc'}">${esc(p.status)}</span></header>
      <p>${esc(p.spec||'規格待補')}</p><p>數量：${p.qty}　預估單價：NT$ ${money(p.price)}　預估小計：NT$ ${money(p.qty*p.price)}</p>
      <p class="muted">庫存：${esc(p.stock||'尚未確認')}　${p.owner?'負責人：'+esc(p.owner)+'　':''}${esc(p.note||'')}</p>
      ${p.actual_price?`<p>實際金額：NT$ ${money(p.actual_price)}</p>`:''}
      ${p.url?`<p><a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">購買連結 ↗</a></p>`:''}
      <div class="buy-images">${(p.images||[]).map(i=>`<figure><a href="${esc(i.url)}" target="_blank" rel="noopener"><img class="buy-photo" src="${esc(i.url)}" alt="${esc(i.original_name)}" loading="lazy"></a><figcaption class="muted">${esc(i.original_name)}</figcaption>${admin?`<button class="btn ghost" data-delimg="${i.id}">刪除圖片</button>`:''}</figure>`).join('')}</div>
      ${admin||perms.refund_view?`<details class="legacy"><summary>報銷管理：${esc(p.refund||'未開始')}</summary><div class="legacy-body">
      ${admin||perms.refund_edit?`<label>報銷狀態<select data-refund="${p.id}">${['未開始','待送件','審核中','已完成','不需報銷'].map(x=>`<option ${x===p.refund?'selected':''}>${x}</option>`).join('')}</select></label><button class="btn ghost" data-save-refund="${p.id}">儲存報銷狀態</button>`:`<p>${esc(p.refund||'未開始')}</p>`}
      ${admin?`<h4>報銷附件（僅管理員可存取）</h4><div class="buy-receipts">${(p.receipts||[]).map(r=>`<p><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.original_name)} ↗</a> <button class="btn ghost" data-delreceipt="${r.id}">刪除附件</button></p>`).join('')}</div><label class="btn ghost">上傳發票／報銷表 <input type="file" data-receipt="${p.id}" accept=".pdf,image/jpeg,image/png,image/webp" multiple hidden></label>`:''}</div></details>`:''}
      <div class="bar"><button class="btn ghost" data-edit="${p.id}">編輯</button><label class="btn ghost" style="cursor:pointer">上傳商品圖片 <input type="file" accept="image/jpeg,image/png,image/webp" data-upload="${p.id}" multiple hidden></label>${admin?`<button class="btn ghost" data-del="${p.id}">刪除項目</button>`:''}</div>
    </article>`).join(''):'<p class="muted">尚無採購項目，可由組員新增。</p>';
  }
  let loadBusy=false, lastSnapshot='', deferredRender=false;
  function editingPurchase(){return !$('#buyForm').hidden || !!$('#buyItems').querySelector('select:focus, input:focus, textarea:focus');}
  async function load(force=false){
    if(loadBusy)return;
    loadBusy=true;
    try{
      const d=await req('/api/purchases'), snapshot=JSON.stringify([d.purchases,d.permissions]);
      purchases=d.purchases;perms=d.permissions||perms;
      if(force || snapshot!==lastSnapshot || deferredRender){
        if(!force && editingPurchase()){deferredRender=true;}
        else{render();deferredRender=false;}
        lastSnapshot=snapshot;
      }
      msg('');
    }catch(e){msg('採購清單同步失敗：'+e.message)}
    finally{loadBusy=false;}
  }
  function form(p){editId=p?.id||null;const f=$('#buyForm');f.hidden=false;$('#buyFormTitle').textContent=p?'編輯採購項目':'新增採購項目';f.reset();$('#buyOwnerField').hidden=!admin;for(const k of ['name','spec','qty','price','status','owner','url','note','stock','actual_price'])if(p&&f.elements[k]&&p[k]!=null)f.elements[k].value=p[k];f.scrollIntoView({behavior:'smooth',block:'nearest'});}
  $('#buyNew').onclick=()=>form();$('#buyCancel').onclick=()=>{$('#buyForm').hidden=true;load(true);};
  $('#buyForm').onsubmit=async e=>{e.preventDefault();const f=e.currentTarget,d=Object.fromEntries(new FormData(f).entries());if(!admin)delete d.owner;try{await req(editId?'/api/purchases/'+editId:'/api/purchases',editId?'PATCH':'POST',d);f.hidden=true;await load();}catch(e){alert('儲存失敗：'+e.message)}};
  async function uploadFiles(input,kind){const files=[...input.files];if(!files.length)return;const limit=kind==='receipts'?20:10;for(const file of files){if(file.size>limit*1024*1024){alert(file.name+' 超過 '+limit+' MB');continue;}if(!confirm('確認上傳附件？\n\n檔案：'+file.name+'\n\n⚠️ 請確認檔案內容與版本正確。\n附件一旦上傳，一般組員無法自行刪除，僅管理者有權限刪除。'))continue;try{const path='/api/purchases/'+(kind==='receipts'?input.dataset.receipt:input.dataset.upload)+'/'+kind;const r=await fetch(API+path,{method:'POST',headers:{...headers(),'Content-Type':file.type,'X-File-Name':encodeURIComponent(file.name)},body:file});const d=await r.json();if(!r.ok)throw Error(d.error||'上傳失敗');}catch(e){alert('上傳失敗：'+e.message)}}input.value='';await load();}
  $('#buyItems').addEventListener('change',async e=>{const f=e.target;if(f.matches('[data-upload]'))return uploadFiles(f,'images');if(f.matches('[data-receipt]')&&admin)return uploadFiles(f,'receipts');});
  $('#buyItems').addEventListener('click',async e=>{
    const b=e.target.closest('[data-edit],[data-del],[data-delimg],[data-delreceipt],[data-save-refund]');if(!b)return;
    if(b.dataset.edit){form(purchases.find(p=>p.id===b.dataset.edit));return;}
    if(b.dataset.saveRefund){const p=purchases.find(x=>x.id===b.dataset.saveRefund);if(!p)return;const sel=b.parentElement.querySelector('[data-refund]');if(!sel)return;try{await req('/api/purchases/'+p.id,'PATCH',{...p,refund:sel.value});await load();}catch(e){alert('更新失敗：'+e.message)}return;}
    if(!admin)return;
    const kind=b.dataset.delreceipt?'receipt':b.dataset.delimg?'image':'item';const id=b.dataset.delreceipt||b.dataset.delimg||b.dataset.del;
    if(!confirm('確定刪除'+(kind==='receipt'?'報銷附件':kind==='image'?'商品圖片':'採購項目與所有附件')+'？此操作無法復原。'))return;
    const path=kind==='receipt'?'/api/purchase-receipts/':kind==='image'?'/api/purchase-images/':'/api/purchases/';
    try{await req(path+id,'DELETE');await load();}catch(e){alert('刪除失敗：'+e.message)}
  });
  $('#buyCSV').onclick=()=>{const cols=['name','spec','qty','price','actual_price','stock','status','owner','url','note','updated'];if(admin||perms.refund_view)cols.push('refund');const csv='\uFEFF'+[cols.join(','),...purchases.map(p=>cols.map(k=>'"'+String(p[k]??'').replace(/"/g,'""')+'"').join(','))].join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='XLeRobot_採購清單.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
  const events={task_add:'分工：新增任務',task_edit:'分工：修改任務內容',task_done:'分工：回報完成',task_reopen:'分工：取消完成',task_result:'分工：成果文字更新',task_upload:'分工：上傳成果附件',task_delete:'分工：刪除任務或附件',buy_add:'採購：新增項目',buy_edit:'採購：修改資料',buy_status:'採購：狀態更新',buy_image:'採購：上傳圖片',buy_delete:'採購：刪除項目或圖片',buy_stock:'採購：庫存確認更新',buy_owner:'採購：指派或更換負責人',buy_refund:'採購：報銷狀態更新',progress_add:'進度回報：新增回報',progress_continue:'進度回報：接續回報',progress_void:'進度回報：作廢回報',progress_file_remove:'進度回報：附件移除'};
  $('#notifyEvents').innerHTML=Object.entries(events).map(([id,name])=>`<label><input type="checkbox" value="${id}"> ${name}</label>`).join('');
  $('#refundView').onchange=()=>{if(!$('#refundView').checked)$('#refundEdit').checked=false;$('#refundEdit').disabled=!$('#refundView').checked;};
  $('#purchasePermSave').onclick=async()=>{try{perms=await req('/api/purchases/permissions','POST',{refund_view:$('#refundView').checked,refund_edit:$('#refundEdit').checked});$('#purchasePermMsg').textContent='權限已儲存';await load();}catch(e){$('#purchasePermMsg').textContent='儲存失敗：'+e.message}};
  let notifyEdits=0,notifySavedEdits=0;
  $('#notifyPanel').addEventListener('change',e=>{if(e.target.matches('input,select'))notifyEdits++;});
  $('#notifySave').onclick=async()=>{const revision=notifyEdits;try{await req('/api/notifications/config','POST',{enabled:$('#notifyEnabled').checked,mode:$('#notifyMode').value,events:[...$('#notifyEvents').querySelectorAll('input:checked')].map(i=>i.value)});notifySavedEdits=revision;$('#notifyMsg').textContent='設定已儲存';loadNotifyStatus();}catch(e){$('#notifyMsg').textContent='儲存失敗：'+e.message}};
  async function checkAdmin(){let next=false;try{next=!!key()&&(await fetch(API+'/api/auth',{headers:headers()})).ok;}catch{}const changed=next!==admin;admin=next;$('#notifyPanel').hidden=!admin;$('#purchasePermissionsPanel').hidden=!admin;$('#buyOwnerField').hidden=!admin;if(changed){await load(true);window.dispatchEvent(new CustomEvent('xle-admin-change',{detail:{admin}}));}if(admin){try{const c=await req('/api/notifications/config');if(notifyEdits===notifySavedEdits){$('#notifyEnabled').checked=c.enabled;$('#notifyMode').value=c.mode;$('#notifyEvents').querySelectorAll('input').forEach(i=>i.checked=c.events.includes(i.value));}const p=await req('/api/purchases/permissions');$('#refundView').checked=p.refund_view;$('#refundEdit').checked=p.refund_edit;$('#refundEdit').disabled=!p.refund_view;}catch{}}}
  let notifyStatusBusy=false;
  async function loadNotifyStatus(){
    if(!admin || notifyStatusBusy || document.hidden || !$('#adminsettings').classList.contains('on') || !$('#notifyPanel').open)return;
    notifyStatusBusy=true;
    try{
      const r=await fetch(API+'/api/progress/notification-status',{headers:headers(),cache:'no-store',signal:AbortSignal.timeout(15000)});
      if(!r.ok)throw Error('讀取失敗');
      const n=await r.json();
      const text=`進度回報通知｜Discord：${n.configured?'已設定':'尚未設定'} · 待送 ${n.pending} · 重試中 ${n.failed}${n.enabled?'':' · 通知總開關已關閉'}${n.recent_error?' · 最近失敗：'+n.recent_error:''}`;
      if($('#progressNotifyStatus').textContent!==text)$('#progressNotifyStatus').textContent=text;
    }catch{
      const text='進度回報通知狀態暫時無法讀取，稍後會自動重試。';
      if($('#progressNotifyStatus').textContent!==text)$('#progressNotifyStatus').textContent=text;
    }finally{notifyStatusBusy=false;}
  }
  $('#notifyPanel').addEventListener('toggle',loadNotifyStatus);
  document.querySelector('[data-view="adminsettings"]').addEventListener('click',loadNotifyStatus);
  document.addEventListener('visibilitychange',loadNotifyStatus);
  setInterval(loadNotifyStatus,5000);
  load(true).then(checkAdmin);
  setInterval(()=>{if(!document.hidden)load();},3000);
  setInterval(()=>{if(!document.hidden)checkAdmin();},30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden){load();checkAdmin();}});
  $('#buyItems').addEventListener('focusout',()=>setTimeout(()=>{if(deferredRender&&!editingPurchase())load(true);},0));
})();
