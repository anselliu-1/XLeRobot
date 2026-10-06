// 分工 & 時程：可互動工作表（資料存在本機瀏覽器）
(function () {
  const KEY = "xlerobot-tasks-v1";
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const today = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  // 共用資料：後端 API（全組同步）
  const API = "port/8000".startsWith("__") ? "http://localhost:8000" : "port/8000";
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
  }
  let filter = "all", whoF = "", sortBy = "due";

  function setSync(ok, msg) {
    online = ok; const el = $("#tkSync"); if (!el) return;
    el.className = "sync " + (ok ? "ok" : "bad");
    el.querySelector("span").textContent = msg || (ok ? "已連線・全組即時同步（最後同步 " + new Date().toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + "）" : "連線中斷，正在重試…（此時修改不會儲存）");
  }
  // 負責者可多人：以「、」分隔儲存
  const people = w => String(w || "").split(/[、,，;；\/]+/).map(x => x.trim()).filter(Boolean);
  const joinP = arr => [...new Set(arr.map(x => x.trim()).filter(Boolean))].slice(0, 4).join("、");
  const norm = t => ({ ...t, who: t.who || "", due: t.due || "", done_date: t.done_date || "", note: t.note || "", result: t.result || "", member_done_at: t.member_done_at || "" });
  function apply(d) { if (d && Array.isArray(d.tasks)) { tasks = d.tasks.map(norm); rev = d.rev; } }
  async function call(method, path, body) {
    pending = true;
    try {
      const r = await fetch(API + path, { method, headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...hdr() }, body: body ? JSON.stringify(body) : undefined });
      if (r.status === 403) { render(); alert("這個欄位只有管理者能修改。組員可以勾選「回報完成」和填寫「成果」。"); throw new Error("403"); }
      if (!r.ok) throw new Error(r.status);
      const d = await r.json(); apply(d); setSync(true); render(); return d;
    } catch (e) { if (e.message !== "403") { setSync(false); alert("無法儲存到共用清單，請檢查網路後再試一次。"); } throw e; }
    finally { pending = false; }
  }
  const editing = () => { const a = document.activeElement; return a && a.closest && a.closest("#tkTable") && a.matches(".in"); };
  async function poll() {
    if (!pending && !editing()) {
      try {
        const r = await fetch(API + "/api/tasks?since=" + rev, { headers: hdr(), cache: "no-store" });
        if (!r.ok) throw new Error(r.status);
        const d = await r.json();
        if (!d.unchanged) { apply(d); render(); }
        setSync(true);
      } catch (e) { setSync(false); }
    }
    setTimeout(poll, document.hidden ? 10000 : 3000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !editing()) fetch(API + "/api/tasks", { headers: hdr(), cache: "no-store" }).then(r => r.json()).then(d => { apply(d); render(); setSync(true); }).catch(() => setSync(false)); });

  const fin = t => isAdmin ? !!t.done : !!t.member_done;   // 管理者看複檢，組員看回報
  const late = t => !t.member_done && !t.done && t.due && t.due < today();
  const PRI = { "高": 0, "中": 1, "低": 2 };
  const dtIn = v => (v || "").replace(" ", "T");
  const shortDT = v => v ? v.slice(5).replace("-", "/") : "";

  function render() {
    // 負責者清單
    const whos = [...new Set(tasks.flatMap(t => people(t.who)))].sort((a, b) => a.localeCompare(b, "zh-Hant"));
    $("#whoList").innerHTML = whos.map(w => `<option value="${esc(w)}">`).join("");
    const sel = $("#tkWho");
    if (whoF && !whos.includes(whoF)) whoF = "";
    sel.innerHTML = `<option value="">所有負責者</option><option value="__none"${whoF === "__none" ? " selected" : ""}>未指派</option>` + whos.map(w => `<option${w === whoF ? " selected" : ""}>${esc(w)}</option>`).join("");

    // 統計
    const total = tasks.length, rep = tasks.filter(t => t.member_done).length, chk = tasks.filter(t => t.done).length,
      lt = tasks.filter(late).length, none = tasks.filter(t => !people(t.who).length).length;
    const pct = total ? Math.round(rep / total * 100) : 0, pct2 = total ? Math.round(chk / total * 100) : 0;
    const per = whos.map(w => { const a = tasks.filter(t => people(t.who).includes(w)); const d = a.filter(t => t.member_done).length; return `<span class="chip"><b>${esc(w)}</b> ${d}/${a.length}</span>`; }).join("");
    $("#tkStats").innerHTML = `
      <div class="st"><span>組員回報完成</span><b>${rep} / ${total}</b><div class="pbar"><i style="width:${pct}%"></i></div></div>
      ${isAdmin ? `<div class="st adm"><span>組長已複檢</span><b>${chk} / ${total}</b><div class="pbar"><i style="width:${pct2}%"></i></div></div>` : `<div class="st"><span>未完成</span><b>${total - rep}</b></div>`}
      <div class="st ${lt ? "warn" : ""}"><span>已逾期</span><b>${lt}</b></div>
      <div class="st"><span>未指派</span><b>${none}</b></div>
      ${per ? `<div class="st wide"><span>各負責者回報完成數</span><div class="chips">${per}</div></div>` : ""}`;

    // 列表
    let list = tasks.filter(t =>
      (filter === "all" || (filter === "todo" && !fin(t)) || (filter === "done" && fin(t)) || (filter === "late" && late(t))) &&
      (!whoF || (whoF === "__none" ? !people(t.who).length : people(t.who).includes(whoF))));
    const byDue = (a, b) => (a.due || "9999").localeCompare(b.due || "9999");
    list.sort((a, b) => (fin(a) - fin(b)) || (
      sortBy === "pri" ? (PRI[a.pri] - PRI[b.pri]) || byDue(a, b) :
      sortBy === "who" ? (a.who || "\uffff").localeCompare(b.who || "\uffff", "zh-Hant") || byDue(a, b) :
      sortBy === "add" ? (a.n - b.n) : byDue(a, b) || (PRI[a.pri] - PRI[b.pri])));

    const ro = isAdmin ? "" : "disabled";
    const head = `<div class="tk h"><span>回報完成</span><span>工作內容</span><span>負責者</span><span>截止</span><span>優先</span><span>備註</span><span>成果</span>${isAdmin ? "<span>組長複檢</span><span></span>" : ""}</div>`;
    $("#tkTable").innerHTML = head + (list.length ? list.map(t => `
      <div class="tk ${t.member_done ? "rep" : ""} ${isAdmin && t.done ? "done" : ""} ${late(t) ? "late" : ""}" data-id="${t.id}">
        <div class="ckc"><label class="ck"><input type="checkbox" data-k="member_done" ${t.member_done ? "checked" : ""} aria-label="組員回報完成"></label><span class="when">${t.member_done_at ? esc(shortDT(t.member_done_at)) : "未回報"}</span></div>
        <textarea class="in task" rows="1" ${ro} data-k="task" aria-label="工作內容">${esc(t.task)}</textarea>
        <div class="whos" data-k2="who">${(() => { const p = people(t.who).slice(0, 4); const n = isAdmin ? Math.min(4, p.length + 1) : Math.max(1, p.length); return Array.from({ length: n }, (_, i) => `<input class="in w" ${ro} value="${esc(p[i] || "")}" list="whoList" placeholder="${i ? (isAdmin ? "＋負責者" : "") : "未指派"}" aria-label="負責者 ${i + 1}">`).join(""); })()}</div>
        <input class="in" type="date" ${ro} data-k="due" value="${esc(t.due)}" aria-label="截止">
        <select class="in pri p${PRI[t.pri]}" ${ro} data-k="pri" aria-label="優先級">${["高", "中", "低"].map(p => `<option${p === t.pri ? " selected" : ""}>${p}</option>`).join("")}</select>
        <textarea class="in" rows="1" ${ro} data-k="note" placeholder="—" aria-label="備註">${esc(t.note)}</textarea>
        <textarea class="in res" rows="1" data-k="result" placeholder="填寫成果、量測數據或連結" aria-label="成果">${esc(t.result)}</textarea>
        ${isAdmin ? `<div class="ckc rv"><label class="ck"><input type="checkbox" data-k="done" ${t.done ? "checked" : ""} aria-label="組長複檢確認"></label><input class="in dt" type="datetime-local" data-k="done_date" value="${esc(dtIn(t.done_date))}" aria-label="複檢確認時間"></div>
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
    if (el.classList.contains("w")) {
      const who = joinP([...el.closest(".whos").querySelectorAll("input")].flatMap(i => people(i.value)));
      call("PATCH", "/api/tasks/" + row.dataset.id, { who }).catch(() => {}); return;
    }
    if (!el.dataset.k) return;
    const val = el.type === "checkbox" ? el.checked : el.value.trim();
    call("PATCH", "/api/tasks/" + row.dataset.id, { [el.dataset.k]: val }).catch(() => {});
  });
  tbl.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && e.target.matches(".in")) { e.preventDefault(); e.target.blur(); } });
  tbl.addEventListener("input", e => { if (e.target.tagName === "TEXTAREA") { e.target.style.height = "auto"; e.target.style.height = e.target.scrollHeight + 2 + "px"; } });
  tbl.addEventListener("click", e => {
    const id = e.target.dataset.del; if (!id) return;
    const t = tasks.find(x => x.id === id);
    if (confirm("刪除這項工作？全組都會看不到。\n" + (t ? t.task : ""))) call("DELETE", "/api/tasks/" + id).catch(() => {});
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
    const H = ["回報完成", "回報完成時間", "工作內容", "負責者", "截止", "優先級", "備註", "成果"].concat(isAdmin ? ["組長複檢", "複檢確認時間"] : []);
    const rows = [H].concat(tasks.map(t => [t.member_done ? "是" : "否", t.member_done_at, t.task, t.who, t.due, t.pri, t.note, t.result].concat(isAdmin ? [t.done ? "是" : "否", t.done_date || ""] : [])));
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
