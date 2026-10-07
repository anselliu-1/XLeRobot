# XLeRobot 分工&時程 共用資料 API（Python 標準函式庫，SQLite）
import json, os, sqlite3, threading, time, uuid, re, mimetypes, urllib.request, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
import hashlib, hmac

DB = os.environ.get("TASK_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))
PORT = int(os.environ.get("PORT", "8000"))
LOCK = threading.Lock()
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.path.dirname(DB), "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)
MAX_UPLOAD = 50 * 1024 * 1024
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".txt", ".csv"}
TZ = timezone(timedelta(hours=8))

# Railway Storage Bucket (S3-compatible). If these variables are present, new
# attachments are stored in the bucket; existing Volume attachments stay local.
S3_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "").rstrip("/")
S3_BUCKET = os.environ.get("AWS_S3_BUCKET_NAME", "")
S3_REGION = os.environ.get("AWS_DEFAULT_REGION", "auto") or "auto"
S3_ACCESS = os.environ.get("AWS_ACCESS_KEY_ID", "")
S3_SECRET = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
S3_ENABLED = all((S3_ENDPOINT, S3_BUCKET, S3_ACCESS, S3_SECRET))

def _sig_key(key, date, region, service="s3"):
    k_date = hmac.new(("AWS4" + key).encode(), date.encode(), hashlib.sha256).digest()
    k_region = hmac.new(k_date, region.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode(), hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()

def s3_request(method, key, data=None, content_type="application/octet-stream"):
    if not S3_ENABLED:
        raise RuntimeError("bucket not configured")
    key = key.lstrip("/")
    encoded_key = urllib.parse.quote(key, safe="/-_.~")
    base = urllib.parse.urlsplit(S3_ENDPOINT)
    host = base.netloc
    base_path = base.path.rstrip("/")
    canonical_uri = f"{base_path}/{urllib.parse.quote(S3_BUCKET, safe='-_.~')}/{encoded_key}"
    url = urllib.parse.urlunsplit((base.scheme, host, canonical_uri, "", ""))
    body = data if data is not None else b""
    payload_hash = hashlib.sha256(body).hexdigest()
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
    if method == "PUT": headers["content-type"] = content_type
    signed_names = ";".join(sorted(headers))
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in sorted(headers))
    canonical_request = "\n".join([method, canonical_uri, "", canonical_headers, signed_names, payload_hash])
    scope = f"{date}/{S3_REGION}/s3/aws4_request"
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()])
    signature = hmac.new(_sig_key(S3_SECRET, date, S3_REGION), string_to_sign.encode(), hashlib.sha256).hexdigest()
    auth = f"AWS4-HMAC-SHA256 Credential={S3_ACCESS}/{scope}, SignedHeaders={signed_names}, Signature={signature}"
    req_headers = {"Authorization": auth, "X-Amz-Date": amz_date, "X-Amz-Content-Sha256": payload_hash}
    if method == "PUT": req_headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=(body if method == "PUT" else None), headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read(), resp.headers

