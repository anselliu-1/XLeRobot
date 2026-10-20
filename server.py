# XLeRobot 分工&時程 共用資料 API（Python 標準函式庫，SQLite）
import json, os, sqlite3, threading, time, uuid, re, mimetypes, urllib.request, urllib.parse, io, zipfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone, timedelta
import hashlib, hmac
import progress, backup, purchase_safety, sys
progress.install(sys.modules[__name__])
purchase_safety.install(sys.modules[__name__])

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

APP_VERSION = os.environ.get("APP_VERSION", "v1.4.0")
DEPLOY_TIME = datetime.now(TZ)
DEPLOY_TIME_TEXT = DEPLOY_TIME.strftime("%Y 年 %m 月 %d 日 %H:%M（UTC+8）")

ADMIN_HASH = os.environ.get("ADMIN_KEY_HASH", "")
def is_admin(h):
    k = h.headers.get("X-Admin-Key", "")
    return bool(ADMIN_HASH and k) and hmac.compare_digest(hashlib.sha256(k.encode()).hexdigest(), ADMIN_HASH)
OWNER_FIELDS = ("done", "done_date")          # 組長複檢：只有管理者可見可改
PUBLIC_FIELDS = ()  # 舊成果改為唯讀
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

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def conn():
    c = sqlite3.connect(DB, timeout=10, factory=ClosingConnection)
    c.row_factory = sqlite3.Row
    return c

