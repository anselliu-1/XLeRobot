(() => {
  const tabs=document.querySelector('#mainTabs'),shell=tabs?.closest('.tabs-shell');
  const prev=document.querySelector('#tabPrev'),next=document.querySelector('#tabNext');
  if(!tabs||!shell||!prev||!next)return;
  let frame=0;
  function update(){
    frame=0;
    const overflow=tabs.scrollWidth>shell.clientWidth+1;
    prev.hidden=next.hidden=!overflow;
    prev.disabled=tabs.scrollLeft<=1;
    next.disabled=tabs.scrollLeft+tabs.clientWidth>=tabs.scrollWidth-1;
  }
  function schedule(){if(!frame)frame=requestAnimationFrame(update);}
  const behavior=()=>matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth';
  function move(direction){tabs.scrollBy({left:direction*Math.max(120,tabs.clientWidth*.75),behavior:behavior()});}
  prev.addEventListener('click',()=>move(-1));next.addEventListener('click',()=>move(1));
  tabs.addEventListener('scroll',schedule,{passive:true});
  tabs.addEventListener('wheel',event=>{
    if(event.ctrlKey||Math.abs(event.deltaX)>=Math.abs(event.deltaY)||tabs.scrollWidth<=tabs.clientWidth+1)return;
    const scale=event.deltaMode===1?16:event.deltaMode===2?tabs.clientWidth:1;
    const target=Math.max(0,Math.min(tabs.scrollWidth-tabs.clientWidth,tabs.scrollLeft+event.deltaY*scale));
    if(target===tabs.scrollLeft)return;
    event.preventDefault();tabs.scrollBy({left:target-tabs.scrollLeft,behavior:'instant'});
  },{passive:false});
  function reveal(button){
    if(!button||button.hidden)return;
    const rect=button.getBoundingClientRect(),view=tabs.getBoundingClientRect();
    const delta=rect.left<view.left?rect.left-view.left:rect.right>view.right?rect.right-view.right:0;
    if(delta)tabs.scrollBy({left:delta,behavior:behavior()});
  }
  tabs.addEventListener('focusin',event=>reveal(event.target.closest('button')));
  new MutationObserver(records=>{
    schedule();
    if(records.some(r=>r.attributeName==='class'&&r.target.matches('button.on')))reveal(tabs.querySelector('button.on'));
  }).observe(tabs,{subtree:true,attributes:true,attributeFilter:['hidden','class'],childList:true});
  new ResizeObserver(schedule).observe(shell);
  window.addEventListener('resize',schedule);
  document.fonts?.ready.then(schedule);
  update();
})();
