const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/progress.js','utf8');
const nodes=new Map(),node=()=>({textContent:'',innerHTML:'',hidden:false});
const fields={reporter:{value:'tester'},subject:{value:'topic'},content:{value:'content'},task_id:{value:''},parent_id:{value:''},files:{value:'',files:[]}};
const button={disabled:false};Object.values(fields).forEach(f=>f.disabled=false);
const form={elements:Object.assign(Object.values(fields),fields),hidden:false,querySelector:()=>button};
const context={form,$:s=>{if(!nodes.has(s))nodes.set(s,node());return nodes.get(s);},draftFields:()=>'',esc:s=>String(s).replaceAll('<','&lt;'),fileSize:n=>n+' bytes',Set,JSON,taskOptions:[],showId:()=>false};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  let submittedFields'),source.indexOf('  const mayLeave')),context);
vm.runInContext(source.slice(source.indexOf('  form.elements.files.onchange'),source.indexOf('  form.onsubmit')),context);
const f=(name,size=5)=>({name,size,lastModified:1,type:'text/plain'});
function add(files){fields.files.files=files;fields.files.value='selected';fields.files.onchange();}
function names(){return Array.from(vm.runInContext('queuedFiles.map(f=>f.name)',context));}
add([f('first.txt')]);add([f('second.txt')]);assert.deepEqual(names(),['first.txt','second.txt']);
add([f('second.txt')]);assert.equal(names().length,2);
nodes.get('#prUploadList').onclick({target:{closest:()=>({dataset:{unqueue:'0'}})}});assert.deepEqual(names(),['second.txt']);
add([f('huge.txt',51*1024*1024)]);assert.deepEqual(names(),['second.txt']);assert.match(nodes.get('#prMessage').textContent,/未加入/);
add(Array.from({length:20},(_,i)=>f('x'+i)));assert.deepEqual(names(),['second.txt']);
assert.equal(fields.files.value,'');assert.match(nodes.get('#prUploadList').innerHTML,/second.txt/);
let answer=false,request;
context.FormData=class{constructor(){this.map=new Map(Object.entries(fields).filter(([k])=>k!=='files').map(([k,v])=>[k,v.value]));this.attachments=[];}get(k){return this.map.get(k);}set(k,v){this.map.set(k,v);}delete(){}append(k,file,name){this.attachments.push(name);}};
context.xleDialog=async()=>answer;context.api=async(path,opts)=>{request=opts;return{id:1,version:1};};context.load=async()=>{};context.resetForm=()=>context.wasReset=true;
vm.runInContext(source.slice(source.indexOf('  form.onsubmit'),source.indexOf("  $('#prItems').onclick")),context);
async function run(){
  await form.onsubmit({preventDefault(){}});assert.equal(vm.runInContext('uploadBusy',context),false);assert.deepEqual(names(),['second.txt']);assert.equal(request,undefined);
  add([f('third.txt')]);answer=true;await form.onsubmit({preventDefault(){}});
  assert.deepEqual(request.body.attachments,['second.txt','third.txt']);assert.equal(context.wasReset,true);assert.equal(fields.files.disabled,false);
  const tasks=fs.readFileSync(__dirname+'/tasks.js','utf8'),sortContext={window:{}};vm.createContext(sortContext);
  vm.runInContext(tasks.slice(tasks.indexOf('  const PRI ='),tasks.indexOf('  const dtIn =')),sortContext);
  const list=[{n:1,done:true,done_date:'2026-10-18 10:00',due:'2026-10-01'},{n:2,done:true,done_date:'2026-10-20 13:00',due:'2026-12-01'},{n:3,done:false,due:'2026-11-01',pri:'中'},{n:4,done:true,done_date:'',due:'2026-01-01'}];
  for(const mode of ['due','pri','who','add'])assert.deepEqual([...list].sort((a,b)=>sortContext.window.xleTaskCompare(a,b,mode)).map(t=>t.n),[3,2,1,4]);
  console.log('PASS: incremental attachments, deduplication, removal, count/size rejection, confirmation cancellation, exact upload payload and shared completion ordering.');
}
run().catch(e=>{console.error(e);process.exitCode=1});
