const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/tasks.js','utf8');
const csv=source.slice(source.indexOf('  $("#tkCsv").addEventListener'),source.indexOf('  $("#tkImport").addEventListener'));
for(const isAdmin of [false,true]){
  let handler,output;
  const tasks=[{done:true,member_done:false,member_done_at:'',done_date:'2026-10-20 13:00',task:'A,"B"',who:'甲',due:'',pri:'高',note:'完整目標',result:''}];
  vm.runInNewContext(csv,{$:()=>({addEventListener:(_,fn)=>handler=fn}),tasks,isAdmin,stamp:()=>'',dl:(_,text)=>output=text});
  handler();assert.ok(output.includes('工作完成狀態'));assert.ok(output.includes('"已完成"'));assert.ok(output.includes('"A,""B"""'));
  assert.equal(output.includes('"完成時間"'),isAdmin);assert.ok(output.includes('歷史：組員回報完成'));
}
const guard=source.split('\n').find(l=>l.includes('if (whoF &&'));
for(const [selected,expected] of [['__none','__none'],['甲','甲'],['已移除姓名','']]){
  const ctx={whoF:selected,whos:['甲']};vm.runInNewContext(guard,ctx);assert.equal(ctx.whoF,expected);
}
console.log('CSV admin/member states, escaping and three owner-filter cases passed');
