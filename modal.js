// XLeRobot 共用網站內確認、原因輸入與提示視窗
(() => {
  let active=false;
  window.xleDialog=({title='請確認',message='',kind='confirm',label='確認',danger=false,options=null,value='',requireReason=false,ack=false}={})=>new Promise(resolve=>{
    if(active){resolve(null);return;}active=true;
    const backdrop=document.createElement('div');backdrop.className='xle-modal-backdrop';
    const panel=document.createElement('section');panel.className='xle-modal';panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','true');
    const h=document.createElement('h3');h.textContent=title;panel.append(h);
    const p=document.createElement('p');p.className='xle-modal-message';p.textContent=message;panel.append(p);
    let input=null,check=null;
    if(options){
      input=document.createElement('select');input.className='xle-modal-input';
      options.forEach(o=>{const el=document.createElement('option');el.value=o.value;el.textContent=o.label;input.append(el);});
      input.value=value;panel.append(input);
    }else if(kind==='reason'){
      input=document.createElement('textarea');input.className='xle-modal-input';input.rows=3;input.maxLength=500;input.placeholder='請輸入原因';input.value=value;panel.append(input);
    }
    if(ack){
      const wrap=document.createElement('label');wrap.className='xle-modal-ack';
      check=document.createElement('input');check.type='checkbox';wrap.append(check,document.createTextNode('我了解此操作無法復原'));panel.append(wrap);
    }
    const actions=document.createElement('div');actions.className='xle-modal-actions';
    const cancel=document.createElement('button');cancel.type='button';cancel.className='btn ghost';cancel.textContent=kind==='notice'?'關閉':'取消';
    const ok=document.createElement('button');ok.type='button';ok.className='btn';ok.textContent=label;if(danger)ok.classList.add('xle-modal-danger');
    if(kind!=='notice')actions.append(cancel);actions.append(ok);panel.append(actions);backdrop.append(panel);document.body.append(backdrop);
    const previous=document.activeElement;
    const valid=()=>{ok.disabled=!!(requireReason&&(!input||!input.value.trim()))||!!(check&&!check.checked);};
    const finish=v=>{document.removeEventListener('keydown',onKey,true);backdrop.remove();active=false;previous?.focus?.();resolve(v);};
    const onKey=e=>{if(e.key==='Escape'){e.preventDefault();finish(null);}else if(e.key==='Tab'){const focusable=[...panel.querySelectorAll('button,input,textarea,select')].filter(x=>!x.disabled);if(!focusable.length)return;const first=focusable[0],last=focusable.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}};
    document.addEventListener('keydown',onKey,true);
    input?.addEventListener('input',valid);check?.addEventListener('change',valid);valid();
    cancel.onclick=()=>finish(null);ok.onclick=()=>finish(input?input.value:true);
    (input||(kind==='notice'?ok:cancel)).focus();
  });
})();