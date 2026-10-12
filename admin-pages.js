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
      '<p><a class="btn ghost" href="'+esc(f.url)+'" target="_blank" rel="noopener">預覽／下載</a></p></article>').join('')||'<p class="muted">沒有符合條件的檔案。</p>';
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
  $('#adminSettingsLogout').onclick=()=>{
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