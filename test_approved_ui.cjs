const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const purchaseSource=fs.readFileSync(__dirname+'/purchases.js','utf8');
const code=purchaseSource.slice(purchaseSource.indexOf('  const buyForm='),purchaseSource.indexOf('  async function uploadFiles'));
const nodes=new Map(),listeners={},answers=[],requests=[];
function node(){return{hidden:false,value:'',disabled:false,textContent:'',innerHTML:'',children:[],addEventListener(){},scrollIntoView(){},click(){this.clicked=true;},querySelector(selector){this.nodes??={};return this.nodes[selector]??=node();},querySelectorAll(){return[];},append(child){this.children.push(child);nodes.set('#'+child.id,child);},after(){}};}
const defaults={name:'',spec:'',qty:'1',price:'0',status:'待確認',owner:'',url:'',note:'',stock:'尚未確認',actual_price:'0'};
const formNode=node();formNode.hidden=true;formNode.elements=Object.fromEntries(Object.entries(defaults).map(([k,value])=>[k,{value,disabled:false}]));
formNode.reset=()=>{for(const [k,v] of Object.entries(defaults))formNode.elements[k].value=v;};
formNode.querySelectorAll=()=>Object.values(formNode.elements);
nodes.set('#buyForm',formNode);
const context={document:{createElement:()=>node(),querySelector:s=>nodes.get(s),hidden:false},
  window:{addEventListener:(name,fn)=>listeners[name]=fn},$:s=>{if(!nodes.has(s))nodes.set(s,node());return nodes.get(s);},
  FormData:class{constructor(form){this.data=Object.entries(form.elements).filter(([,v])=>!v.disabled).map(([k,v])=>[k,v.value]);}entries(){return this.data[Symbol.iterator]();}},
  editId:null,editBase:null,baseFields:{},saveBusy:false,leaveApproved:false,admin:false,structuredClone,
  xleDialog:async()=>answers.shift()??false,esc:s=>String(s??'').replaceAll('<','&lt;'),msg:s=>context.message=s,
  setInterval(){},load:async()=>{},req:async(path,method,body)=>{requests.push({path,method,body});if(context.failure)throw context.failure;return{};}};
vm.createContext(context);vm.runInContext(code,context);
const sample={id:'a',revision:1,name:'purchase',spec:'old-spec',qty:1,price:10,status:'待確認',note:'old-note',stock:'尚未確認',actual_price:0};
const event={preventDefault(){}};
async function run(){
  context.sample=sample;await vm.runInContext('form(sample)',context);
  formNode.elements.note.value='MINE';answers.push(false);await nodes.get('#buyNew').onclick();assert.equal(formNode.elements.note.value,'MINE');
  let blocked=false;listeners.beforeunload({preventDefault(){blocked=true;}});assert.equal(blocked,true);
  context.failure=Object.assign(Error('conflict'),{status:409,current:{...sample,revision:2,qty:2,spec:'latest-spec'}});
  await formNode.onsubmit(event);
  assert.equal(requests.at(-1).body.note,'MINE');assert.equal(requests.at(-1).body.qty,undefined);
  assert.ok(nodes.get('#buyConflict').innerHTML.includes('MINE'));
  assert.equal(formNode.elements.note.value,'MINE');assert.equal(formNode.hidden,false);
  formNode.elements.note.value='MINE updated after conflict';
  nodes.get('#buyConflict').querySelector('[data-rebase]').onclick();
  assert.equal(formNode.elements.qty.value,2);assert.equal(formNode.elements.note.value,'MINE updated after conflict');assert.equal(formNode.elements.spec.value,'latest-spec');
  context.failure=null;await formNode.onsubmit(event);
  assert.equal(requests.at(-1).body.revision,2);assert.equal(requests.at(-1).body.qty,undefined);assert.equal(formNode.hidden,true);
  await vm.runInContext('form()',context);formNode.elements.name.value='new';formNode.elements.note.value='keep-on-error';
  context.failure=Error('offline');await formNode.onsubmit(event);assert.equal(formNode.elements.note.value,'keep-on-error');assert.equal(formNode.hidden,false);
  answers.push(true);await nodes.get('#buyCancel').onclick();assert.equal(formNode.hidden,true);
  console.log('Purchase UI: discard cancellation, unload warning, conflict diff, explicit rebase, partial retry and error preservation passed');

  const source=fs.readFileSync(__dirname+'/tasks.js','utf8');
  const taskCode=source.slice(source.indexOf('  const taskDrafts='),source.indexOf('  let filter ='));
  const done={checked:false},date={value:''},label={textContent:''},feedback={innerHTML:''};
  const row={dataset:{id:'a'},querySelector:s=>s==='[data-k="done"]'?done:s==='[data-k="done_date"]'?date:s==='.when'?label:feedback};
  const taskContext={Map,Promise,JSON,document:{querySelectorAll:()=>[row],activeElement:null},window:{addEventListener(){}},
    tasks:[{id:'a',done:false,done_date:''}],hdr:()=>({}),esc:s=>String(s??'').replaceAll('<','&lt;'),setSync(){},render(){},editing:()=>false,late:()=>false,
    fetch:async()=>taskContext.response,apply:d=>taskContext.tasks=d.tasks};
  vm.createContext(taskContext);vm.runInContext(taskCode,taskContext);
  taskContext.response={ok:true,json:async()=>({tasks:[{id:'a',done:true,done_date:'2026-10-20 13:00'}]})};
  await vm.runInContext("saveTask('a',{done_date:'2026-10-20T13:00'})",taskContext);
  assert.equal(done.checked,true);assert.equal(date.value,'2026-10-20T13:00');assert.equal(label.textContent,'已完成');
  taskContext.response={ok:false,json:async()=>({error:'offline'})};await vm.runInContext("saveTask('a',{note:'UNSAVED'})",taskContext);
  assert.equal(vm.runInContext("taskDrafts.get('a').note",taskContext),'UNSAVED');assert.ok(feedback.innerHTML.includes('重試儲存'));
  taskContext.response={ok:true,json:async()=>({tasks:[{id:'a',done:true,done_date:'2026-10-20 13:00',note:'UNSAVED'}]})};
  await vm.runInContext("saveTask('a',taskDrafts.get('a'))",taskContext);assert.equal(vm.runInContext('taskDrafts.size',taskContext),0);
  assert.ok(source.includes('isAdmin||saveStates.has(t.id)'));
  console.log('Task UI: normalized checkbox/time, failed-input retention, retry and scoped feedback passed');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
