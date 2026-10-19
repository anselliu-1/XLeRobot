const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const events={},frames=[],observers={};let shellWidth=600,contentWidth=1400;
function control(){return{hidden:true,disabled:false,addEventListener(name,fn){this[name]=fn;}};}
const prev=control(),next=control(),shell={get clientWidth(){return shellWidth;}};
const tabs={scrollLeft:0,get clientWidth(){return shellWidth-(prev.hidden?0:72);},get scrollWidth(){return Math.max(contentWidth,this.clientWidth);},
  closest:()=>shell,addEventListener(name,fn){events[name]=fn;},querySelector:()=>selected,
  scrollBy({left}){this.scrollLeft=Math.max(0,Math.min(this.scrollWidth-this.clientWidth,this.scrollLeft+left));events.scroll?.();},
  getBoundingClientRect(){return{left:100,right:100+this.clientWidth};}};
const selected={hidden:false,getBoundingClientRect:()=>({left:100,right:200}),matches:()=>true};
const context={document:{querySelector:s=>s==='#mainTabs'?tabs:s==='#tabPrev'?prev:next},window:{addEventListener(name,fn){events['window-'+name]=fn;}},
  requestAnimationFrame(fn){frames.push(fn);return frames.length;},matchMedia:()=>({matches:true}),
  MutationObserver:class{constructor(fn){observers.mutation=fn;}observe(){}},ResizeObserver:class{constructor(fn){observers.resize=fn;}observe(){}}};
vm.runInNewContext(fs.readFileSync(__dirname+'/nav-scroll.js','utf8'),context);
function flush(){while(frames.length)frames.shift()();}
assert.equal(next.hidden,false);assert.equal(prev.disabled,true);assert.equal(next.disabled,false);
next.click();flush();assert.ok(tabs.scrollLeft>0);assert.equal(prev.disabled,false);
prev.click();flush();assert.equal(tabs.scrollLeft,0);
let prevented=false;
events.wheel({deltaX:0,deltaY:120,deltaMode:0,ctrlKey:false,preventDefault(){prevented=true;}});flush();
assert.equal(prevented,true);assert.equal(tabs.scrollLeft,120);
const before=tabs.scrollLeft;events.wheel({deltaX:140,deltaY:0,deltaMode:0,ctrlKey:false,preventDefault(){throw Error('native horizontal wheel intercepted');}});assert.equal(tabs.scrollLeft,before);
tabs.scrollLeft=contentWidth-tabs.clientWidth;
events.wheel({deltaX:0,deltaY:120,deltaMode:0,ctrlKey:false,preventDefault(){throw Error('page scroll blocked at right edge');}});
shellWidth=1800;tabs.scrollLeft=0;observers.resize();flush();assert.equal(next.hidden,true);assert.equal(prev.hidden,true);
shellWidth=480;observers.resize();flush();assert.equal(next.hidden,false);
const last={hidden:false,getBoundingClientRect:()=>({left:1300,right:1400})};
events.focusin({target:{closest:()=>last}});flush();assert.ok(tabs.scrollLeft>0);
while(tabs.scrollLeft+tabs.clientWidth<tabs.scrollWidth){next.click();flush();}
assert.equal(next.disabled,true);
console.log('Navigation: arrows, wheel, native horizontal wheel, boundary scrolling, resize and focus passed');
