# XLeRobot 分工&時程 共用資料 API（Python 標準函式庫，SQLite）
import json, os, sqlite3, threading, time, uuid, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta

DB = os.environ.get("TASK_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))
PORT = int(os.environ.get("PORT", "8000"))
LOCK = threading.Lock()
TZ = timezone(timedelta(hours=8))
import hashlib, hmac
ADMIN_HASH = os.environ.get("ADMIN_KEY_HASH", "")
def is_admin(h):
    k = h.headers.get("X-Admin-Key", "")
    return bool(ADMIN_HASH and k) and hmac.compare_digest(hashlib.sha256(k.encode()).hexdigest(), ADMIN_HASH)
OWNER_FIELDS = ("done", "done_date")          # 組長複檢：只有管理者可見可改
PUBLIC_FIELDS = ("result", "member_done")       # 所有人可改：成果、組員回報完成
FIELDS = ("task", "who", "due", "done_date", "pri", "note", "done", "result", "member_done", "member_done_at")

SEED = [
    ("高", "確認電瓶電壓、容量、可供應電流及接頭", "規格表或產品頁截圖"),
    ("高", "量測單支與兩支手臂在待機、一般動作及堵轉附近的電流", "電流量測紀錄"),
    ("高", "依最大工作電流選擇保險絲、保險絲座、降壓板與線徑", "簡易配電圖與料表（先查實驗室庫存並詢問學長）"),
    ("高", "確認主電源板能否同時供應兩支手臂", "原廠規格＋實測結果"),
    ("中", "先用筆電／虛擬機完成手臂控制與狀態監測", "可重現的操作步驟、程式版本"),
    ("中", "測試夾爪抓取輕量物品並改善防滑", "抓取成功率與負載測試"),
    ("中", "評估相機方案，先完成單一物品辨識", "相機測試與辨識示範"),
    ("中", "整合車體、手臂與相機的展示流程", "可操作的最小展示版本"),
    ("中", "確認電瓶購買店家、發票品項與核銷方式", "採購清單"),
]

def conn():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def init():
    with LOCK, conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id TEXT PRIMARY KEY, n INTEGER, task TEXT NOT NULL, who TEXT DEFAULT '', due TEXT DEFAULT '',
            done_date TEXT DEFAULT '', pri TEXT DEFAULT '中', note TEXT DEFAULT '', done INTEGER DEFAULT 0, updated REAL)""")
        c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        cols = {r[1] for r in c.execute("PRAGMA table_info(tasks)")}
        for col, ddl in (("result", "TEXT DEFAULT ''"), ("member_done", "INTEGER DEFAULT 0"), ("member_done_at", "TEXT DEFAULT ''")):
            if col not in cols: c.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
        if c.execute("SELECT v FROM meta WHERE k='seeded'").fetchone() is None:
            seed(c)
            c.execute("INSERT OR REPLACE INTO meta VALUES('seeded','1')")
        if c.execute("SELECT v FROM meta WHERE k='rev'").fetchone() is None:
            c.execute("INSERT INTO meta VALUES('rev','1')")

def seed(c):
    c.execute("DELETE FROM tasks")
    now = time.time()
    for i, (p, t, note) in enumerate(SEED):
        c.execute("INSERT INTO tasks(id,n,task,pri,note,updated) VALUES(?,?,?,?,?,?)", ("s%d" % i, i, t, p, note, now))

def bump(c):
    r = int(c.execute("SELECT v FROM meta WHERE k='rev'").fetchone()[0]) + 1
    c.execute("UPDATE meta SET v=? WHERE k='rev'", (str(r),))
    return r

def rev(c):
    return int(c.execute("SELECT v FROM meta WHERE k='rev'").fetchone()[0])

def rows(c, admin=True):
    out = []
    for r in c.execute("SELECT * FROM tasks ORDER BY n"):
        d = dict(r); d["done"] = bool(d["done"]); d["member_done"] = bool(d.get("member_done"))
        for k in ("result", "member_done_at"): d[k] = d.get(k) or ""
        if not admin:
            d.pop("done", None); d.pop("done_date", None)
        out.append(d)
    return out

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DT = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$")
def clean(d, partial=False):
    o = {}
    for k in FIELDS:
        if k not in d:
            continue
        v = d[k]
        if k in ("done", "member_done"):
            o[k] = 1 if v else 0
        elif k == "due":
            v = str(v or "").strip()[:10]
            o[k] = v if (v == "" or DATE.match(v)) else ""
        elif k in ("done_date", "member_done_at"):
            v = str(v or "").strip().replace("T", " ")[:16]
            o[k] = v if (v == "" or DT.match(v)) else ""
        elif k in ("note", "result"):
            o[k] = str(v or "").strip()[:1000]
        elif k == "pri":
            o[k] = v if v in ("高", "中", "低") else "中"
        else:
            o[k] = str(v or "").strip()[:500]
    if not partial:
        o.setdefault("task", "")
    if "task" in o and not o["task"]:
        o["task"] = "（未命名工作）"
    return o

def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")

def now_s():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

class H(BaseHTTPRequestHandler):
    server_version = "xle/1"
    def log_message(self, *a): pass

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Key")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000: raise ValueError("too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def _path(self):
        p = self.path.split("?")[0].rstrip("/")
        i = p.find("/api/")
        return p[i:] if i >= 0 else p

    def do_OPTIONS(self): self._send(204, {})

    def do_GET(self):
        p = self._path()
        if p == "/api/health": return self._send(200, {"ok": True})
        if p == "/api/auth": return self._send(200 if is_admin(self) else 403, {"admin": is_admin(self)})
        if p == "/api/tasks":
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            since = dict(x.split("=", 1) for x in q.split("&") if "=" in x).get("since")
            with LOCK, conn() as c:
                r = rev(c)
                if since and since.isdigit() and int(since) == r:
                    return self._send(200, {"rev": r, "unchanged": True})
                return self._send(200, {"rev": r, "tasks": rows(c, is_admin(self))})
        self._send(404, {"error": "not found"})

    def _deny(self):
        if is_admin(self): return False
        self._send(403, {"error": "owner only"}); return True

    def do_POST(self):
        if self._deny(): return
        p = self._path()
        try: d = self._body()
        except Exception: return self._send(400, {"error": "bad json"})
        admin = is_admin(self)
        if p in ("/api/import", "/api/reset") and not admin:
            return self._send(403, {"error": "owner only"})
        with LOCK, conn() as c:
            if p == "/api/tasks":
                o = clean(d)
                if not admin: o.pop("done", None); o.pop("done_date", None)
                if o.get("done") and not o.get("done_date"): o["done_date"] = now_s()
                n = (c.execute("SELECT COALESCE(MAX(n),0) FROM tasks").fetchone()[0] or 0) + 1
                tid = uuid.uuid4().hex[:10]
                c.execute("INSERT INTO tasks(id,n,task,who,due,done_date,pri,note,done,result,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (tid, n, o["task"], o.get("who", ""), o.get("due", ""), o.get("done_date", ""), o.get("pri", "中"), o.get("note", ""), o.get("done", 0), o.get("result", ""), time.time()))
                r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c), "id": tid})
            if p == "/api/import":
                arr = d.get("tasks") if isinstance(d, dict) else None
                if not isinstance(arr, list): return self._send(400, {"error": "no tasks"})
                if d.get("mode") == "replace": c.execute("DELETE FROM tasks")
                n = (c.execute("SELECT COALESCE(MAX(n),0) FROM tasks").fetchone()[0] or 0)
                for t in arr[:1000]:
                    if not isinstance(t, dict) or not t.get("task"): continue
                    if "done_date" not in t and "doneDate" in t: t["done_date"] = t["doneDate"]
                    o = clean(t); n += 1
                    tid = str(t.get("id") or uuid.uuid4().hex[:10])[:40]
                    c.execute("INSERT OR REPLACE INTO tasks(id,n,task,who,due,done_date,pri,note,done,result,member_done,member_done_at,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (tid, n, o["task"], o.get("who", ""), o.get("due", ""), o.get("done_date", ""), o.get("pri", "中"), o.get("note", ""), o.get("done", 0), o.get("result", ""), o.get("member_done", 0), o.get("member_done_at", ""), time.time()))
                r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c)})
            if p == "/api/reset":
                seed(c); r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c)})
        self._send(404, {"error": "not found"})

    def do_PATCH(self):
        p = self._path()
        m = re.match(r"^/api/tasks/([\w-]+)$", p)
        if not m: return self._send(404, {"error": "not found"})
        try: d = self._body()
        except Exception: return self._send(400, {"error": "bad json"})
        admin = is_admin(self)
        o = clean(d, partial=True)
        if not admin:
            if any(k not in PUBLIC_FIELDS for k in o):
                return self._send(403, {"error": "owner only"})
        if not o: return self._send(400, {"error": "no fields"})
        with LOCK, conn() as c:
            cur = c.execute("SELECT * FROM tasks WHERE id=?", (m.group(1),)).fetchone()
            if not cur: return self._send(404, {"error": "gone"})
            if o.get("done") == 1 and not cur["done"] and not o.get("done_date"): o["done_date"] = now_s()
            if o.get("done") == 0 and "done_date" not in o: o["done_date"] = ""
            if o.get("member_done") == 1 and not cur["member_done"] and not o.get("member_done_at"): o["member_done_at"] = now_s()
            if o.get("member_done") == 0 and "member_done_at" not in o: o["member_done_at"] = ""
            sets = ",".join(f"{k}=?" for k in o) + ",updated=?"
            c.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*o.values(), time.time(), m.group(1)))
            r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c, admin)})

    def do_DELETE(self):
        if self._deny(): return
        m = re.match(r"^/api/tasks/([\w-]+)$", self._path())
        if not m: return self._send(404, {"error": "not found"})
        with LOCK, conn() as c:
            c.execute("DELETE FROM tasks WHERE id=?", (m.group(1),))
            r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c)})

if __name__ == "__main__":
    init()
    print(f"listening on {PORT}, db={DB}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
