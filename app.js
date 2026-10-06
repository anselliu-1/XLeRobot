(() => {
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const T = { A: "ta", B: "tb", C: "tc" };
  const byId = id => IDEAS.find(i => i.id === id);
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const state = { cat: "all", sort: "feas", only: false, pgroup: "全部", checks: new Set() };

  // 主題
  const root = document.documentElement;
  root.dataset.theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  $("#theme").onclick = () => root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";

  // 分頁
  function go(v) {
    $$(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.view === v));
    $$(".view").forEach(s => s.classList.toggle("on", s.id === v));
    window.scrollTo({ top: 0 });
  }
  $$(".tabs button").forEach(b => b.onclick = () => go(b.dataset.view));

  // 總覽：分類卡
  $("#catCards").innerHTML = Object.entries(CATS).map(([k, c]) => {
    const n = IDEAS.filter(i => i.cat === k).length;
    return `<article class="cat ${T[k]}"><div class="cnt">${n}</div><h3><span class="tag">${k}</span>${c.name}</h3><p>${c.desc}</p>
      ${k === "C" ? `<p style="color:var(--c)">建議：只列為「未來工作」，或先找出 A／B 類替代做法。</p>` : ""}
      <button class="btn go" data-go="${k}">看 ${k} 類方向</button></article>`;
  }).join("");
  $$("[data-go]").forEach(b => b.onclick = () => { setCat(b.dataset.go); go("ideas"); });

  // 組合方案
  $("#combos").innerHTML = COMBOS.map((c, i) => `<article class="combo ${i === 0 ? "best" : ""}">
    <span class="lv">${c.level}</span><h3>${c.name}</h3><p>${c.story}</p>
    <div class="parts">${c.ids.map(id => { const d = byId(id); return `<button data-open="${id}"><span class="tag ${T[d.cat]}">${d.cat}</span>${d.title}</button>`; }).join("")}</div>
    <div class="ph">${c.phase}</div></article>`).join("");

  // 規格
  $("#specs").innerHTML = SPECS.map(s => `<div class="spec"><b>${s.k}</b><span>${s.v}${s.src >= 0 ? `<a href="${SOURCES[s.src === 2 ? 2 : s.src].u}" target="_blank" rel="noopener">[${SOURCES[s.src].n.replace("XLeRobot ", "")}]</a>` : ""}</span></div>`).join("");

  // 方向清單
  function setCat(c) {
    state.cat = c;
    $$("#catFilter button").forEach(b => b.classList.toggle("on", b.dataset.c === c));
    $("#catDesc").textContent = c === "all" ? "共 " + IDEAS.length + " 個方向。點卡片看情境、困難點、展出疑慮、教授問題與復原方式。" : CATS[c].desc;
    renderGrid();
  }
  $$("#catFilter button").forEach(b => b.onclick = () => setCat(b.dataset.c));
  $("#sort").onchange = e => { state.sort = e.target.value; renderGrid(); };
  $("#onlyPick").onchange = e => { state.only = e.target.checked; renderGrid(); };
  const dots = (n, cls) => `<div class="dots">${[1, 2, 3, 4, 5].map(i => `<i class="${i <= n ? "f" : ""}"></i>`).join("")}</div>`;
  function renderGrid() {
    let list = IDEAS.filter(i => (state.cat === "all" || i.cat === state.cat) && (!state.only || i.pick));
    list.sort((a, b) => b[state.sort] - a[state.sort] || a.cat.localeCompare(b.cat));
    $("#grid").innerHTML = list.length ? list.map(i => `<button class="card ${T[i.cat]}" data-open="${i.id}">
      <div class="hd"><span class="tag">${i.cat}・${CATS[i.cat].short}</span>${i.pick ? `<span class="pick">推薦</span>` : ""}<span class="diff" style="margin-left:auto;color:var(--muted)">難度 ${i.diff}</span></div>
      <h3>${i.title}</h3><p>${i.tagline}</p>
      <div class="meters"><div class="meter"><small>可行性</small>${dots(i.feas)}</div><div class="meter"><small>展示效果</small>${dots(i.demo)}</div><div class="meter"><small>創新空間</small>${dots(i.novelty)}</div></div>
    </button>`).join("") : `<p class="muted">沒有符合的方向，取消「只看推薦」試試。</p>`;
    bindOpen();
  }

  // 詳細抽屜
  function openIdea(id) {
    const i = byId(id); if (!i) return;
    const list = a => `<ul>${a.map(x => `<li>${x}</li>`).join("")}</ul>`;
    $("#dBody").innerHTML = `<div class="${T[i.cat]}"><span class="tag">${i.cat}・${CATS[i.cat].name}</span></div>
      <h2 id="dTitle">${i.title}</h2><p class="tagline">${i.tagline}</p>
      <div class="dmeta"><span>可行性 ${i.feas}/5</span><span>展示效果 ${i.demo}/5</span><span>創新空間 ${i.novelty}/5</span><span>難度 ${i.diff}</span></div>
      <div class="blk"><h4>應用情境</h4><p>${i.scene}</p></div>
      <div class="two"><div class="blk"><h4>需要的設備與成本</h4><p>${i.hw}</p></div><div class="blk"><h4>技術組成</h4><p>${i.stack}</p></div></div>
      <div class="two" style="margin-top:10px"><div class="blk"><h4>先做：半自動</h4><p>${i.semi}</p></div><div class="blk"><h4>再挑戰：全自動</h4><p>${i.full}</p></div></div>
      <div class="blk warn" style="margin-top:10px"><h4>困難點</h4>${list(i.hard)}</div>
      <div class="blk"><h4>展出時的疑慮</h4>${list(i.expo)}</div>
      <div class="blk"><h4>教授可能會問</h4>${i.prof.map(p => `<div class="dqa"><b>Q：${p.q}</b><p>回答方向：${p.a}</p></div>`).join("")}</div>
      <div class="two"><div class="blk"><h4>量化指標</h4>${list(i.metrics)}</div><div class="blk"><h4>失敗降級方案</h4><p>${i.fallback}</p></div></div>
      ${i.alt ? `<div class="blk alt" style="margin-top:10px"><h4>不改機器的替代做法</h4><p>${i.alt}</p></div>` : ""}
      <div class="blk" style="margin-top:10px"><h4>歸還前復原</h4><p>${i.restore}</p></div>`;
    $("#drawerBg").classList.add("open"); $("#drawerBg").setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden"; $("#dClose").focus();
  }
  function closeD() { $("#drawerBg").classList.remove("open"); $("#drawerBg").setAttribute("aria-hidden", "true"); document.body.style.overflow = ""; }
  $("#dClose").onclick = closeD;
  $("#drawerBg").onclick = e => { if (e.target.id === "drawerBg") closeD(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeD(); });
  function bindOpen() { $$("[data-open]").forEach(b => b.onclick = () => openIdea(b.dataset.open)); }

  // 困難
  $("#hards").innerHTML = HARDS.map(h => `<div class="hard ${h.lv === "高" ? "hi" : ""}"><h3>${h.t}<span>影響 ${h.lv}</span></h3><p>${h.d}</p></div>`).join("");
  $("#expo").innerHTML = EXPO.map(e => `<div class="ex"><b>${e.t}</b><span class="d">${e.d}</span><span class="f">${e.fix}</span></div>`).join("");

  // 教授問答
  const groups = ["全部", ...new Set(PROF.map(p => p.g))];
  $("#profFilter").innerHTML = groups.map(g => `<button data-g="${g}" class="${g === "全部" ? "on" : ""}">${g}</button>`).join("");
  $$("#profFilter button").forEach(b => b.onclick = () => { state.pgroup = b.dataset.g; $$("#profFilter button").forEach(x => x.classList.toggle("on", x === b)); renderQA(); });
  function renderQA() {
    $("#qa").innerHTML = PROF.filter(p => state.pgroup === "全部" || p.g === state.pgroup).map(p => `<div class="q"><button aria-expanded="false"><span class="g">${p.g}</span><span class="t">${p.q}</span><span class="ic">＋</span></button><div class="a">${p.a}</div></div>`).join("");
    $$(".q button").forEach(b => b.onclick = () => { const q = b.parentElement; q.classList.toggle("open"); b.setAttribute("aria-expanded", q.classList.contains("open")); });
  }
  $("#revealAll").onclick = () => { const all = $$(".q"); const open = !all.every(q => q.classList.contains("open")); all.forEach(q => q.classList.toggle("open", open)); $("#revealAll").textContent = open ? "全部收合" : "全部展開"; };

  // 歸還守則
  const rg = [...new Set(RULES.map(r => r.g))];
  $("#ruleList").innerHTML = rg.map(g => `<div class="rgroup"><h3>${g}</h3>${RULES.map((r, i) => r.g === g ? `<label class="rule"><input type="checkbox" data-r="${i}"><span>${r.t}</span></label>` : "").join("")}</div>`).join("");
  function prog() { const n = state.checks.size, t = RULES.length; $("#progNum").textContent = `${n}/${t}`; $("#progBar").style.width = (n / t * 100) + "%"; }
  $$("[data-r]").forEach(c => c.onchange = () => { c.checked ? state.checks.add(c.dataset.r) : state.checks.delete(c.dataset.r); c.parentElement.classList.toggle("done", c.checked); prog(); });
  prog();

  // 時程
  $("#timeline").innerHTML = PLAN.map((p, i) => `<li class="${i === 3 ? "key" : ""}"><span class="w">${p.w}</span><h3>${p.t}</h3><ul>${p.items.map(x => `<li>${x}</li>`).join("")}</ul><span class="out">產出：${p.out}</span></li>`).join("");

  // 依據
  $("#srcs").innerHTML = SOURCES.map(s => `<div class="src"><a href="${s.u}" target="_blank" rel="noopener">${s.n}</a><p>${s.d}</p></div>`).join("");

  // 我的硬體
  const TT = { a: "ta", b: "tb", c: "tc" };
  $("#hwNote").textContent = "整理自先前的對話紀錄與你提供的鍵盤控制程式（更新於 " + MYHW.updated + "）。需歸還的設備（學校財產、教授資產）以紅色標示。";
  $("#hwGroups").innerHTML = MYHW.groups.map(g => `<article class="hw ${TT[g.tone]}"><header><h3>${g.name}</h3><span class="tag">${g.owner}</span></header>${g.rows.map(r => `<div class="row"><b>${r[0]}</b><span>${r[1]}</span></div>`).join("")}</article>`).join("");
  $("#hwIssues").innerHTML = MYHW.issues.map(h => `<div class="hard ${h.lv === "高" ? "hi" : ""}"><h3>${h.t}<span>影響 ${h.lv}</span></h3><p>${h.d}</p></div>`).join("");
  $("#hwKeys").innerHTML = MYHW.keys.map(k => `<div class="key"><kbd>${k[0]}</kbd><span>${k[1]}</span></div>`).join("");
  $("#hwProt").innerHTML = MYHW.protections.map(x => `<li>${x}</li>`).join("");
  $("#hwImpact").innerHTML = MYHW.impact.map(h => `<div class="hard"><h3>${h.t}</h3><p>${h.d}</p></div>`).join("");
  $("#hwUnknown").innerHTML = MYHW.unknown.map(u => `<li>${u}</li>`).join("");

  // 供電方案
  const PW = POWER;
  $("#pwVerdict").innerHTML = "<b>結論　</b>" + PW.verdict;
  $("#pwTabs").innerHTML = PW.plans.map((p, i) => `<button data-p="${p.id}" class="${i === 0 ? "on" : ""}">${p.name.split("：")[0]}</button>`).join("");
  const col = v => v === "12V" ? "var(--c)" : v === "20V" ? "var(--b)" : "var(--accent)";
  function wrap(s, n) { const W = t => [...t].reduce((x, ch) => x + (/[\x00-\x7f]/.test(ch) ? 0.55 : 1), 0); const toks = s.match(/[\x00-\x7f]+|[^\x00-\x7f]/g) || []; const out = []; let cur = ""; for (const t of toks) { if (W(cur + t) > n && cur.trim()) { out.push(cur.trim()); cur = ""; } cur += t; } if (cur.trim()) out.push(cur.trim()); return out; }
  function diagram(plan) {
    // 版面：行動電源 x=20..230，轉接 x=300..560，負載 x=640..900
    const rowH = 64, gap = 36;
    let y = 20, parts = [], defs = "";
    plan.banks.forEach(bank => {
      const nLoads = bank.links.reduce((s, l) => s + l.loads.length, 0);
      const h = nLoads * rowH;
      parts.push(`<rect x="20" y="${y}" width="180" height="${h - 12}" rx="10" fill="var(--card)" stroke="var(--ink)" stroke-width="1.5"/>`);
      const nm = bank.name.includes("：") ? bank.name.split("：") : ["行動電源", bank.name];
      parts.push(`<text x="34" y="${y + 26}" font-size="14" font-weight="700">${nm[0]}</text>`);
      wrap(nm[1], 11).forEach((t, i) => parts.push(`<text x="34" y="${y + 46 + i * 17}" class="sm">${t}</text>`));
      let ly = y;
      bank.links.forEach(l => {
        const n = l.loads.length, mid = ly + (n * rowH - 12) / 2;
        const v = l.out.startsWith("12") ? "12V" : "5V";
        const is20 = l.via.includes("20 V");
        // 孔
        parts.push(`<rect x="196" y="${mid - 12}" width="48" height="24" rx="5" fill="var(--surface)" stroke="var(--ink)"/>`);
        parts.push(`<text x="220" y="${mid + 4}" font-size="12" font-weight="700" text-anchor="middle">${l.port}</text>`);
        // 線到轉接
        parts.push(`<line x1="244" y1="${mid}" x2="300" y2="${mid}" stroke="${is20 ? col("20V") : col(v)}" stroke-width="3"/>`);
        // 轉接盒
        parts.push(`<rect x="300" y="${mid - 22}" width="260" height="44" rx="8" fill="var(--card)" stroke="${is20 ? col("20V") : "var(--line)"}" stroke-dasharray="${is20 ? "" : "4 3"}"/>`);
        const via = l.via.length > 20 ? [l.via.slice(0, l.via.indexOf("＋") > 0 ? l.via.indexOf("＋") : 20), l.via.slice(l.via.indexOf("＋") > 0 ? l.via.indexOf("＋") : 20)] : [l.via, ""];
        parts.push(`<text x="430" y="${mid - 4}" font-size="12.5" text-anchor="middle">${via[0]}</text>`);
        parts.push(`<text x="430" y="${mid + 13}" class="sm" text-anchor="middle">${via[1] ? via[1] : l.out}</text>`);
        l.loads.forEach((k, j) => {
          const L = PW.loads[k], cy = ly + j * rowH + (rowH - 12) / 2;
          parts.push(`<path d="M560 ${mid} C600 ${mid}, 600 ${cy}, 640 ${cy}" fill="none" stroke="${col(L.v)}" stroke-width="3" ${l.either ? 'stroke-dasharray="6 4"' : ""}/>`);
          parts.push(`<rect x="640" y="${cy - 22}" width="250" height="44" rx="8" fill="var(--card)" stroke="${col(L.v)}" stroke-width="1.5"/>`);
          parts.push(`<text x="656" y="${cy - 3}" font-size="13.5" font-weight="700">${L.n}${l.either ? "（二選一）" : ""}</text>`);
          parts.push(`<text x="656" y="${cy + 14}" class="sm">${L.s}</text>`);
        });
        if (n > 1 && !l.either) parts.push(`<text x="578" y="${mid - 30}" class="sm" text-anchor="middle">分接</text>`);
        ly += n * rowH;
      });
      y += h + gap;
    });
    const H = y - gap + 10;
    return `<svg viewBox="0 0 910 ${H}" role="img" aria-label="${plan.name} 接線圖">${parts.join("")}</svg>`;
  }
  function showPlan(id) {
    const p = PW.plans.find(x => x.id === id);
    $$("#pwTabs button").forEach(b => b.classList.toggle("on", b.dataset.p === id));
    $("#pwPlan").innerHTML = `<article class="plan"><h3>${p.name}</h3>
      <div class="meta"><span class="t">${p.tag}</span><span>額外花費 ${p.cost}</span></div>
      <p style="margin:0;color:var(--muted)">${p.summary}</p>
      <div class="diagram">${diagram(p)}</div>
      <div class="legend"><span><i style="background:var(--c)"></i>12 V 動力</span><span><i style="background:var(--b)"></i>20 V（降壓前）</span><span><i style="background:var(--accent)"></i>5 V 控制</span><span>虛線＝二選一</span></div>
      <div class="pc" style="margin-top:14px"><div class="blk"><h4>優點</h4><ul>${p.pros.map(x => `<li>${x}</li>`).join("")}</ul></div><div class="blk warn"><h4>缺點</h4><ul>${p.cons.map(x => `<li>${x}</li>`).join("")}</ul></div><div class="blk alt"><h4>什麼時候選</h4><p style="font-size:14px">${p.when}</p></div></div></article>`;
  }
  $$("#pwTabs button").forEach(b => b.onclick = () => showPlan(b.dataset.p));
  showPlan("p1");
  $("#pwNotes").innerHTML = PW.notes.map(x => `<li>${x}</li>`).join("");
  $("#pwEnergy").innerHTML = `<div class="tr h"><span>裝置</span><span>估計平均耗電</span><span>說明</span></div>` + PW.energy.map((r, i) => `<div class="tr ${i === PW.energy.length - 1 ? "total" : ""}"><span>${r[0]}</span><span>${r[1]}</span><span>${r[2]}</span></div>`).join("");
  $("#pwBuy").innerHTML = `<div class="tr h"><span>品項</span><span>數量／方案</span><span>注意</span></div>` + PW.buy.map(r => `<div class="tr"><span>${r[0]}</span><span>${r[1]}</span><span>${r[2]}</span></div>`).join("");

  // 組員接線圖
  const TW = TEAMWIRE;
  $("#twImg").src = TW.img;
  $("#twImg").onclick = () => window.open(TW.img, "_blank");
  $("#twVerdict").innerHTML = "<b>判斷　</b>" + TW.verdict;
  const lvCls = { "必改": "tc", "必確認": "tb", "注意": "ta", "建議": "" };
  $("#twChecks").innerHTML = TW.checks.map((c, i) => `<label class="rule chk2"><input type="checkbox"><span><span class="tag ${lvCls[c.lv]}">${c.lv}</span> <b>${c.t}</b><br><span class="cd">${c.d}</span></span></label>`).join("");
  $$("#twChecks input").forEach(c => c.onchange = () => c.parentElement.classList.toggle("done", c.checked));
  $("#twFix").innerHTML = `<div class="tr h"><span>孔位</span><span>線材</span><span>接到</span></div>` + TW.fix.map(r => `<div class="tr"><span>${r[0]}</span><span>${r[1]}</span><span>${r[2]}</span></div>`).join("");

  // 控制板接線圖
  const WR = WIRING;
  $("#wrMeta").textContent = `製作：${WR.author}　製作時間：${WR.recorded}（UTC+8）。點圖可放大。`;
  $("#wrVerdict").innerHTML = "<b>結論　</b>" + WR.verdict;
  $("#wrFigs").innerHTML = WR.figs.map(f => `<figure class="teamfig"><img src="${f.img}" alt="${esc(f.cap)}" loading="lazy" data-full="${f.img}"><figcaption>${f.cap}</figcaption></figure>`).join("");
  $$("#wrFigs img").forEach(i => i.onclick = () => window.open(i.dataset.full, "_blank"));
  const rows = (hd, rs) => `<div class="tr h">${hd.map(x => `<span>${x}</span>`).join("")}</div>` + rs.map(r => `<div class="tr">${r.map(x => `<span>${x}</span>`).join("")}</div>`).join("");
  $("#wrBoards").innerHTML = rows(["板子／元件", "電壓", "電流", "接孔"], WR.boards);
  $("#wrPorts").innerHTML = rows(["裝置", "圖 1 獨立供電版", "圖 3 只用行動電源版"], WR.ports);
  $("#wrCompare").innerHTML = rows(["面向", "獨立供電（圖 1）", "只用行動電源（圖 3）"], WR.compare);
  $("#wrBuy").innerHTML = rows(["品項", "數量", "注意"], WR.pbBuy);
  $("#wrTidy").innerHTML = WR.tidy.map(x => `<li>${x}</li>`).join("");
  $("#wrShared").innerHTML = WR.shared.map(x => `<li>${x}</li>`).join("");
  $("#wrConfirm").innerHTML = WR.confirm.map(x => `<li>${x}</li>`).join("");

  // 暫定方向與 1005 討論重點
  const MT = MEET, DR = MT.direction;
  $("#dirTitle").textContent = DR.title;
  $("#dirLead").textContent = DR.lead;
  $("#dirPoints").innerHTML = DR.points.map(r => `<div class="tr dp"><span><b>${r[0]}</b></span><span>${r[1]}</span></div>`).join("");
  $("#dirSteps").innerHTML = DR.steps.map(s => `<li>${s}</li>`).join("");
  $("#mtSrc").textContent = "來源：" + MT.src + "。";
  $("#mtBattery").innerHTML = "<b>電瓶供電　</b>" + MT.battery;
  $("#mtSecs").innerHTML = MT.sections.map(s => `<article class="hw"><header><h3>${s.t}</h3></header><ul class="prot" style="margin:0;border:0;border-radius:0;box-shadow:none;background:transparent">${s.items.map(x => `<li>${x}</li>`).join("")}</ul></article>`).join("");
  const lvc = { "高": "tc", "中": "tb" };
  $("#mtTodo").innerHTML = `<div class="tr h"><span>優先級＋待辦事項</span><span></span><span>建議產出</span></div>` + MT.todo.map(r => `<div class="tr"><span><span class="tag ${lvc[r[0]]}">${r[0]}</span> ${r[1]}</span><span></span><span>${r[2]}</span></div>`).join("");

  setCat("all"); renderQA(); bindOpen();
})();
