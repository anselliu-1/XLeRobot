// Protected receipt links need the same verified header as the admin API.
(() => {
  document.addEventListener('click',async event=>{
    const link=event.target.closest('a[data-admin-file]');
    if(!link)return;
    event.preventDefault();
    if(link.dataset.loading)return;
    const url=new URL(link.href,location.href);
    if(url.origin!==location.origin || !/^\/api\/purchase-receipts\/[a-f0-9]+$/.test(url.pathname))return;
    const key=localStorage.getItem('xle-admin')||'';
    if(!key){alert('請先登入管理員再開啟報銷附件');return;}
    const preview=window.open('about:blank','_blank');
    if(preview)preview.opener=null;
    link.dataset.loading='1';link.setAttribute('aria-busy','true');
    try{
      const response=await fetch(url.href,{headers:{'X-Admin-Key':key},cache:'no-store',signal:AbortSignal.timeout(30000)});
      if(!response.ok)throw Error(response.status===403?'管理員驗證已失效，請重新登入':'無法讀取附件（'+response.status+'）');
      const blob=await response.blob(),objectUrl=URL.createObjectURL(blob);
      if(preview && !preview.closed)preview.location.replace(objectUrl);
      else{
        const a=document.createElement('a');a.href=objectUrl;
        a.download=link.dataset.fileName||'報銷附件';a.click();
      }
      setTimeout(()=>URL.revokeObjectURL(objectUrl),300000);
    }catch(e){if(preview&&!preview.closed)preview.close();alert('附件開啟失敗：'+e.message);}
    finally{delete link.dataset.loading;link.removeAttribute('aria-busy');}
  });
})();
