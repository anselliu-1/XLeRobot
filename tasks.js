// 分工 & 時程：可互動工作表（資料存在本機瀏覽器）
(function () {
  const KEY = "xlerobot-tasks-v1";
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  // 共用資料：後端 API（全組同步）
  const API = "";
  let tasks = [], rev = 0, online = null, pending = false;
  // 管理者（只有管理者能勾選完成、改完成日期、匯入、還原）
  let ls = null; try { ls = window["local" + "Storage"]; ls.getItem("x"); } catch (e) { ls = null; }
  let adminKey = (ls && ls.getItem("xle-admin")) || "", isAdmin = false;
  const hdr = () => adminKey ? { "X-Admin-Key": adminKey } : {};
  async function checkAdmin() {
    if (!adminKey) { isAdmin = false; return; }
    try { const r = await fetch(API + "/api/auth", { headers: hdr(), cache: "no-store" }); isAdmin = r.ok; } catch (e) { isAdmin = false; }
    if (!isAdmin && adminKey) { adminKey = ""; ls && ls.removeItem("xle-admin"); }
  }
  function adminUI() {
    const b = $("#tkAdmin"); if (b) b.textContent = isAdmin ? "管理者模式・登出" : "管理者登入";
    document.body.classList.toggle("tk-admin", isAdmin);
    window.dispatchEvent(new CustomEvent("xle-admin-change",{detail:{admin:isAdmin}}));
  }
  const taskDrafts=new Map(),saveStates=new Map();
  let taskPending=0,taskQueue=Promise.resolve(),taskRenderNeeded=false;
  const draftTask=t=>({...t,...(taskDrafts.get(t.id)||{})});
  function stateMarkup(id){
    const state=saveStates.get(id);
    return '<span class="task-save-state" data-save-id="'+esc(id)+'" role="status" title="'+esc(state?.text||'')+'">'+(state?esc(state.kind==='error'?'儲存失敗，輸入已保留':state.text):'')+'</span>'+(state?.kind==='error'?'<button type="button" class="btn ghost task-retry" data-task-retry="'+esc(id)+'">重試儲存</button>':'');
  }
  function markTask(id,kind,text){
    saveStates.set(id,{kind,text});
    const row=[...document.querySelectorAll('#tkTable .tk[data-id]')].find(r=>r.dataset.id===id);
    const el=row?.querySelector('[data-save-feedback]');if(el)el.innerHTML=stateMarkup(id);
  }
  function saveTask(id,patch){
    taskDrafts.set(id,{...(taskDrafts.get(id)||{}),...patch});
    taskPending++;markTask(id,'saving','儲存中…');
    const job={...patch};
    taskQueue=taskQueue.then(async()=>{
      try{
        const response=await fetch('/api/tasks/'+id,{method:'PATCH',headers:{'Content-Type':'application/json',...hdr()},body:JSON.stringify(job)});
        const data=await response.json();if(!response.ok)throw Error(data.error||'儲存失敗');
        apply(data);setSync(true);
        const draft=taskDrafts.get(id)||{};
        for(const [k,v] of Object.entries(job))if(draft[k]===v)delete draft[k];
        if(Object.keys(draft).length)taskDrafts.set(id,draft);else taskDrafts.delete(id);
        const saved=tasks.find(t=>t.id===id),row=[...document.querySelectorAll('#tkTable .tk[data-id]')].find(r=>r.dataset.id===id);
        if(saved&&row){
          for(const key of ['done','done_date']){
            const input=row.querySelector('[data-k="'+key+'"]');
            if(input&&document.activeElement!==input&&!(key in draft)){
              if(key==='done')input.checked=!!saved.done;else input.value=(saved.done_date||'').replace(' ','T');
            }
          }
          const label=row.querySelector('.when');if(label)label.textContent=saved.done?'已完成':late(saved)?'已逾期':'進行中';
        }
        markTask(id,'saved','已儲存');taskRenderNeeded=true;
      }catch(error){markTask(id,'error','儲存失敗：'+error.message+'（輸入已保留）');setSync(false);}
      finally{taskPending--;if(!taskPending){
        for(const [key] of taskDrafts)if(saveStates.get(key)?.kind!=='error')markTask(key,'error','部分變更尚未儲存（輸入已保留）');
        if(!editing()){render();taskRenderNeeded=false;}
      }}
    });
    return taskQueue;
  }
  window.addEventListener('beforeunload',e=>{if(taskPending||taskDrafts.size){e.preventDefault();e.returnValue='';}});
  let filter = "all", whoF = "", sortBy = "due";

  function setSync(ok, msg) {
    online = ok; const el = $("#tkSync"); if (!el) return;
    el.className = "sync " + (ok ? "ok" : "bad");
    el.querySelector("span").textContent = msg || (ok ? "已連線・全組即時同步（最後同步 " + new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + "）" : "連線中斷，正在重試…（此時修改不會儲存）");
  }
  // 負責者可多人：以「、」分隔儲存
  const people = w => String(w || "").split(/[、,，;；\/]+/).map(x => x.trim()).filter(Boolean);
  const joinP = arr => [...new Set(arr.map(x => x.trim()).filter(Boolean))].slice(0, 4).join("、");
  const norm = t => ({ ...t, attachments: Array.isArray(t.attachments) ? t.attachments : [], who: t.who || "", due: t.due || "", done_date: t.done_date || "", note: t.note || "", result: t.result || "", member_done_at: t.member_done_at || "" });
  function apply(d) { if (d && Array.isArray(d.tasks)) { tasks = d.tasks.map(norm); rev = d.rev; const toggle=$("#allowMemberCompletion"); if(toggle && tasks.length) toggle.checked=!!tasks[0].member_completion_allowed; } }
  const completionToggle=$("#allowMemberCompletion"), completionMsg=$("#memberCompletionMsg");
  if(completionToggle)completionToggle.onchange=async()=>{
    completionToggle.disabled=true;completionMsg.textContent="儲存中…";
    try{
      const res=await fetch("/api/tasks/completion-settings",{method:"POST",headers:{"Content-Type":"application/json",...hdr()},body:JSON.stringify({allow_members:completionToggle.checked})});
      if(!res.ok)throw Error("無法儲存權限");
      completionMsg.textContent="已儲存";await refetch();
    }catch(e){completionToggle.checked=!completionToggle.checked;completionMsg.textContent=e.message;}
    finally{completionToggle.disabled=false;}
  };
  const auditButton=$("#taskAuditRefresh");
  if(auditButton)auditButton.onclick=async()=>{
    const el=$("#taskAuditList");el.textContent="載入中…";
    try{
      const res=await fetch("/api/tasks/status-audit",{headers:hdr(),cache:"no-store"});
      if(!res.ok)throw Error("無法取得操作紀錄");
      const d=await res.json();
      el.innerHTML=d.items.length?d.items.map(a=>'<p>'+esc(a.changed_at)+' · '+esc(a.task_name)+' · '+(a.before_done?'已完成':'未完成')+' → '+(a.after_done?'已完成':'未完成')+' · '+esc(a.actor)+'</p>').join(''):"尚無完成狀態變更紀錄";
    }catch(e){el.textContent=e.message;}
  };
  async function call(method, path, body) {
    pending = true;
    try {
      const r = await fetch(API + path, { method, headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...hdr() }, body: body ? JSON.stringify(body) : undefined });
      if (r.status === 403) { render(); alert("這個欄位只有管理者能修改。組員可以勾選「回報完成」和填寫「成果」。"); throw new Error("403"); }
      if (!r.ok) {let d={};try{d=await r.json();}catch{};throw new Error(d.error||r.status);}
      const d = await r.json(); apply(d); setSync(true); render(); return d;
    } catch (e) { if (e.message !== "403") { setSync(false); alert("無法儲存到共用清單："+e.message); } throw e; }
    finally { pending = false; }
  }
  const editing = () => { const a = document.activeElement; return a && a.closest && a.closest("#tkTable") && a.matches(".in"); };
  async function poll() {
    if (!pending && !taskPending && !editing()) {
      try {
        const r = await fetch(API + "/api/tasks?since=" + rev, { headers: hdr(), cache: "no-store" });
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        if (!d.unchanged && !taskPending && !editing()) { apply(d); render(); }
        setSync(true);
      } catch (e) { setSync(false); }
    }
    setTimeout(poll, document.hidden ? 10000 : 3000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !taskPending && !editing()) fetch(API + "/api/tasks", { headers: hdr(), cache: "no-store" }).then(r => r.json()).then(d => { apply(d); render(); setSync(true); }).catch(() => setSync(false)); });

  const fin = t => !!t.done;
  const late = t => !t.done && t.due && t.due < today();
  const PRI = { "高": 0, "中": 1, "低": 2 };
  const dtIn = v => (v || "").replace(" ", "T");
  const shortDT = v => v ? v.slice(5).replace("-", "/") : "";

  function render() {
    // 負責者清單
    const whos = [...new Set(tasks.flatMap(t => people(t.who)))].sort((a, b) => a.localeCompare(b, "zh-Hant"));
    $("#whoList").innerHTML = whos.map(w => `<option value="${esc(w)}">`).join("");
    const sel = $("#tkWho");
    if (whoF && whoF !== "__none" && !whos.includes(whoF)) whoF = "";
    sel.innerHTML = `<option value="">所有負責者</option><option value="__none"${whoF === "__none" ? " selected" : ""}>未指派</option>` + whos.map(w => `<option${w === whoF ? " selected" : ""}>${esc(w)}</option>`).join("");

    // 統計
    const total = tasks.length, rep = tasks.filter(t => t.done).length, chk = rep,
      lt = tasks.filter(late).length, none = tasks.filter(t => !people(t.who).length).length;
    const pct = total ? Math.round(rep / total * 100) : 0, pct2 = total ? Math.round(chk / total * 100) : 0;
    const per = whos.map(w => { const a = tasks.filter(t => people(t.who).includes(w)); const d = a.filter(t => t.done).length; return `<span class="chip"><b>${esc(w)}</b> ${d}/${a.length}</span>`; }).join("");
    $("#tkStats").innerHTML = `
      <div class="st"><span>工作主題已完成</span><b>${rep} / ${total}</b><div class="pbar"><i style="width:${pct}%"></i></div></div>
      <div class="st"><span>未完成</span><b>${total - rep}</b></div>
      <div class="st ${lt ? "warn" : ""}"><span>已逾期</span><b>${lt}</b></div>
      <div class="st"><span>未指派</span><b>${none}</b></div>
      ${per ? `<div class="st wide"><span>各負責者已完成主題數</span><div class="chips">${per}</div></div>` : ""}`;

    // 列表
    let list = tasks.map(draftTask).filter(t =>
      (filter === "all" || (filter === "todo" && !fin(t)) || (filter === "done" && fin(t)) || (filter === "late" && late(t))) &&
      (!whoF || (whoF === "__none" ? !people(t.who).length : people(t.who).includes(whoF))));
    const byDue = (a, b) => (a.due || "9999").localeCompare(b.due || "9999");
    list.sort((a, b) => (fin(a) - fin(b)) || (
      sortBy === "pri" ? (PRI[a.pri] - PRI[b.pri]) || byDue(a, b) :
      sortBy === "who" ? (a.who || "\uffff").localeCompare(b.who || "\uffff", "zh-Hant") || byDue(a, b) :
      sortBy === "add" ? (a.n - b.n) : byDue(a, b) || (PRI[a.pri] - PRI[b.pri])));

    const ro = isAdmin ? "" : "disabled";
    const canComplete = isAdmin || tasks.some(t=>t.member_completion_allowed);
    const head = `<div class="tk h"><span>完成狀態</span><span>工作主題</span><span>負責者</span><span>截止</span><span>優先</span><span>目標</span><span>進度回報／歷史成果</span>${isAdmin ? "<span>完成時間</span><span></span>" : ""}</div>`;
    $("#tkTable").innerHTML = head + (list.length ? list.map(t => `
      <div class="tk ${t.done ? "rep" : ""} ${isAdmin && t.done ? "done" : ""} ${late(t) ? "late" : ""}" data-id="${t.id}">
        <div class="ckc"><label class="ck"><input type="checkbox" data-k="done" ${t.done ? "checked" : ""} ${canComplete?"":"disabled"} aria-label="工作主題完成"></label><span class="when">${t.done ? "已完成" : late(t) ? "已逾期" : "進行中"}</span><div class="task-save-feedback" data-save-feedback>${isAdmin||saveStates.has(t.id)?stateMarkup(t.id):""}</div></div>
        <textarea class="in task" rows="1" ${ro} data-k="task" aria-label="工作內容">${esc(t.task)}</textarea>
        <div class="whos" data-k2="who">${(() => { const p = people(t.who).slice(0, 4); const n = isAdmin ? Math.min(4, p.length + 1) : Math.max(1, p.length); return Array.from({ length: n }, (_, i) => `<span class="who-control"><input class="in w" ${ro} value="${esc(p[i] || "")}" list="whoList" placeholder="${i ? (isAdmin ? "＋負責者" : "") : "未指派"}" aria-label="負責者 ${i + 1}">${isAdmin?'<button type="button" class="who-picker" aria-label="選擇負責者"><svg aria-hidden="true" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg></button>':''}</span>`).join(""); })()}</div>
        <input class="in" type="date" ${ro} data-k="due" value="${esc(t.due)}" aria-label="截止">
        <select class="in pri p${PRI[t.pri]}" ${ro} data-k="pri" aria-label="優先級">${["高", "中", "低"].map(p => `<option${p === t.pri ? " selected" : ""}>${p}</option>`).join("")}</select>
        <textarea class="in" rows="1" ${ro} data-k="note" placeholder="—" aria-label="目標" maxlength="10000" title="目標上限 10,000 字">${esc(t.note)}</textarea>
        <div class="resultbox">
          <button type="button" class="btn ghost" data-task-reports="${esc(t.id)}">查看回報（${t.report_count||0}）</button>
          ${t.latest_report ? `<div class="tk-latest-report"><small class="tk-latest-label">最近回報</small><small class="tk-latest-date"><span>${esc(t.latest_report.created.slice(0,10).replaceAll("-","/"))}</span><span>${esc(t.latest_report.created.slice(11,16))}</span></small><div class="tk-latest-field"><small class="tk-latest-field-label">主題</small><small class="tk-latest-subject" title="${esc(t.latest_report.subject)}">${esc(t.latest_report.subject)}</small></div><div class="tk-latest-field"><small class="tk-latest-field-label">內容</small><small class="tk-latest-content" title="${esc(t.latest_report.content.slice(0,300))}">${esc(t.latest_report.content.slice(0,90))}</small></div></div>` : '<small>尚無關聯回報</small>'}
          <button type="button" class="btn ghost" data-task-add="${esc(t.id)}">新增回報</button>
          ${t.result || (t.attachments||[]).length ? `<details><summary>歷史成果與附件（唯讀）</summary><p>${esc(t.result)}</p>${(t.attachments||[]).map(a=>`<p><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.original_name)}</a></p>`).join('')}</details>` : ''}
        </div>
        ${isAdmin ? `<div class="ckc rv"><input class="in dt" type="datetime-local" data-k="done_date" value="${esc(dtIn(t.done_date))}" aria-label="完成時間"></div>
        <button class="del" data-del="${t.id}" title="刪除" aria-label="刪除">×</button>` : ""}
      </div>`).join("") : `<div class="tk empty">${rev ? "沒有符合條件的工作。" : "正在載入共用清單…"}</div>`);
    grow();
  }

  function grow() { document.querySelectorAll("#tkTable textarea").forEach(el => { el.style.height = "auto"; el.style.height = el.scrollHeight + 2 + "px"; }); }
  window.addEventListener("resize", grow);
  document.addEventListener("click", e => { if (e.target.closest('[data-view="plan"]')) setTimeout(grow, 30); });

  // 新增
  $("#tkForm").addEventListener("submit", async e => {
    e.preventDefault();
    const task = $("#fTask").value.trim(); if (!task) return;
    const btn = e.submitter; if (btn) btn.disabled = true;
    try {
      await call("POST", "/api/tasks", { task, who: joinP(["#fWho", "#fWho2", "#fWho3", "#fWho4"].map(s => $(s).value)), due: $("#fDue").value, pri: $("#fPri").value, note: $("#fNote").value.trim(), done: false });
      ["#fTask", "#fNote", "#fDue", "#fWho", "#fWho2", "#fWho3", "#fWho4"].forEach(s => $(s).value = ""); $("#fTask").focus();
    } catch (e) {} finally { if (btn) btn.disabled = false; }
  });

  // 編輯
  const tbl = $("#tkTable");
  tbl.addEventListener("change", e => {
    const el = e.target, row = el.closest(".tk"); if (!row) return;
    if (el.dataset.upload) {
      const f = el.files && el.files[0]; if (!f) return;
      if (f.size > 50 * 1024 * 1024) { alert("單一附件上限為 50 MB。"); el.value=""; return; }
      const ok = confirm(`確認上傳附件？\n\n檔案：${f.name}\n\n⚠️ 請確認檔案內容與版本正確。\n附件一旦上傳，一般組員無法自行刪除，僅管理者有權限刪除。`);
      if (!ok) { el.value=""; return; }
      const lab=el.closest(".uploadbtn"), old=lab.firstChild.textContent; lab.firstChild.textContent="上傳中…"; el.disabled=true; pending=true;
      fetch(API + "/api/tasks/" + el.dataset.upload + "/attachments", {method:"POST", headers:{"Content-Type":f.type||"application/octet-stream","X-File-Name":encodeURIComponent(f.name),...hdr()}, body:f})
        .then(async r=>{ if(!r.ok){let d={};try{d=await r.json()}catch(_){};throw new Error(d.error||r.status)} return r.json(); })
        .then(d=>{apply(d);setSync(true);render();})
        .catch(err=>{alert("附件上傳失敗："+err.message);setSync(false);})
        .finally(()=>{pending=false;}); return;
    }
    if (el.classList.contains("w")) {
      const who = joinP([...el.closest(".whos").querySelectorAll("input")].flatMap(i => people(i.value)));
      saveTask(row.dataset.id, { who }); return;
    }
    if (!el.dataset.k) return;
    const val = el.type === "checkbox" ? el.checked : el.value.trim();
    saveTask(row.dataset.id, { [el.dataset.k]: val });
  });
  tbl.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && e.target.matches(".in")) { e.preventDefault(); e.target.blur(); } });
  tbl.addEventListener("input", e => { if (e.target.tagName === "TEXTAREA") { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + 2 + "px"; } });
  tbl.addEventListener('focusout',()=>setTimeout(()=>{if(taskRenderNeeded&&!taskPending&&!editing()){render();taskRenderNeeded=false;}},0));
  tbl.addEventListener("click", e => {
    const picker=e.target.closest('.who-picker');
    if(picker){const input=picker.parentElement.querySelector('input');input.focus();try{input.showPicker?.();}catch{};return;}
    const retry=e.target.closest('[data-task-retry]');
    if(retry){saveTask(retry.dataset.taskRetry,taskDrafts.get(retry.dataset.taskRetry)||{});return;}

    const add=e.target.closest("[data-task-add]");
    if(add){window.dispatchEvent(new CustomEvent("xle-progress-task",{detail:{taskId:add.dataset.taskAdd,openForm:true}}));document.querySelector('[data-view="progress"]').click();return;}
    const link=e.target.closest("[data-task-reports]");
    if(link){window.dispatchEvent(new CustomEvent("xle-progress-task",{detail:{taskId:link.dataset.taskReports}}));document.querySelector('[data-view="progress"]').click();return;}
    const aid=e.target.dataset.attdel;
    if(aid){ if(confirm("刪除這個附件？")) call("DELETE","/api/attachments/"+aid).catch(()=>{}); return; }
    const id = e.target.dataset.del; if (!id) return;
    const t = tasks.find(x => x.id === id);
    xleDialog({title:'確認刪除工作主題',message:'工作：'+(t?t.task:'')+'\\n刪除後工作清單不再顯示，但既有進度回報仍會保留。',danger:true,label:'確認刪除'}).then(ok=>{if(ok)call("DELETE","/api/tasks/"+id).catch(()=>{});});
  });

  // 篩選與排序
  $("#tkFilter").addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    filter = b.dataset.f; document.querySelectorAll("#tkFilter button").forEach(x => x.classList.toggle("on", x === b)); render();
  });
  $("#tkWho").addEventListener("change", e => { whoF = e.target.value; render(); });
  $("#tkSort").addEventListener("change", e => { sortBy = e.target.value; render(); });

  // 匯出／匯入
  const stamp = () => { const d = new Date(); const p = n => String(n).padStart(2, "0"); return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}`; };
  function dl(name, text, type) {
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name;
    document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  $("#tkExport").addEventListener("click", () => dl(`XLeRobot-分工時程-${stamp()}.json`, JSON.stringify({ app: "xlerobot-tasks", v: 2, exported: new Date().toISOString(), tasks }, null, 2), "application/json"));
  $("#tkCsv").addEventListener("click", () => {
    const q = s => `"${String(s ?? "").replace(/"/g, '""')}"`;
    const H = ["工作完成狀態", "工作內容", "負責者", "截止", "優先級", "目標", "歷史成果"].concat(isAdmin ? ["完成時間"] : []).concat(["歷史：組員回報完成", "歷史：組員回報時間"]);
    const rows = [H].concat(tasks.map(t => [t.done ? "已完成" : "未完成", t.task, t.who, t.due, t.pri, t.note, t.result].concat(isAdmin ? [t.done_date || ""] : []).concat([t.member_done ? "是" : "否", t.member_done_at])));
    dl(`XLeRobot-分工時程-${stamp()}.csv`, "\ufeff" + rows.map(r => r.map(q).join(",")).join("\r\n"), "text/csv");
  });
  $("#tkImport").addEventListener("change", e => {
    const f = e.target.files[0]; if (!f) return;
    f.text().then(txt => {
      const d = JSON.parse(txt); const arr = Array.isArray(d) ? d : d.tasks;
      if (!Array.isArray(arr)) throw 0;
      const replace = confirm(`讀到 ${arr.length} 項工作。\n按「確定」取代全組目前的清單；按「取消」合併進去。`);
      return call("POST", "/api/import", { mode: replace ? "replace" : "merge", tasks: arr });
    }).catch(err => { if (err === 0 || err instanceof SyntaxError) alert("檔案格式不正確，請選擇從這裡匯出的 JSON 檔。"); }).finally(() => { e.target.value = ""; });
  });
  $("#tkReset").addEventListener("click", () => {
    if (confirm("把全組的清單還原成預設（1005 討論的待辦）？所有人的修改都會被清除，建議先匯出備份。")) call("POST", "/api/reset").catch(() => {});
  });

  $("#tkAdmin").addEventListener("click", async () => {
    if (isAdmin) { if (!confirm("登出管理者？")) return; adminKey = ""; isAdmin = false; ls && ls.removeItem("xle-admin"); adminUI(); refetch(); return; }
    const k = (prompt("輸入管理者密碼") || "").trim(); if (!k) return;
    adminKey = k; await checkAdmin();
    if (isAdmin) { ls && ls.setItem("xle-admin", k); } else alert("密碼不正確。");
    adminUI(); refetch();
  });
  function refetch() { return fetch(API + "/api/tasks", { headers: hdr(), cache: "no-store" }).then(r => r.json()).then(d => { apply(d); render(); setSync(true); }).catch(() => setSync(false)); }
  checkAdmin().then(() => { adminUI(); refetch(); });

  render();
  fetch(API + "/api/tasks", { headers: hdr(), cache: "no-store" }).then(r => { if (!r.ok) throw 0; return r.json(); })
    .then(d => { apply(d); render(); setSync(true); }).catch(() => setSync(false)).finally(() => setTimeout(poll, 3000));
})();