def init():
    with LOCK, conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id TEXT PRIMARY KEY, n INTEGER, task TEXT NOT NULL, who TEXT DEFAULT '', due TEXT DEFAULT '',
            done_date TEXT DEFAULT '', pri TEXT DEFAULT '中', note TEXT DEFAULT '', done INTEGER DEFAULT 0, updated REAL)""")
        c.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS task_time_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,actor TEXT,before_time TEXT,after_time TEXT,changed_at TEXT)")
        c.execute("""CREATE TABLE IF NOT EXISTS task_status_audit(
          id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, task_name TEXT NOT NULL,
          before_done INTEGER NOT NULL, after_done INTEGER NOT NULL, actor TEXT NOT NULL,
          changed_at TEXT NOT NULL)""")
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
        c.execute("""CREATE TABLE IF NOT EXISTS purchases(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, spec TEXT DEFAULT '', qty INTEGER DEFAULT 1,
          price REAL DEFAULT 0, status TEXT DEFAULT '待確認', owner TEXT DEFAULT '',
          url TEXT DEFAULT '', note TEXT DEFAULT '', updated TEXT DEFAULT '')""")
        for col, ddl in (("stock", "TEXT DEFAULT '尚未確認'"), ("actual_price", "REAL DEFAULT 0"), ("refund", "TEXT DEFAULT '未開始'")):
            if col not in {r[1] for r in c.execute('PRAGMA table_info(purchases)')}:
                c.execute(f'ALTER TABLE purchases ADD COLUMN {col} {ddl}')
        c.execute("""CREATE TABLE IF NOT EXISTS project_risks(
          id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '',
          solution TEXT DEFAULT '', status TEXT DEFAULT '待評估',
          updated TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1)""")
        if c.execute("SELECT v FROM meta WHERE k='project_risks_seeded'").fetchone() is None:
            initial=[
                ('車體結構與配重','評估降低總高度、上層平台與舵機承載能力。','量測重心、車體穩定性與機構負載。','待評估'),
                ('單臂或雙臂','需明確定義第二隻手臂的用途。','與單臂流程比較，確認雙臂必要性。','待評估'),
                ('視覺辨識與夾取','辨識、座標轉換與夾取的穩定性待驗證。','量測辨識率、定位誤差與夾取成功率。','待驗證'),
                ('展示動線','展示配置圖與操作流程尚待確認。','準備到場校正、分段展示及備援影片。','規劃中'),
                ('雙臂電瓶供電','需比較共用／獨立電瓶、峰值電流、壓降與續航。','量測雙臂同動電流，確認極性、線徑及分路保護。','待評估'),
                ('AGV 停靠與座標校正','停靠偏差會影響手臂夾取。','測試到站誤差、相機與手臂座標轉換及重試流程。','待驗證'),
                ('整合控制與異常處理','底盤、雙臂與相機的完整流程仍待整合。','設計任務狀態、逾時、急停與人工接管。','規劃中')]
            for title,description,solution,status in initial:
                c.execute('INSERT INTO project_risks(id,title,description,solution,status,updated) VALUES(?,?,?,?,?,?)',
                  (uuid.uuid4().hex,title,description,solution,status,datetime.now(timezone.utc).isoformat()))
            c.execute("INSERT INTO meta(k,v) VALUES('project_risks_seeded','1')")
        c.execute("""CREATE TABLE IF NOT EXISTS purchase_receipts(
          id TEXT PRIMARY KEY, purchase_id TEXT NOT NULL, original_name TEXT NOT NULL,
          stored_name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL,
          storage TEXT NOT NULL, created TEXT NOT NULL)""")
        purchase_safety.init(c)
        if c.execute("SELECT v FROM meta WHERE k='purchase_permissions'").fetchone() is None:
            c.execute("INSERT INTO meta(k,v) VALUES('purchase_permissions',?)", (json.dumps({'refund_view':False,'refund_edit':False}),))
        c.execute("""CREATE TABLE IF NOT EXISTS purchase_images(
          id TEXT PRIMARY KEY, purchase_id TEXT NOT NULL, original_name TEXT NOT NULL,
          stored_name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL,
          storage TEXT NOT NULL, created TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS notify_queue(
          id TEXT PRIMARY KEY, event TEXT NOT NULL, subject TEXT NOT NULL,
          detail TEXT NOT NULL, created REAL NOT NULL, sent INTEGER DEFAULT 0,
          error TEXT DEFAULT '')""")
        if c.execute("SELECT v FROM meta WHERE k='notify_config'").fetchone() is None:
            c.execute("INSERT INTO meta(k,v) VALUES('notify_config',?)", (json.dumps({
              'enabled': False, 'mode':'instant', 'events':[
                'task_add','task_done','task_upload','buy_add','buy_status','buy_image']}),))
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

def member_completion_allowed(c):
    r=c.execute("SELECT v FROM meta WHERE k='member_completion_allowed'").fetchone()
    return bool(r and r['v']=='1')

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
        d["report_count"] = c.execute("SELECT COUNT(*) FROM progress_reports WHERE task_id=? AND status!='trash'",(d["id"],)).fetchone()[0]
        latest=c.execute("SELECT created,subject,content FROM progress_reports WHERE task_id=? AND status!='trash' ORDER BY id DESC LIMIT 1",(d["id"],)).fetchone()
        d["latest_report"] = dict(latest) if latest else None
        d["member_completion_allowed"] = member_completion_allowed(c)
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
            if type(v) not in (bool,int) or v not in (0,1):raise ValueError('完成狀態必須為布林值')
            o[k] = 1 if v else 0
        elif k == "due":
            v = str(v or "").strip()[:10]
            o[k] = v if (v == "" or DATE.match(v)) else ""
        elif k in ("done_date", "member_done_at"):
            v = str(v or "").strip().replace("T", " ")[:16]
            o[k] = v if (v == "" or DT.match(v)) else ""
        elif k in ("note", "result"):
            text = str(v or "").strip()
            limit = 10000 if k == "note" else 1000
            if len(text)>limit:raise ValueError("目標最多 10,000 字，請縮短後再儲存" if k == "note" else "歷史成果文字過長")
            o[k] = text
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

NOTIFY_EVENTS = {'task_add','task_edit','task_done','task_reopen','task_result','task_upload','task_delete',
                 'buy_add','buy_edit','buy_status','buy_image','buy_delete','buy_stock','buy_owner','buy_refund',
                 'progress_add','progress_continue','progress_void','progress_file_remove','progress_restore'}
IMAGE_EXT = {'.jpg','.jpeg','.png','.webp'}
IMAGE_MAX = 10 * 1024 * 1024

def notify_config(c):
    row = c.execute("SELECT v FROM meta WHERE k='notify_config'").fetchone()
    try: return json.loads(row[0]) if row else {'enabled':False,'mode':'instant','events':[]}
    except (ValueError, TypeError): return {'enabled':False,'mode':'instant','events':[]}

def notify_fields(data, fields):
    return '\n'.join(label + '：' + str(data.get(key)) for key, label in fields if data.get(key) is not None and str(data.get(key)).strip() != '')

def notify_changes(before, after, fields):
    lines = []
    for key, label in fields:
        old = before[key] if key in before.keys() else None
        new = after.get(key, old)
        if str(old if old is not None else '') != str(new if new is not None else ''):
            lines.append(label + '：' + (str(old) if old is not None and str(old).strip() else '（空白）')[:200] + ' → ' + (str(new) if new is not None and str(new).strip() else '（空白）')[:200])
    return '\n'.join(lines)

PURCHASE_NOTIFY_FIELDS = [('name','品名'),('spec','規格'),('qty','數量'),('price','預估單價'),('actual_price','實際單價'),('status','採購狀態'),('owner','負責人'),('stock','庫存'),('refund','報銷狀態'),('url','購買連結'),('note','備註')]
TASK_NOTIFY_FIELDS = [('task','工作內容'),('who','負責者'),('due','截止日'),('pri','優先級'),('note','備註'),('result','成果'),('member_done_at','回報時間')]

def queue_notify(c, event, subject, detail):
    conf = notify_config(c)
    if conf.get('enabled') and event in conf.get('events', []):
        c.execute('INSERT INTO notify_queue(id,event,subject,detail,created) VALUES(?,?,?,?,?)',
                  (uuid.uuid4().hex, event, subject[:200], detail[:1500], time.time()))


def pending_notifications(c, cfg, now):
    # The persistent queue survives deploys; only currently enabled events are sent.
    enabled=[e for e in cfg.get('events',[]) if e in NOTIFY_EVENTS and not e.startswith('progress_')]
    if not cfg.get('enabled') or not enabled:return []
    wait=600 if cfg.get('mode')=='digest' else 0
    slots=','.join('?' for _ in enabled)
    return [dict(r) for r in c.execute(
        f'SELECT * FROM notify_queue WHERE sent=0 AND created<=? AND event IN ({slots}) ORDER BY created LIMIT 5',
        (now-wait,*enabled))]


def mail_worker():

    while True:
        items=[]
        try:
            webhook = os.environ.get(
                "DISCORD_WEBHOOK_URL", ""
            ).strip()

            with LOCK, conn() as c:
                cfg = notify_config(c)

                if cfg.get("enabled") and webhook:
                    items = pending_notifications(c, cfg, time.time())
                else:
                    items = []

            if items:
                title = (
                    "XLeRobot｜" + items[0]["subject"]
                    if len(items) == 1
                    else f"XLeRobot｜{len(items)} 項網站更新"
                )

                details = "\n\n".join(
                    f"{x['subject']}\n{x['detail']}"
                    for x in items
                )

                message = (
                    title + "\n\n" + details
                )[:1800]

                message += (
                    "\n\n網站：https://" + os.environ.get(
                        "RAILWAY_PUBLIC_DOMAIN",
                        "xlerobot-production.up.railway.app"
                    ).strip().removeprefix("https://").removeprefix("http://").rstrip("/") + "/"
                )

                payload = json.dumps(
                    {"content": message, "allowed_mentions": {"parse": []}},
                    ensure_ascii=False
                ).encode("utf-8")

                request = urllib.request.Request(
                    webhook,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "XLeRobot-Notifier"
                    },
                    method="POST"
                )

                with urllib.request.urlopen(
                    request, timeout=20
                ) as response:
                    if response.status not in (200, 204):
                        raise RuntimeError(
                            "Discord HTTP "
                            + str(response.status)
                        )

                with LOCK, conn() as c:
                    c.executemany(
                        """
                        UPDATE notify_queue
                        SET sent = 1, error = ''
                        WHERE id = ?
                        """,
                        [(x["id"],) for x in items]
                    )
                print('task/purchase notification delivered:',','.join(x['id'] for x in items),flush=True)

        except Exception as exc:
            error='HTTP '+str(exc.code) if isinstance(exc,urllib.error.HTTPError) else type(exc).__name__
            if items:
                with LOCK,conn() as c:
                    c.executemany('UPDATE notify_queue SET error=? WHERE id=? AND sent=0',[(error,x['id']) for x in items])
            print(
                "discord notification failed:",
                error,
                flush=True
            )

        time.sleep(20)


def purchase_permissions(c):
    row=c.execute("SELECT v FROM meta WHERE k='purchase_permissions'").fetchone()
    try: return json.loads(row[0]) if row else {'refund_view':False,'refund_edit':False}
    except (ValueError, TypeError): return {'refund_view':False,'refund_edit':False}

def purchase_rows(c, admin=False):
    result=[dict(r) for r in c.execute('SELECT * FROM purchases ORDER BY updated DESC')]
    if not admin:result=[r for r in result if not r['deleting']]
    images=[dict(r) for r in c.execute("SELECT id,purchase_id,original_name,mime,size FROM purchase_images WHERE NOT EXISTS(SELECT 1 FROM purchase_cleanup q WHERE q.file_table='purchase_images' AND q.file_id=purchase_images.id) ORDER BY created")]
    perms=purchase_permissions(c)
    for r in result:
        if not admin and not perms.get('refund_view'): r.pop('refund',None)
        r['images']=[dict(i, url='/api/purchase-images/'+i['id']) for i in images if i['purchase_id']==r['id']]
    if admin:
        receipts=[dict(x) for x in c.execute("SELECT id,purchase_id,original_name,mime,size FROM purchase_receipts WHERE NOT EXISTS(SELECT 1 FROM purchase_cleanup q WHERE q.file_table='purchase_receipts' AND q.file_id=purchase_receipts.id) ORDER BY created")]
        for r in result:r['receipts']=[dict(x,url='/api/purchase-receipts/'+x['id']) for x in receipts if x['purchase_id']==r['id']]
    return result

def clean_purchase(d):
    if not isinstance(d,dict): raise ValueError('invalid payload')
    name=str(d.get('name','')).strip()[:160]
    if not name: raise ValueError('name required')
    qty=int(d.get('qty',1)); price=float(d.get('price',0))
    if not 1<=qty<=100000 or not 0<=price<=100000000: raise ValueError('invalid amount')
    status=str(d.get('status','待確認'))
    if status not in ('待確認','待評估','待採購','已購買','已到貨','不需採購'): raise ValueError('invalid status')
    url=str(d.get('url','')).strip()[:600]
    if url and not url.startswith(('https://','http://')): raise ValueError('invalid url')
    stock=str(d.get('stock','尚未確認'))
    if stock not in ('尚未確認','有','沒有'): raise ValueError('invalid stock')
    actual=float(d.get('actual_price') or 0)
    if not 0<=actual<=100000000: raise ValueError('invalid actual price')
    for field in ('spec','note'):
        if len(str(d.get(field,'')))>10000:raise ValueError(('規格' if field=='spec' else '備註')+'最多 10,000 字')
    return {'name':name,'spec':str(d.get('spec','')),'qty':qty,'price':price,
            'status':status,'url':url,'note':str(d.get('note','')),
            'stock':stock,'actual_price':actual,'updated':now_s()}

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
        if backup.route(self, 'GET'): return
        if progress.route(self, "GET"): return
        p = self._path()
        if p == "/api/health": return self._send(200, {"ok": True})
        
        if p == "/api/site-info":
            return self._send(200, {
                "version": APP_VERSION,
                "deploy_time": DEPLOY_TIME_TEXT
            })
        
        if p == '/api/purchases/cleanup-status':return purchase_safety.status(self)
        if p == "/api/auth": return self._send(200 if is_admin(self) else 403, {"admin": is_admin(self)})
        if p == '/api/project-risks':
            with LOCK,conn() as c:
                return self._send(200,{'items':[dict(x) for x in c.execute('SELECT * FROM project_risks ORDER BY rowid')]})
        if p == '/api/admin/files':
            if self._deny(): return
            with LOCK, conn() as c:
                result=[]
                for table,kind,parent in [('attachments','task','task_id'),('purchase_images','image','purchase_id'),('purchase_receipts','receipt','purchase_id')]:
                    for row in c.execute('SELECT * FROM '+table).fetchall():
                        d=dict(row)
                        if kind!='task' and purchase_safety.queued(c,table,d['id']):continue
                        if kind=='task':
                            t=c.execute('SELECT task FROM tasks WHERE id=?',(d[parent],)).fetchone()
                            name=t['task'] if t else '(原任務已移除)'
                        else:
                            t=c.execute('SELECT name,deleting FROM purchases WHERE id=?',(d[parent],)).fetchone()
                            name=t['name'] if t else '(原商品已移除)'
                        result.append({'id':d['id'],'kind':kind,'original_name':d['original_name'],
                            'mime':d['mime'],'size':d['size'],'created':d['created'],
                            'parent_id':d[parent],'parent_name':name,
                            'url':('/api/files/' if kind=='task' else '/api/purchase-images/' if kind=='image' else '/api/purchase-receipts/')+d['id']})
                for pf in c.execute("""SELECT pf.id,pf.name,pf.size,pf.report_id,pr.subject,pr.reporter,pr.task_name,pr.created
                    FROM progress_files pf JOIN progress_reports pr ON pr.id=pf.report_id
                    WHERE pf.removed_at='' ORDER BY pr.id DESC"""):
                    d=dict(pf)
                    result.append({'id':d['id'],'kind':'progress','original_name':d['name'],
                        'mime':'application/octet-stream','size':d['size'],'created':d['created'],
                        'parent_id':str(d['report_id']),
                        'parent_name':d['subject']+' · '+d['reporter']+((' · '+d['task_name']) if d['task_name'] else ''),
                        'url':'/api/progress-files/'+d['id']})
                return self._send(200,{'files':result})
        if p == '/api/purchases':
            with LOCK, conn() as c: return self._send(200, {'purchases':purchase_rows(c,is_admin(self)),'permissions':purchase_permissions(c) if is_admin(self) else {'refund_view':purchase_permissions(c)['refund_view'],'refund_edit':purchase_permissions(c)['refund_edit']}})
        if p == '/api/tasks/completion-settings':
            if self._deny():return
            with LOCK,conn() as c:return self._send(200,{'allow_members':member_completion_allowed(c)})
        if p == '/api/purchases/permissions':
            if self._deny(): return
            with LOCK, conn() as c: return self._send(200,purchase_permissions(c))
        if p == '/api/notifications/config':
            if self._deny(): return
            with LOCK, conn() as c: return self._send(200,notify_config(c))
        mreceipt=re.fullmatch(r'/api/purchase-receipts/([a-f0-9]+)',p)
        if mreceipt:
            with LOCK,conn() as c:
                if purchase_safety.queued(c,'purchase_receipts',mreceipt.group(1)):return self._send(404,{'error':'附件正在移除'})
            if self._deny(): return
            with LOCK, conn() as c: a=c.execute('SELECT * FROM purchase_receipts WHERE id=?',(mreceipt.group(1),)).fetchone()
            if not a: return self._send(404,{'error':'not found'})
            try:
                if a['storage']=='bucket': b,_=s3_request('GET','receipts/'+a['stored_name'])
                else:
                    with open(os.path.join(UPLOAD_DIR,a['stored_name']),'rb') as f:b=f.read()
            except Exception:return self._send(502,{'error':'storage unavailable'})
            self.send_response(200); self.send_header('Content-Type',a['mime']);self.send_header('Content-Length',str(len(b)))
            self.send_header('Content-Disposition',"inline; filename*=UTF-8''"+urllib.parse.quote(a['original_name']))
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b);return
        mimg=re.fullmatch(r'/api/purchase-images/([a-f0-9]+)',p)
        if mimg:
            with LOCK,conn() as c:
                if purchase_safety.queued(c,'purchase_images',mimg.group(1)):return self._send(404,{'error':'附件正在移除'})
            with LOCK, conn() as c:
                a=c.execute('SELECT * FROM purchase_images WHERE id=?',(mimg.group(1),)).fetchone()
            if not a: return self._send(404,{'error':'not found'})
            try:
                if a['storage']=='bucket': b,_=s3_request('GET','purchases/'+a['stored_name'])
                else:
                    with open(os.path.join(UPLOAD_DIR,a['stored_name']),'rb') as f: b=f.read()
            except Exception: return self._send(502,{'error':'storage unavailable'})
            self.send_response(200); self.send_header('Content-Type',a['mime']); self.send_header('Content-Length',str(len(b)))
            self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(b); return
        if p == "/api/tasks/options":
            with LOCK, conn() as c:
                return self._send(200, {"items":[{"id":r["id"],"name":r["task"]} for r in c.execute("SELECT id,task FROM tasks ORDER BY n")]})
        if p == "/api/tasks/status-audit":
            if self._deny(): return
            with LOCK, conn() as c:
                return self._send(200,{"items":[dict(r) for r in c.execute("SELECT * FROM task_status_audit ORDER BY id DESC LIMIT 300")]})
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
        if rel in {"index.html", "style.css", "app.js", "data.js", "tasks.js", "purchases.js", "admin-pages.js", "admin-files.js", "nav-scroll.js", "risks-admin.js", "progress.js", "progress.css", "modal.js", "arm-battery-wiring.png", "team-wiring.png", "wiring-1-lipo.png", "wiring-2-shared-u2d2.png", "wiring-3-powerbank-only.png", "README_v1.3.0.md"} and target.startswith(root + os.sep) and os.path.isfile(target):
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
        if backup.route(self): return
        if progress.route(self, "POST"): return
        p = self._path()
        if p == '/api/tasks/completion-settings':
            if self._deny(): return
            try:
                d=self._body()
                if type(d.get('allow_members')) is not bool: raise ValueError()
            except Exception: return self._send(400,{'error':'設定格式錯誤'})
            with LOCK,conn() as c:
                c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('member_completion_allowed',?)",('1' if d['allow_members'] else '0',))
                bump(c)
            return self._send(200,{'allow_members':d['allow_members']})
        if p == '/api/admin/files/zip':
            if self._deny():return
            try:
                ids=self._body().get('ids',[])
                if not isinstance(ids,list) or not ids or len(ids)>50 or any(not re.fullmatch(r'[a-f0-9-]{8,64}',str(x)) for x in ids):
                    return self._send(400,{'error':'請選擇 1–50 個有效檔案'})
                buffer=io.BytesIO()
                with LOCK,conn() as c,zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
                    for n,ident in enumerate(dict.fromkeys(ids)):
                        row=None;prefix=None
                        for table,folder in [('attachments','uploads'),('purchase_images','purchases'),('purchase_receipts','receipts')]:
                            row=c.execute('SELECT * FROM '+table+' WHERE id=?',(ident,)).fetchone()
                            if row:
                                if table!='attachments' and purchase_safety.queued(c,table,row['id']):raise ValueError('附件正在移除')
                                prefix=folder;break
                        if not row:
                            pf=c.execute("SELECT * FROM progress_files WHERE id=? AND removed_at=''",(ident,)).fetchone()
                            if pf:
                                if pf['storage']=='bucket':data,_=s3_request('GET',pf['object_key'])
                                else:
                                    with open(os.path.join(UPLOAD_DIR,pf['object_key']),'rb') as f:data=f.read()
                                name=os.path.basename(pf['name']).replace('\\','_').replace('/','_')
                                z.writestr(str(n+1).zfill(2)+'_progress_'+name,data)
                            continue
                        if row['storage']=='bucket':data,_=s3_request('GET',prefix+'/'+row['stored_name'])
                        else:
                            with open(os.path.join(UPLOAD_DIR,row['stored_name']),'rb') as f:data=f.read()
                        name=os.path.basename(row['original_name']).replace('\\','_').replace('/','_')
                        z.writestr(str(n+1).zfill(2)+'_'+name,data)
                data=buffer.getvalue()
                self.send_response(200)
                self.send_header('Content-Type','application/zip')
                self.send_header('Content-Disposition','attachment; filename="XLeRobot_files.zip"')
                self.send_header('Content-Length',str(len(data)))
                self.send_header('Cache-Control','no-store')
                self.end_headers();self.wfile.write(data);return
            except Exception as e:
                print('zip download failed:',repr(e),flush=True)
                return self._send(502,{'error':'檔案打包失敗，請檢查附件儲存空間'})
        if p == '/api/project-risks':
            if self._deny(): return
            try:
                d=self._body()
                title=str(d.get('title','')).strip()[:160]
                status=str(d.get('status','待評估'))
                if not title or status not in ('待評估','規劃中','進行中','待驗證','已完成','暫緩'):raise ValueError()
                with LOCK,conn() as c:
                    ident=uuid.uuid4().hex
                    c.execute('INSERT INTO project_risks(id,title,description,solution,status,updated) VALUES(?,?,?,?,?,?)',
                      (ident,title,str(d.get('description',''))[:4000],str(d.get('solution',''))[:4000],status,datetime.now(timezone.utc).isoformat()))
                    return self._send(200,{'id':ident})
            except (ValueError,TypeError):return self._send(400,{'error':'invalid risk data'})

        if p == '/api/purchases/permissions':
            if self._deny(): return
            try:
                d=self._body(); cfg={'refund_view':d['refund_view'],'refund_edit':d['refund_edit']}
                if any(type(v) is not bool for v in cfg.values()) or (cfg['refund_edit'] and not cfg['refund_view']):raise ValueError()
            except Exception:return self._send(400,{'error':'invalid permissions'})
            with LOCK, conn() as c:c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('purchase_permissions',?)",(json.dumps(cfg),))
            return self._send(200,cfg)
        if p == '/api/notifications/config':
            if self._deny(): return
            try:
                d=self._body(); cfg={'enabled':d['enabled'], 'mode':d['mode'], 'events':d['events']}
                if type(cfg['enabled']) is not bool: raise ValueError()
                if cfg['mode'] not in ('instant','digest') or not isinstance(cfg['events'],list) or any(x not in NOTIFY_EVENTS for x in cfg['events']): raise ValueError()
            except Exception: return self._send(400,{'error':'invalid settings'})
            with LOCK, conn() as c: c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('notify_config',?)",(json.dumps(cfg),))
            return self._send(200,cfg)
        if p == '/api/purchases':
            try:
                raw=self._body();d=clean_purchase(raw)
                if 'owner' in raw and raw['owner'] and not is_admin(self):return self._send(403,{'error':'owner only'})
                owner=str(raw.get('owner',''))[:100] if is_admin(self) else ''
            except Exception as e: return self._send(400,{'error':str(e)})
            pid=uuid.uuid4().hex[:16]
            with LOCK, conn() as c:
                c.execute('INSERT INTO purchases(id,name,spec,qty,price,status,url,note,stock,actual_price,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(pid,d['name'],d['spec'],d['qty'],d['price'],d['status'],d['url'],d['note'],d['stock'],d['actual_price'],d['updated']))
                if owner:c.execute('UPDATE purchases SET owner=? WHERE id=?',(owner,pid))
                queue_notify(c,'buy_add','新增採購項目',notify_fields(dict(d,owner=owner),PURCHASE_NOTIFY_FIELDS))
                return self._send(200,{'purchases':purchase_rows(c,is_admin(self))})
        receipt=re.fullmatch(r'/api/purchases/([a-f0-9]+)/receipts',p)
        if receipt:
            if self._deny():return
            n=int(self.headers.get('Content-Length') or 0)
            if not 0<n<=20*1024*1024:return self._send(413,{'error':'單檔上限 20 MB'})
            name=os.path.basename(urllib.parse.unquote(self.headers.get('X-File-Name','receipt.pdf')).replace('\\','/'))[:160]
            ext=os.path.splitext(name)[1].lower()
            if ext not in IMAGE_EXT|{'.pdf'}:return self._send(415,{'error':'只接受圖片或 PDF'})
            with LOCK, conn() as c:
                item=c.execute('SELECT name,deleting FROM purchases WHERE id=?',(receipt.group(1),)).fetchone()
                if not item:return self._send(404,{'error':'item not found'})
                if item['deleting']:return self._send(409,{'error':'此項目正在刪除'})
            b=self.rfile.read(n)
            signatures={'.jpg':b.startswith(b'\xff\xd8\xff'),'.jpeg':b.startswith(b'\xff\xd8\xff'),'.png':b.startswith(b'\x89PNG\r\n\x1a\n'),'.webp':b.startswith(b'RIFF') and b[8:12]==b'WEBP','.pdf':b.startswith(b'%PDF-')}
            if not signatures[ext]:return self._send(415,{'error':'檔案格式不符'})
            aid=uuid.uuid4().hex;stored=aid[:10]+'_'+name;mime=mimetypes.guess_type(name)[0] or 'application/octet-stream'
            storage='bucket' if S3_ENABLED else 'local'
            try:
                if storage=='bucket':s3_request('PUT','receipts/'+stored,b,mime)
                else:
                    with open(os.path.join(UPLOAD_DIR,stored),'wb') as f:f.write(b)
            except Exception as e:
                print('receipt upload failed:',repr(e),flush=True)
                return self._send(502,{'error':'storage unavailable'})
            with LOCK, conn() as c:
                parent=c.execute('SELECT deleting FROM purchases WHERE id=?',(receipt.group(1),)).fetchone()
                if not parent or parent['deleting']:
                    purchase_safety.queue_file(c,'purchase_receipts',dict(id=aid,purchase_id=receipt.group(1),original_name=name,stored_name=stored,storage=storage))
                    return self._send(409,{'error':'此項目已刪除或正在刪除，上傳檔案將自動清理'})
                c.execute('INSERT INTO purchase_receipts VALUES(?,?,?,?,?,?,?,?)',(aid,receipt.group(1),name,stored,mime,n,storage,now_s()))
                c.execute('UPDATE purchases SET revision=revision+1 WHERE id=?',(receipt.group(1),))
                return self._send(200,{'purchases':purchase_rows(c,True)})
        im=re.fullmatch(r'/api/purchases/([a-f0-9]+)/images',p)
        if im:
            n=int(self.headers.get('Content-Length') or 0)
            if not 0<n<=IMAGE_MAX: return self._send(413,{'error':'圖片不得超過 10 MB'})
            name=urllib.parse.unquote(self.headers.get('X-File-Name','image.jpg'))
            name=os.path.basename(name.replace('\\','/'))[:160]
            ext=os.path.splitext(name)[1].lower()
            if ext not in IMAGE_EXT: return self._send(415,{'error':'僅支援 JPG、PNG、WebP'})
            with LOCK, conn() as c:
                item=c.execute('SELECT name,deleting FROM purchases WHERE id=?',(im.group(1),)).fetchone()
                if not item: return self._send(404,{'error':'item not found'})
                if item['deleting']:return self._send(409,{'error':'此項目正在刪除'})
            b=self.rfile.read(n)
            signatures={'.jpg':b.startswith(b'\xff\xd8\xff'),'.jpeg':b.startswith(b'\xff\xd8\xff'),'.png':b.startswith(b'\x89PNG\r\n\x1a\n'),'.webp':b.startswith(b'RIFF') and b[8:12]==b'WEBP'}
            if not signatures[ext]: return self._send(415,{'error':'圖片格式不符'})
            aid=uuid.uuid4().hex; stored=aid[:10]+'_'+name; mime=mimetypes.guess_type(name)[0] or 'image/jpeg'
            storage='bucket' if S3_ENABLED else 'local'
            try:
                if storage=='bucket': s3_request('PUT','purchases/'+stored,b,mime)
                else:
                    with open(os.path.join(UPLOAD_DIR,stored),'wb') as f:f.write(b)
            except Exception as e:
                print('purchase image upload failed:',repr(e),flush=True)
                return self._send(502,{'error':'storage unavailable'})
            with LOCK, conn() as c:
                parent=c.execute('SELECT deleting FROM purchases WHERE id=?',(im.group(1),)).fetchone()
                if not parent or parent['deleting']:
                    purchase_safety.queue_file(c,'purchase_images',dict(id=aid,purchase_id=im.group(1),original_name=name,stored_name=stored,storage=storage))
                    return self._send(409,{'error':'此項目已刪除或正在刪除，上傳檔案將自動清理'})
                c.execute('INSERT INTO purchase_images VALUES(?,?,?,?,?,?,?,?)',(aid,im.group(1),name,stored,mime,n,storage,now_s()))
                c.execute('UPDATE purchases SET revision=revision+1 WHERE id=?',(im.group(1),))
                queue_notify(c,'buy_image','新增採購圖片','商品：'+item['name']+'\n檔案：'+name)
                return self._send(200,{'purchases':purchase_rows(c,is_admin(self))})
        m = re.match(r"^/api/tasks/([\w-]+)/attachments$", p)
        if m:
            return self._send(403, {"error":"請改至進度回報上傳新成果附件"})
        if False:
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
                queue_notify(c,"task_upload","新增成果附件","工作內容："+c.execute("SELECT task FROM tasks WHERE id=?",(m.group(1),)).fetchone()["task"]+"\n檔案："+name); r=bump(c); return self._send(200,{"rev":r,"tasks":rows(c,is_admin(self))})
        if self._deny(): return
        try: d = self._body()
        except Exception: return self._send(400, {"error": "bad json"})
        admin = is_admin(self)
        if p in ("/api/import", "/api/reset") and not admin:
            return self._send(403, {"error": "owner only"})
        with LOCK, conn() as c:
            if p == "/api/tasks":
                try:o = clean(d)
                except ValueError as exc:return self._send(400,{"error":str(exc)})
                if not admin: o.pop("done", None); o.pop("done_date", None)
                if o.get("done") and not o.get("done_date"): o["done_date"] = now_s()
                n = (c.execute("SELECT COALESCE(MAX(n),0) FROM tasks").fetchone()[0] or 0) + 1
                tid = uuid.uuid4().hex[:10]
                c.execute("INSERT INTO tasks(id,n,task,who,due,done_date,pri,note,done,result,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          (tid, n, o["task"], o.get("who", ""), o.get("due", ""), o.get("done_date", ""), o.get("pri", "中"), o.get("note", ""), o.get("done", 0), o.get("result", ""), time.time()))
                queue_notify(c,"task_add","新增分工任務",notify_fields(o,TASK_NOTIFY_FIELDS)); r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c), "id": tid})
            if p == "/api/import":
                arr = d.get("tasks") if isinstance(d, dict) else None
                if not isinstance(arr, list): return self._send(400, {"error": "no tasks"})
                try:
                    prepared=[]
                    for item in arr[:1000]:
                        if not isinstance(item,dict) or not item.get('task'):continue
                        t=dict(item)
                        if 'done_date' not in t and 'doneDate' in t:t['done_date']=t['doneDate']
                        prepared.append((t,clean(t)))
                except (ValueError,TypeError) as exc:return self._send(400,{"error":str(exc)})
                if d.get("mode") == "replace": c.execute("DELETE FROM tasks")
                n = (c.execute("SELECT COALESCE(MAX(n),0) FROM tasks").fetchone()[0] or 0)
                for t,o in prepared:
                    n += 1
                    tid = str(t.get("id") or uuid.uuid4().hex[:10])[:40]
                    c.execute("INSERT OR REPLACE INTO tasks(id,n,task,who,due,done_date,pri,note,done,result,member_done,member_done_at,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (tid, n, o["task"], o.get("who", ""), o.get("due", ""), o.get("done_date", ""), o.get("pri", "中"), o.get("note", ""), o.get("done", 0), o.get("result", ""), o.get("member_done", 0), o.get("member_done_at", ""), time.time()))
                r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c)})
            if p == "/api/reset":
                seed(c); r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c)})
        self._send(404, {"error": "not found"})

    def _purchase_extra(self,d,old,admin,perms):
        try: raw=self._purchase_raw
        except AttributeError:return {'owner':old['owner'],'refund':old['refund']}
        owner=str(raw.get('owner',old['owner']))[:100]
        refund=str(raw.get('refund',old['refund']))
        if refund not in ('未開始','待送件','審核中','已完成','不需報銷'):return None
        if not admin and ('owner' in raw and owner!=old['owner']):return None
        if not admin and ('refund' in raw and refund!=old['refund']) and not perms.get('refund_edit'):return None
        return {'owner':owner if admin else old['owner'],'refund':refund if (admin or perms.get('refund_edit')) else old['refund']}

    def do_PATCH(self):
        if progress.route(self, "PATCH"): return
        p = self._path()
        rm=re.fullmatch(r'/api/project-risks/([a-f0-9]+)',p)
        if rm:
            if self._deny():return
            try:
                d=self._body()
                title=str(d.get('title','')).strip()[:160]
                status=str(d.get('status','待評估'))
                revision=int(d.get('revision',0))
                if not title or status not in ('待評估','規劃中','進行中','待驗證','已完成','暫緩'):raise ValueError()
                with LOCK,conn() as c:
                    result=c.execute('UPDATE project_risks SET title=?,description=?,solution=?,status=?,updated=?,revision=revision+1 WHERE id=? AND revision=?',
                      (title,str(d.get('description',''))[:4000],str(d.get('solution',''))[:4000],status,datetime.now(timezone.utc).isoformat(),rm.group(1),revision))
                    if result.rowcount==0:return self._send(409,{'error':'資料已被其他管理員修改，請重新整理'})
                    return self._send(200,{'ok':True})
            except (ValueError,TypeError):return self._send(400,{'error':'invalid risk data'})

        pm=re.fullmatch(r'/api/purchases/([a-f0-9]+)',p)
        if pm:return purchase_safety.patch(self,pm.group(1))
        m = re.match(r"^/api/tasks/([\w-]+)$", p)
        if not m: return self._send(404, {"error": "not found"})
        try: d = self._body()
        except Exception: return self._send(400, {"error": "bad json"})
        admin = is_admin(self)
        try:o = clean(d, partial=True)
        except ValueError as exc:return self._send(400,{"error":str(exc)})
        if d.get('done_date') and not o.get('done_date'):return self._send(400,{'error':'完成時間格式不正確'})
        if not admin:
            if any(k != "done" for k in o):
                return self._send(403, {"error": "一般組員僅可依管理員設定操作完成狀態"})
        if not o: return self._send(400, {"error": "no fields"})
        with LOCK, conn() as c:
            cur = c.execute("SELECT * FROM tasks WHERE id=?", (m.group(1),)).fetchone()
            if not cur: return self._send(404, {"error": "gone"})
            if not admin and not member_completion_allowed(c):
                return self._send(403,{"error":"目前僅管理員可以勾選完成"})
            if "result" in o or "member_done" in o or "member_done_at" in o:
                return self._send(403,{"error":"舊成果及回報完成欄位已停止編輯"})
            if 'done_date' in o and o['done_date']:
                try:datetime.strptime(o['done_date'],'%Y-%m-%d %H:%M')
                except ValueError:return self._send(400,{'error':'完成時間格式不正確'})
            if 'done' in o:
                o['done_date']=(o.get('done_date') or cur['done_date'] or now_s()) if o['done'] else ''
            elif 'done_date' in o:
                o['done']=1 if o['done_date'] else 0
            sets = ",".join(f"{k}=?" for k in o) + ",updated=?"
            c.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*o.values(), time.time(), m.group(1)))
            if "done" in o and bool(o["done"]) != bool(cur["done"]):
                c.execute("INSERT INTO task_status_audit(task_id,task_name,before_done,after_done,actor,changed_at) VALUES(?,?,?,?,?,?)",
                          (m.group(1),cur["task"],int(bool(cur["done"])),int(bool(o["done"])),"管理員" if admin else "一般組員（未驗證身分）",now_s()))
            if 'done_date' in o and o['done_date']!=(cur['done_date'] or ''):
                c.execute('INSERT INTO task_time_audit(task_id,actor,before_time,after_time,changed_at) VALUES(?,?,?,?,?)',
                          (m.group(1),'管理員' if admin else '一般組員（未驗證身分）',cur['done_date'] or '',o['done_date'],now_s()))
            current = dict(cur)
            current.update(o)
            summary = notify_fields(current, TASK_NOTIFY_FIELDS)
            changes = notify_changes(cur, current, TASK_NOTIFY_FIELDS)
            if 'done' in o and bool(o['done']) != bool(cur['done']):
                queue_notify(c,'task_done' if o['done'] else 'task_reopen',
                             '分工確認完成' if o['done'] else '分工取消完成',summary)
            elif o.get('member_done') == 1 and not cur['member_done']:
                queue_notify(c,'task_done','組員回報完成',summary)
            elif o.get('member_done') == 0 and cur['member_done']:
                queue_notify(c,'task_reopen','取消完成回報',summary)
            elif 'result' in o and o['result']!=cur['result']:
                queue_notify(c,'task_result','成果內容更新',summary + ('\n變更：\n'+changes if changes else ''))
            elif changes:
                queue_notify(c,'task_edit','分工內容更新',summary + '\n變更：\n'+changes)
            r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c, admin)})

    def do_DELETE(self):
        if progress.route(self, "DELETE"): return
        if self._deny(): return
        p = self._path()
        rm=re.fullmatch(r'/api/project-risks/([a-f0-9]+)',p)
        if rm:
            with LOCK,conn() as c:
                c.execute('DELETE FROM project_risks WHERE id=?',(rm.group(1),))
                return self._send(200,{'ok':True})

        for pattern,table in [(r'/api/purchase-receipts/([a-f0-9]+)','purchase_receipts'),(r'/api/purchase-images/([a-f0-9]+)','purchase_images'),(r'/api/purchases/([a-f0-9]+)',None)]:
            match=re.fullmatch(pattern,p)
            if match:return purchase_safety.request_delete(self,match.group(1),table)
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
                c.execute("DELETE FROM attachments WHERE id=?",(fm.group(1),)); queue_notify(c,"task_delete","刪除成果附件",a["stored_name"]); r=bump(c)
                return self._send(200,{"rev":r,"tasks":rows(c,True)})
        m = re.match(r"^/api/tasks/([\w-]+)$", p)
        if not m: return self._send(404, {"error": "not found"})
        with LOCK, conn() as c:
            old=c.execute("SELECT task FROM tasks WHERE id=?",(m.group(1),)).fetchone()
            c.execute("DELETE FROM tasks WHERE id=?", (m.group(1),))
            if old: queue_notify(c,'task_delete','刪除分工任務',old['task'])
            r = bump(c); return self._send(200, {"rev": r, "tasks": rows(c)})

if __name__ == "__main__":
    init()
    progress.init()
    backup.init(sys.modules[__name__])
    threading.Thread(target=progress.worker, daemon=True).start()
    threading.Thread(target=purchase_safety.worker, daemon=True).start()
    print(f"listening on {PORT}, db={DB}, attachment_storage={'bucket' if S3_ENABLED else 'local'}", flush=True)
    threading.Thread(target=mail_worker, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()




