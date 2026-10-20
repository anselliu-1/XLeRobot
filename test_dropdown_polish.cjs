const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/progress.js','utf8');
const options=new Map();
function select(value){return{value,html:'',set innerHTML(s){this.html=s;this.value='';},get innerHTML(){return this.html;}};}
options.set('#prTask',select('two'));options.set('#prTaskFilter',select('two'));options.set('#prExportTask',select('two'));
const tasks=[{id:'one',task:'older',done:true,done_date:'2026-10-19 12:00',n:1},{id:'two',task:'active',done:false,n:2},{id:'three',task:'newer',done:true,done_date:'2026-10-20 12:00',n:3}];
let resolveFirst;
const context={taskOptions:[],taskFilter:'',window:{xleTaskCompare:(a,b)=>Number(a.done)-Number(b.done)||(b.done_date||'').localeCompare(a.done_date||'')},$:s=>options.get(s),esc:s=>String(s),console,api:async()=>({tasks})};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  let taskOptionsRequest='),source.indexOf('  function card(')),context);
async function run(){
 await vm.runInContext('loadTasks()',context);
 assert.deepEqual(Array.from(context.taskOptions,t=>t.id),['two','three','one']);
 for(const sel of options.values())assert.equal(sel.value,'two');
 const formOptions=options.get('#prTask').innerHTML;
 assert.ok(formOptions.indexOf('active')<formOptions.indexOf('newer'));assert.ok(formOptions.indexOf('newer')<formOptions.indexOf('older'));
 let count=0;context.api=()=>++count===1?new Promise(r=>resolveFirst=r):Promise.resolve({tasks:[...tasks].reverse()});
 const first=vm.runInContext('loadTasks()',context),second=vm.runInContext('loadTasks()',context);
 await second;resolveFirst({tasks:[]});await first;assert.equal(context.taskOptions.length,3);
 assert.ok(source.includes("href=url"));assert.ok(source.includes('rel="noopener noreferrer"'));assert.ok(!source.includes('若瀏覽器不支援此格式或無法顯示'));
 console.log('PASS: shared task ordering, selected work/filter/export preserved, stale response ignored and independent preview actions.');
}
run().catch(e=>{console.error(e);process.exitCode=1;});
