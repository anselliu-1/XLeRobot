const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/admin-files.js','utf8');
async function check({key='test-key',status=200,popup=true,href='https://staging.example/api/purchase-receipts/'+ 'a'.repeat(32)}={}){
  let handler,request,opened=0,download=0,alerts=[],prevented=false;
  const link={href,dataset:{fileName:'receipt.pdf'},setAttribute(){},removeAttribute(){}};
  const preview={closed:false,opener:{},location:{replace(url){this.url=url;}},close(){this.closed=true;}};
  class ObjectURL extends URL{static createObjectURL(){return 'blob:test';}static revokeObjectURL(){}}
  const context={URL:ObjectURL,location:{origin:'https://staging.example',href:'https://staging.example/'},
    localStorage:{getItem:()=>key},AbortSignal:{timeout:()=>({})},setTimeout(){},alert:s=>alerts.push(s),
    document:{addEventListener(_,fn){handler=fn;},createElement(){return{click(){download++;}};}},
    window:{open(){opened++;return popup?preview:null;}},
    fetch:async(url,options)=>{request={url,options};return {ok:status===200,status,blob:async()=>({})};}};
  vm.runInNewContext(source,context);
  await handler({target:{closest:()=>link},preventDefault(){prevented=true;}});
  return {request,opened,download,alerts,preview,link,prevented};
}
(async()=>{
  let r=await check();assert.equal(r.request.options.headers['X-Admin-Key'],'test-key');assert.equal(r.request.options.cache,'no-store');
  assert.equal(r.preview.location.url,'blob:test');assert.equal(r.preview.opener,null);assert.equal(r.link.dataset.loading,undefined);
  r=await check({popup:false});assert.equal(r.download,1);
  r=await check({status:403});assert.equal(r.preview.closed,true);assert.equal(r.alerts.length,1);
  r=await check({key:''});assert.equal(r.request,undefined);assert.equal(r.opened,0);assert.equal(r.alerts.length,1);
  r=await check({href:'https://other.example/api/purchase-receipts/'+ 'a'.repeat(32)});assert.equal(r.request,undefined);assert.equal(r.opened,0);
  console.log('5 protected attachment scenarios passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
