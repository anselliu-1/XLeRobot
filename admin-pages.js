(() => {
  const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
  const key=()=>localStorage.getItem('xle-admin')||'';
  const headers=()=>key()?{'X-Admin-Key':key()}:{};
  let admin=false, files=[], backupStatusBusy=false;
  const selectedFileIds=new Set(), openFileGroups=new Set();
  const fileGroups=[['task','分工＆時程','原有工作附件及歷史資料'],['progress','進度回報','各筆進度回報的附件'],['image','商品圖片','商品圖片及相關檔案'],['receipt','報銷憑證','報銷相關附件']];
  const formatFileDate=s=>{if(!s)return '時間未提供';const d=new Date(s);return Number.isNaN(d.getTime())?String(s):new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(d);};
  const shownFiles=()=>{const q=$('#fileSearch').value.trim().toLowerCase(),type=$('#fileType').value;return files.filter(f=>(type==='all'||f.kind===type)&&(String(f.original_name||'')+' '+String(f.parent_name||'')).toLowerCase().includes(q));};
  function updateFileSelection(){const shown=shownFiles(),all=shown.length>0&&shown.every(f=>selectedFileIds.has(String(f.id))),some=shown.some(f=>selectedFileIds.has(String(f.id)));const cb=$('#fileSelectAll');cb.checked=all;cb.indeterminate=!all&&some;cb.disabled=!shown.length;$('#fileSelectedCount').textContent='已選取 '+selectedFileIds.size+' 個檔案';}
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function auth(){
    let next=false;
    if(key())try{next=(await fetch('/api/auth',{headers:headers(),cache:'no-store'})).ok;}catch{}
    admin=next;
    $$('[data-admin-tab]').forEach(b=>b.hidden=!admin);
    if(!admin && ($('#fileadmin').classList.contains('on')||$('#adminsettings').classList.contains('on')||$('#rules').classList.contains('on'))){
      document.querySelector('[data-view="overview"]').click();
    }
    if(admin && $('#fileadmin').classList.contains('on'))loadFiles();
    if(admin && $('#adminsettings').classList.contains('on'))loadBackupStatus();
  }
  async function loadBackupStatus(){
    if(!admin || backupStatusBusy)return;
    backupStatusBusy=true;
    try{
      const r=await fetch('/api/admin/backup/status',{headers:headers(),cache:'no-store',signal:AbortSignal.timeout(15000)});
      if(!r.ok)throw Error('讀取失敗');
      const d=await r.json();
      const time=d.last_backup_at?new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(d.last_backup_at))+'（台灣時間）':'尚無成功備份紀錄';
      const text='上次成功備份時間：'+time;
      if($('#lastBackupTime').textContent!==text)$('#lastBackupTime').textContent=text;
    }catch{$('#lastBackupTime').textContent='上次成功備份時間：暫時無法讀取';}
    finally{backupStatusBusy=false;}
  }
  function render(){
    const shown=shownFiles();
    const root=$('#fileItems');
    root.querySelectorAll('details[data-file-group]').forEach(d=>{
      if(d.open)openFileGroups.add(d.dataset.fileGroup);
      else openFileGroups.delete(d.dataset.fileGroup);
    });
    root.innerHTML=fileGroups.map(([kind,title,description])=>{
      const group=shown.filter(f=>f.kind===kind);
      if(!group.length && ($('#fileSearch').value.trim()||$('#fileType').value!=='all'))return '';
      const rows=group.map(f=>'<article class="hw file-entry"><header><h3>'+esc(f.original_name)+'</h3></header>'+
        '<div class="file-entry-body"><p class="muted">'+esc(title)+' · '+esc(f.parent_name)+' · '+Math.ceil((f.size||0)/1024)+' KB · '+esc(formatFileDate(f.created))+'</p>'+
        '<div class="file-entry-actions"><label><input type="checkbox" data-file-id="'+esc(f.id)+'" '+(selectedFileIds.has(String(f.id))?'checked':'')+'> 選取下載</label> <a class="btn ghost" href="'+esc(f.url)+'" target="_blank" rel="noopener">預覽／下載</a></div></div></article>').join('');
      return '<details class="file-group" data-file-group="'+kind+'" '+(openFileGroups.has(kind)?'open':'')+'><summary><span class="file-group-title">'+esc(title)+'</span><span class="file-group-desc">'+esc(description)+'</span><span class="file-group-count">'+group.length+' 個檔案</span></summary><div class="file-group-body">'+(rows||'<p class="muted">目前沒有檔案。</p>')+'</div></details>';
    }).join('')||'<p class="muted">沒有符合條件的檔案。</p>';
    updateFileSelection();
  }
  async function loadFiles(){
    if(!admin)return;
    try{const r=await fetch('/api/admin/files',{headers:headers(),cache:'no-store'});if(!r.ok)throw Error('無法讀取檔案清單 ('+r.status+')');
      const d=await r.json();files=d.files||[];const valid=new Set(files.map(f=>String(f.id)));for(const id of selectedFileIds)if(!valid.has(id))selectedFileIds.delete(id);render();$('#fileMsg').textContent='共 '+files.length+' 個檔案';
    }catch(e){$('#fileMsg').textContent='檔案清單讀取失敗：'+e.message;}
  }
  async function loadOverview(){
    const stats=$('#overviewStats'),topics=$('#overviewTopics');
    try{
      const [tr,pr]=await Promise.all([fetch('/api/tasks',{cache:'no-store'}),fetch('/api/progress',{cache:'no-store'})]);
      if(!tr.ok||!pr.ok)throw Error('暫時無法讀取進度');
      const td=await tr.json(),pd=await pr.json();
      const tasks=td.tasks||[],reports=pd.items||[];
      const count=tasks.length,done=tasks.filter(t=>t.done).length;
      const rate=count?Math.round(done/count*1000)/10:0;
      const boxes=[['工作主題',count],['進行中',count-done],['已完成',done],['累計進度回報',reports.length]];
      stats.innerHTML=boxes.map(([k,v])=>'<article class="hw"><header><h3>'+esc(k)+'</h3></header><strong class="overview-number">'+v+'</strong></article>').join('');
      $('#overviewProgressBar').style.width=rate+'%';
      $('#overviewProgressLabel').textContent=done+' / '+count+' 項工作主題已完成（'+rate+'%）';
      topics.innerHTML=tasks.length?tasks.map(t=>'<article class="hw"><header><h3>'+esc(t.task)+'</h3></header><p>'+(t.done?'已完成':'進行中')+' · '+(t.report_count||0)+' 筆進度回報</p>'+(t.latest_report?'<p class="muted">最近更新：'+esc(t.latest_report.created.slice(0,16))+'</p>':'<p class="muted">尚無關聯回報</p>')+'</article>').join(''):'<p class="muted">尚無工作主題。</p>';
    }catch(e){stats.textContent='進度載入失敗：'+e.message;topics.textContent='請稍後重新整理。';}
  }
  document.querySelectorAll('[data-view="overview"]').forEach(b=>b.addEventListener('click',loadOverview));
  loadOverview();
  $('#fileItems').addEventListener('toggle',e=>{const d=e.target.closest('details[data-file-group]');if(!d)return;if(d.open)openFileGroups.add(d.dataset.fileGroup);else openFileGroups.delete(d.dataset.fileGroup);},true);
  $('#fileItems').addEventListener('change',e=>{const c=e.target.closest('input[data-file-id]');if(!c)return;if(c.checked)selectedFileIds.add(c.dataset.fileId);else selectedFileIds.delete(c.dataset.fileId);updateFileSelection();});
  $('#fileSelectAll').addEventListener('change',e=>{for(const f of shownFiles()){if(e.target.checked)selectedFileIds.add(String(f.id));else selectedFileIds.delete(String(f.id));}render();});
  $('#fileSearch').addEventListener('input',render);
  $('#fileType').addEventListener('change',render);
  $('#fileRefresh').onclick=loadFiles;
  $('#fileZip').onclick=async()=>{
    if(!admin)return;
    const ids=[...selectedFileIds];
    if(!ids.length){alert('請先勾選要下載的檔案');return;}
    if(ids.length>50){alert('每次最多選擇 50 個檔案');return;}
    const b=$('#fileZip');b.disabled=true;b.textContent='打包中…';
    try{
      const r=await fetch('/api/admin/files/zip',{method:'POST',headers:{...headers(),'Content-Type':'application/json'},body:JSON.stringify({ids})});
      if(!r.ok){const d=await r.json();throw Error(d.error||'下載失敗');}
      const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');
      a.href=url;a.download='XLeRobot_files.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
    }catch(e){alert(e.message);}finally{b.disabled=false;b.textContent='下載勾選檔案 ZIP';}
  };
  $('#fullBackupDownload').onclick=async()=>{
    if(!admin)return;
    const button=$('#fullBackupDownload'),status=$('#fullBackupMsg');
    button.disabled=true;status.textContent='正在建立資料庫快照、讀取附件並壓縮，請保留此頁…';
    try{
      const response=await fetch('/api/admin/backup',{method:'POST',headers:headers(),cache:'no-store'});
      if(!response.ok){const d=await response.json();throw Error(d.error||'備份失敗');}
      status.textContent='打包完成，正在下載 ZIP…';
      const blob=await response.blob();
      const expected=Number(response.headers.get('Content-Length'));
      if(expected && blob.size!==expected)throw Error('下載不完整，請重新備份');
      const disposition=response.headers.get('Content-Disposition')||'';
      const filename=disposition.match(/filename="([^"]+)"/)?.[1]||'XLeRobot-backup.zip';
      const url=URL.createObjectURL(blob),a=document.createElement('a');
      a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
      status.textContent='已交給瀏覽器下載：'+filename+'（'+(blob.size/1024/1024).toFixed(2)+' MB）。請確認已儲存到電腦。';
      await loadBackupStatus();setTimeout(loadBackupStatus,1000);
    }catch(e){status.textContent='備份未完成：'+e.message;}
    finally{button.disabled=false;}
  };
  $('#adminSettingsLogout').onclick=()=>{
    const original=document.querySelector('#tkAdmin');
    if(original && original.textContent.includes('登出')){original.click();return;}
    if(!confirm('確定登出管理員？'))return;
    localStorage.removeItem('xle-admin');auth();
    window.dispatchEvent(new CustomEvent('xle-admin-change',{detail:{admin:false}}));
  };
  $$('[data-view="fileadmin"]').forEach(b=>b.addEventListener('click',loadFiles));
  $$('[data-view="adminsettings"]').forEach(b=>b.addEventListener('click',loadBackupStatus));
  window.addEventListener('xle-admin-change',auth);
  window.addEventListener('storage',e=>{if(e.key==='xle-admin')auth();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)auth();});
  auth();
  setInterval(()=>{if(!document.hidden)auth();},30000);
})();
