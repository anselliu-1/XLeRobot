(() => {
  const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const key=()=>localStorage.getItem('xle-admin')||'';
  const headers=()=>({'X-Admin-Key':key(),'Content-Type':'application/json'});
  let items=[],admin=false,editId=null,busy=false,snapshot='';
  async function auth(){
    let next=false;
    if(key())try{next=(await fetch('/api/auth',{headers:headers(),cache:'no-store'})).ok;}catch{}
    if(admin!==next){admin=next;$('#riskAdminTools').hidden=!admin;if(!admin)$('#riskForm').hidden=true;render();}
  }
  function render(){
    $('#riskItems').innerHTML=items.map(x=>'<article class="hw"><header><h3>'+esc(x.title)+'</h3><span class="tag ta">'+esc(x.status)+'</span></header>'+
      '<p>'+esc(x.description)+'</p><p><b>對策：</b>'+esc(x.solution)+'</p>'+
      '<p class="muted">最後更新：'+esc(x.updated?.replace('T',' ').slice(0,19)||'—')+'</p>'+
      (admin?'<div class="bar"><button class="btn ghost" data-risk-edit="'+esc(x.id)+'">編輯</button><button class="btn ghost" data-risk-delete="'+esc(x.id)+'">刪除</button></div>':'')+'</article>').join('');
  }
  async function load(force=false){
    if(busy)return;busy=true;
    try{const r=await fetch('/api/project-risks',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);
      const d=await r.json(),next=JSON.stringify(d.items);
      items=d.items||[];
      if(force||next!==snapshot){if($('#riskForm').hidden){render();snapshot=next;}else if(!force){$('#riskMsg').textContent='有其他更新，請先完成或取消編輯。';}}
      if($('#riskForm').hidden)$('#riskMsg').textContent='';
    }catch(e){$('#riskMsg').textContent='更新失敗：'+e.message;}finally{busy=false;}
  }
  function form(x){
    editId=x?.id||null;const f=$('#riskForm');f.hidden=false;f.reset();$('#riskFormTitle').textContent=x?'編輯項目':'新增項目';
    for(const n of ['title','description','solution','status'])if(x)f.elements[n].value=x[n]||'';
    f.dataset.revision=x?.revision||'0';f.scrollIntoView({block:'nearest',behavior:'smooth'});
  }
  $('#riskNew').onclick=()=>form();
  $('#riskCancel').onclick=()=>{$('#riskForm').hidden=true;load(true);};
  $('#riskItems').addEventListener('click',async e=>{
    const b=e.target.closest('[data-risk-edit],[data-risk-delete]');if(!b||!admin)return;
    if(b.dataset.riskEdit){form(items.find(x=>x.id===b.dataset.riskEdit));return;}
    if(b.dataset.riskDelete && confirm('確定刪除此項目？')){
      const r=await fetch('/api/project-risks/'+b.dataset.riskDelete,{method:'DELETE',headers:headers()});
      if(!r.ok)alert('刪除失敗');await load(true);
    }
  });
  $('#riskForm').onsubmit=async e=>{
    e.preventDefault();if(!admin)return;
    const f=e.currentTarget,d=Object.fromEntries(new FormData(f).entries());d.revision=Number(f.dataset.revision);
    try{const r=await fetch(editId?'/api/project-risks/'+editId:'/api/project-risks',
      {method:editId?'PATCH':'POST',headers:headers(),body:JSON.stringify(d)});
      if(!r.ok){const v=await r.json();throw Error(v.error||'儲存失敗');}
      f.hidden=true;await load(true);
    }catch(err){alert(err.message);}
  };
  document.querySelector('[data-view="risks"]').addEventListener('click',()=>{auth();load();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&$('#risks').classList.contains('on')){auth();load();}});
  window.addEventListener('xle-admin-change',auth);
  window.addEventListener('storage',auth);
  setInterval(()=>{if(!document.hidden&&$('#risks').classList.contains('on'))load();},30000);
  auth();load(true);
})();