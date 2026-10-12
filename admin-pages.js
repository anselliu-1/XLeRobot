(() => {
  const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
  const key=()=>localStorage.getItem('xle-admin')||'';
  const headers=()=>key()?{'X-Admin-Key':key()}:{};
  let admin=false, files=[];
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function auth(){
    let next=false;
    if(key())try{next=(await fetch('/api/auth',{headers:headers(),cache:'no-store'})).ok;}catch{}
    admin=next;
    $$('[data-admin-tab]').forEach(b=>b.hidden=!admin);
    if(!admin && ($('#fileadmin').classList.contains('on')||$('#adminsettings').classList.contains('on'))){
      document.querySelector('[data-view="overview"]').click();
    }
    if(admin && $('#fileadmin').classList.contains('on'))loadFiles();
  }
  function render(){
    const q=$('#fileSearch').value.trim().toLowerCase(),type=$('#fileType').value;
    const shown=files.filter(f=>(type==='all'||f.kind===type)&&
      (f.original_name+' '+f.parent_name).toLowerCase().includes(q));
    $('#fileItems').innerHTML=shown.map(f=>'<article class="hw"><header><h3>'+esc(f.original_name)+'</h3></header>'+
      '<p class="muted">'+esc(({task:'分工附件',image:'商品圖片',receipt:'報銷憑證'})[f.kind])+
      ' · '+esc(f.parent_name)+' · '+Math.ceil((f.size||0)/1024)+' KB · '+esc(f.created||'')+'</p>'+
      '<p><label><input type="checkbox" data-file-id="'+esc(f.id)+'"> 選取下載</label> <a class="btn ghost" href="'+esc(f.url)+'" target="_blank" rel="noopener">預覽／下載</a></p></article>').join('')||'<p class="muted">沒有符合條件的檔案。</p>';
  }
  async function loadFiles(){
    if(!admin)return;
    try{const r=await fetch('/api/admin/files',{headers:headers(),cache:'no-store'});if(!r.ok)throw Error('無法讀取檔案清單 ('+r.status+')');
      const d=await r.json();files=d.files||[];render();$('#fileMsg').textContent='共 '+files.length+' 個檔案';
    }catch(e){$('#fileMsg').textContent='檔案清單讀取失敗：'+e.message;}
  }
  $('#fileSearch').addEventListener('input',render);
  $('#fileType').addEventListener('change',render);
  $('#fileRefresh').onclick=loadFiles;
  $('#fileZip').onclick=async()=>{
    if(!admin)return;
    const ids=[...document.querySelectorAll('#fileItems [data-file-id]:checked')].map(x=>x.dataset.fileId);
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
  $('#adminSettingsLogout').onclick=()=>{
    const original=document.querySelector('#tkAdmin');
    if(original && original.textContent.includes('登出')){original.click();return;}
    if(!confirm('確定登出管理員？'))return;
    localStorage.removeItem('xle-admin');auth();
    window.dispatchEvent(new CustomEvent('xle-admin-change',{detail:{admin:false}}));
  };
  $$('[data-view="fileadmin"]').forEach(b=>b.addEventListener('click',loadFiles));
  window.addEventListener('xle-admin-change',auth);
  window.addEventListener('storage',e=>{if(e.key==='xle-admin')auth();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)auth();});
  auth();
  setInterval(()=>{if(!document.hidden)auth();},30000);
})();