APP_VERSION = os.environ.get("APP_VERSION", "v1.2.0")
DEPLOY_TIME = datetime.now(TZ)
DEPLOY_TIME_TEXT = DEPLOY_TIME.strftime("%Y 年 %m 月 %d 日 %H:%M（UTC+8）")

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
        c.execute("""CREATE TABLE IF NOT EXISTS attachments(
            id TEXT PRIMARY KEY, task_id TEXT NOT NULL, original_name TEXT NOT NULL, stored_name TEXT NOT NULL,
            mime TEXT DEFAULT 'application/octet-stream', size INTEGER DEFAULT 0, created TEXT DEFAULT '',
            FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE)""")
        cols = {r[1] for r in c.execute("PRAGMA table_info(tasks)")}
        for col, ddl in (("result", "TEXT DEFAULT ''"), ("member_done", "INTEGER DEFAULT 0"), ("member_done_at", "TEXT DEFAULT ''")):
            if col not in cols: c.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")
        acols = {r[1] for r in c.execute("PRAGMA table_info(attachments)")}
        if "storage" not in acols:
            c.execute("ALTER TABLE attachments ADD COLUMN storage TEXT DEFAULT 'local'")
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
    amap = {}
    for a in c.execute("SELECT id,task_id,original_name,mime,size,created FROM attachments ORDER BY created"):
        d = dict(a); d["url"] = "/api/files/" + d["id"]
        amap.setdefault(d.pop("task_id"), []).append(d)
    out = []
    for r in c.execute("SELECT * FROM tasks ORDER BY n"):
        d = dict(r); d["done"] = bool(d["done"]); d["member_done"] = bool(d.get("member_done"))
        for k in ("result", "member_done_at"): d[k] = d.get(k) or ""
        d["attachments"] = amap.get(d["id"], [])
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
        
        if p == "/api/site-info":
            return self._send(200, {
                "version": APP_VERSION,
                "deploy_time": DEPLOY_TIME_TEXT
            })
        
        if p == "/api/auth": return self._send(200 if is_admin(self) else 403, {"admin": is_admin(self)})
        if p == "/api/tasks":
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            since = dict(x.split("=", 1) for x in q.split("&") if "=" in x).get("since")
            with LOCK, conn() as c:
                r = rev(c)
                if since and since.isdigit() and int(since) == r:
                    return self._send(200, {"rev": r, "unchanged": True})
                return self._send(200, {"rev": r, "tasks": rows(c, is_admin(self))})
        m = re.match(r"^/api/files/([\w-]+)$", p)
        if m:
            with LOCK, conn() as c:
                a = c.execute("SELECT * FROM attachments WHERE id=?", (m.group(1),)).fetchone()
            if not a: return self._send(404, {"error": "not found"})
            storage = a["storage"] if "storage" in a.keys() else "local"
            try:
                if storage == "bucket":
                    b, _ = s3_request("GET", "uploads/" + a["stored_name"])
                else:
                    fp = os.path.join(UPLOAD_DIR, a["stored_name"])
                    if not os.path.isfile(fp): return self._send(404, {"error": "file missing"})
                    with open(fp, "rb") as f: b = f.read()
            except Exception as e:
                print("attachment read failed:", repr(e), flush=True)
                return self._send(502, {"error": "file storage unavailable"})
            self.send_response(200)
            self.send_header("Content-Type", a["mime"] or "application/octet-stream")
            safe = re.sub(r'[^A-Za-z0-9._-]', '_', a["original_name"])
            self.send_header("Content-Disposition", 'inline; filename="%s"' % safe)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b); return
        # Serve frontend/static files from the project directory.
        # API routes above keep their existing behavior.
        root = os.path.dirname(os.path.abspath(__file__))
        rel = self.path.split("?", 1)[0]
        if rel in ("", "/"):
            rel = "/index.html"
        rel = os.path.normpath(rel.lstrip("/"))
        target = os.path.abspath(os.path.join(root, rel))
        if target.startswith(root + os.sep) and os.path.isfile(target):
            try:
                with open(target, "rb") as f:
                    b = f.read()
                ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                    ctype += "; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            except OSError:
                pass
        self._send(404, {"error": "not found"})

    def _deny(self):
        if is_admin(self): return False
        self._send(403, {"error": "owner only"}); return True

    def do_POST(self):
        p = self._path()
        m = re.match(r"^/api/tasks/([\w-]+)/attachments$", p)
        if m:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_UPLOAD: return self._send(413, {"error": "file too large (max 50 MB)"})
            name = self.headers.get("X-File-Name", "upload.bin")
            try: name = __import__("urllib.parse", fromlist=["unquote"]).unquote(name)
            except Exception: pass
            name = os.path.basename(name)[:180]
            ext = os.path.splitext(name)[1].lower()
            if ext not in ALLOWED_EXT: return self._send(415, {"error": "file type not allowed"})
            with LOCK, conn() as c:
                if not c.execute("SELECT 1 FROM tasks WHERE id=?", (m.group(1),)).fetchone(): return self._send(404, {"error": "task not found"})
            aid = uuid.uuid4().hex[:16]; stored = aid[:6] + "_" + name
            data = self.rfile.read(n)
            mime = self.headers.get("Content-Type") or mimetypes.guess_type(name)[0] or "application/octet-stream"
            storage = "bucket" if S3_ENABLED else "local"
            try:
                if storage == "bucket":
                    s3_request("PUT", "uploads/" + stored, data, mime)
                else:
                    with open(os.path.join(UPLOAD_DIR, stored), "wb") as f: f.write(data)
            except Exception as e:
                print("attachment upload failed:", repr(e), flush=True)
                return self._send(502, {"error": "upload storage unavailable"})
            with LOCK, conn() as c:
                c.execute("INSERT INTO attachments(id,task_id,original_name,stored_name,mime,size,created,storage) VALUES(?,?,?,?,?,?,?,?)", (aid,m.group(1),name,stored,mime,n,now_s(),storage))
                r=bump(c); return self._send(200,{"rev":r,"tasks":rows(c,is_admin(self))})
        if self._deny(): return
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
        p = self._path()
        fm = re.match(r"^/api/attachments/([\w-]+)$", p)
        if fm:
            with LOCK, conn() as c:
                a=c.execute("SELECT stored_name,storage FROM attachments WHERE id=?",(fm.group(1),)).fetchone()
                if not a: return self._send(404,{"error":"not found"})
                storage = a["storage"] if "storage" in a.keys() else "local"
                try:
                    if storage == "bucket": s3_request("DELETE", "uploads/" + a["stored_name"])
                    else: os.remove(os.path.join(UPLOAD_DIR,a["stored_name"]))
                except FileNotFoundError: pass
                except Exception as e:
                    print("attachment delete failed:", repr(e), flush=True)
                    return self._send(502,{"error":"file storage unavailable"})
                c.execute("DELETE FROM attachments WHERE id=?",(fm.group(1),)); r=bump(c)
                return self._send(200,{"rev":r,"tasks":rows(c,True)})
        m = re.match(r"^/api/tasks/([\w-]+)$", p)
        if not m: return self._send(404, {"error": "not found"})
        with LOCK, conn() as c:
            c.execute("DELETE FROM tasks WHERE id=?", (m.group(1),))
            r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c)})

if __name__ == "__main__":
    init()
    print(f"listening on {PORT}, db={DB}, attachment_storage={'bucket' if S3_ENABLED else 'local'}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
