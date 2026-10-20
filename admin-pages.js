(() => {
  const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
  const key=()=>localStorage.getItem('xle-admin')||'';
  const headers=()=>key()?{'X-Admin-Key':key()}:{};
  let admin=false, files=[], backupStatusBusy=false;
  const selectedFileIds=new Set(), openFileGroups=new Set();
  const fileGroups=[['task','分工＆時程','原有工作附件及歷史資料'],['progress','進度回報','各筆進度回報的附件'],['image','商品圖片','商品圖片及相關檔案'],['receipt','報銷憑證','報銷相關附件']];
  const formatOverviewDate=s=>{if(!s)return '';const raw=String(s);if(/^\d{4}-\d{2}-\d{2}T?\d{2}:\d{2}/.test(raw)&&!/[zZ]|[+-]\d{2}:?\d{2}$/.test(raw))return raw.slice(0,16).replace('T',' ').replace(/-/g,'/');const d=new Date(raw);return Number.isNaN(d.getTime())?raw.replace('T',' ').replace(/-/g,'/'):new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d);};
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
      restoreSafety=d.last_restore_safety_id||'';$('#restoreSafetyDownload').hidden=!restoreSafety;
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
      const chosen=group.filter(f=>selectedFileIds.has(String(f.id))).length;
      const selection=group.length?'<div class="file-group-select"><label><input type="checkbox" data-group-select="'+kind+'" '+(chosen===group.length?'checked':'')+'> 全選此分類</label><span class="muted">已選取 '+chosen+' / '+group.length+' 個</span></div>':'';
      const rows=group.map(f=>'<article class="hw file-entry"><header><h3>'+esc(f.original_name)+'</h3></header>'+
        '<div class="file-entry-body"><p class="muted">'+esc(title)+' · '+esc(f.parent_name)+' · '+Math.ceil((f.size||0)/1024)+' KB · '+esc(formatFileDate(f.created))+'</p>'+
        '<div class="file-entry-actions"><label><input type="checkbox" data-file-id="'+esc(f.id)+'" '+(selectedFileIds.has(String(f.id))?'checked':'')+'> 選取下載</label> <a class="btn ghost" href="'+esc(f.url)+'" '+(f.kind==='receipt'?'data-admin-file data-file-name="'+esc(f.original_name)+'"':'')+' target="_blank" rel="noopener">預覽／下載</a></div></div></article>').join('');
      return '<details class="file-group" data-file-group="'+kind+'" '+(openFileGroups.has(kind)?'open':'')+'><summary><span class="file-group-title">'+esc(title)+'</span><span class="file-group-desc">'+esc(description)+'</span><span class="file-group-count">'+group.length+' 個檔案</span></summary><div class="file-group-body">'+selection+(rows||'<p class="muted">目前沒有檔案。</p>')+'</div></details>';
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
      const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Taipei',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
      const dueValue=t=>String(t.due||t.deadline||'').slice(0,10);
      const orderedTasks=[...tasks].sort((a,b)=>window.xleTaskCompare?window.xleTaskCompare(a,b):a.n-b.n);
      topics.innerHTML=orderedTasks.length?orderedTasks.map(t=>{
        const due=dueValue(t),late=!t.done&&/^\d{4}-\d{2}-\d{2}$/.test(due)&&due<today;
        const status=t.done?'已完成':late?'已逾期':'進行中';
        const css=t.done?'overview-done':late?'overview-late':'';
        return '<article class="hw overview-topic '+css+'"><header><h3>'+esc(t.task)+'</h3></header><p>'+status+' · '+(t.report_count||0)+' 筆進度回報</p>'+(late?'<p class="muted">截止日期：'+esc(due.replace(/-/g,'/'))+'</p>':'')+(t.latest_report?'<p class="muted">最近更新：'+esc(formatOverviewDate(t.latest_report.created))+'</p>':'<p class="muted">尚無關聯回報</p>')+'</article>';
      }).join(''):'<p class="muted">尚無工作主題。</p>';
    }catch(e){stats.textContent='進度載入失敗：'+e.message;topics.textContent='請稍後重新整理。';}
  }
  document.querySelectorAll('[data-view="overview"]').forEach(b=>b.addEventListener('click',loadOverview));
  window.addEventListener('xle-task-order-change',loadOverview);
  loadOverview();
  $('#fileItems').addEventListener('toggle',e=>{const d=e.target.closest('details[data-file-group]');if(!d)return;if(d.open)openFileGroups.add(d.dataset.fileGroup);else openFileGroups.delete(d.dataset.fileGroup);},true);
  $('#fileItems').addEventListener('change',e=>{
    const group=e.target.closest('input[data-group-select]');
    if(group){for(const f of shownFiles().filter(f=>f.kind===group.dataset.groupSelect)){if(group.checked)selectedFileIds.add(String(f.id));else selectedFileIds.delete(String(f.id));}render();return;}
    const c=e.target.closest('input[data-file-id]');if(!c)return;
    if(c.checked)selectedFileIds.add(c.dataset.fileId);else selectedFileIds.delete(c.dataset.fileId);
    const kind=files.find(f=>String(f.id)===c.dataset.fileId)?.kind;
    if(kind){const visible=shownFiles().filter(f=>f.kind===kind),selected=visible.filter(f=>selectedFileIds.has(String(f.id))).length;const toggle=$('#fileItems input[data-group-select="'+kind+'"]');if(toggle){toggle.checked=visible.length>0&&selected===visible.length;toggle.indeterminate=selected>0&&selected<visible.length;const count=toggle.closest('.file-group-select')?.querySelector('.muted');if(count)count.textContent='已選取 '+selected+' / '+visible.length+' 個';}}
    updateFileSelection();
  });
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
  let restoreToken='',restoreSafety='';
  const restoreMsg=$('#restoreBackupMsg'),restoreCheck=$('#restoreBackupCheck'),restoreApply=$('#restoreBackupApply'),restoreCancel=$('#restoreBackupCancel');
  async function restoreRequest(path,body,raw=false){
    const response=await fetch('/api/admin/restore/'+path,{method:'POST',headers:{...headers(),...(raw?{'Content-Type':'application/zip'}:{'Content-Type':'application/json'})},body:raw?body:JSON.stringify(body)});
    const data=await response.json();if(!response.ok)throw Error(data.error||'還原失敗');return data;
  }
  restoreCheck.onclick=async()=>{
    if(!admin)return;
    const file=$('#restoreBackupFile').files[0];if(!file){restoreMsg.textContent='請先選擇 XLeRobot 完整備份 ZIP';return;}
    if(file.size>512*1024*1024){restoreMsg.textContent='備份 ZIP 上限為 512 MB';return;}
    restoreCheck.disabled=true;restoreApply.hidden=true;restoreMsg.textContent='上傳並檢查資料庫、附件與 SHA-256，尚未還原…';
    try{
      if(restoreToken)await restoreRequest('cancel',{token:restoreToken});restoreToken='';
      const d=await restoreRequest('preview',file,true);restoreToken=d.token;
      const labels={tasks:'分工工作',progress_reports:'進度回報',purchases:'採購項目',progress_files:'回報附件紀錄',project_risks:'困難與展出'};
      $('#restoreBackupPreview').innerHTML='<p>備份時間：'+esc(d.created)+' · 版本：'+esc(d.version||'未標示')+'</p><table><thead><tr><th>資料</th><th>目前</th><th>備份</th></tr></thead><tbody>'+Object.entries(labels).map(([k,label])=>'<tr><td>'+label+'</td><td>'+(d.current_tables[k]||0)+'</td><td>'+(d.tables[k]||0)+'</td></tr>').join('')+'</tbody></table><p>已核對 '+d.files+' 個附件 · '+(d.bytes/1024/1024).toFixed(2)+' MB</p><p>'+esc(d.warning)+'</p>';
      restoreApply.hidden=false;restoreCancel.hidden=false;restoreMsg.textContent='檢查通過；尚未還原。預覽 20 分鐘內有效。還原會覆蓋目前資料，請與其他使用者確認停止編輯。';
    }catch(e){restoreMsg.textContent=e.message;}
    finally{restoreCheck.disabled=false;}
  };
  restoreCancel.onclick=async()=>{
    if(!restoreToken)return;
    try{await restoreRequest('cancel',{token:restoreToken});restoreToken='';restoreApply.hidden=true;restoreCancel.hidden=true;$('#restoreBackupPreview').replaceChildren();restoreMsg.textContent='已取消，線上資料未變更。';}
    catch(e){restoreMsg.textContent=e.message;}
  };
  restoreApply.onclick=async()=>{
    if(!admin||!restoreToken)return;
    const reason=await xleDialog({title:'整站還原測試資料',message:'會以已檢查的備份覆蓋目前資料及附件關聯；網站程式和登入金鑰維持現況。還原前會保留目前資料的安全副本。請填寫原因。',kind:'reason',requireReason:true,danger:true,label:'下一步'});
    if(reason===null)return;
    const typed=await xleDialog({title:'最後確認',message:'請輸入「還原測試站」。確認後會覆蓋測試站資料，並停用 Discord 通知。',kind:'reason',requireReason:true,danger:true,ack:true,label:'確認整站還原'});
    if(typed!=='還原測試站'){restoreMsg.textContent='未確認還原，資料未變更。';return;}
    restoreApply.disabled=true;restoreCheck.disabled=true;restoreCancel.disabled=true;restoreMsg.textContent='正在建立安全副本並還原，請勿關閉或重複操作…';
    try{const d=await restoreRequest('apply',{token:restoreToken,confirm:typed,reason});restoreSafety=d.safety_id;restoreToken='';restoreApply.hidden=true;restoreCancel.hidden=true;$('#restoreSafetyDownload').hidden=false;restoreMsg.textContent=d.message;}
    catch(e){restoreMsg.textContent=e.message;}
    finally{restoreApply.disabled=false;restoreCheck.disabled=false;restoreCancel.disabled=false;}
  };
  $('#restoreSafetyDownload').onclick=async()=>{
    if(!admin||!restoreSafety)return;
    try{const r=await fetch('/api/admin/restore/safety/'+restoreSafety,{headers:headers(),cache:'no-store'});if(!r.ok)throw Error('無法下載安全副本');const url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='XLeRobot-before-restore.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),60000);}
    catch(e){restoreMsg.textContent=e.message;}
  };

  auth();
  setInterval(()=>{if(!document.hidden)auth();},30000);
})();




