"""Immutable progress reports; isolated tables, object prefix and durable outbox."""
import json, os, re, uuid, time, threading, urllib.request, urllib.parse
from email.parser import BytesParser
from email.policy import default
from datetime import datetime

MAX = 50 * 1024 * 1024
EXT = set(('.py .js .ts .tsx .jsx .c .cpp .h .hpp .ino .java .rs .go .sh .ps1 .yaml .yml .json .xml .html .css .md .txt .csv .log .toml .ipynb .zip .7z .rar .tar .gz .jpg .jpeg .png .gif .webp .mp4 .mov .webm .avi .pdf .doc .docx .xls .xlsx .ppt .pptx').split())
UPLOADS = threading.BoundedSemaphore(2)
EVENTS = {'新增回報':'progress_add','接續回報':'progress_continue',
          '作廢回報':'progress_void','附件移除':'progress_file_remove','恢復有效':'progress_restore'}

def install(app):
    global A
    A = app

def stamp():
    return datetime.now(A.TZ).isoformat(timespec='microseconds')

def init():
    with A.LOCK, A.conn() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS progress_reports(
          id INTEGER PRIMARY KEY AUTOINCREMENT, reporter TEXT NOT NULL,
          subject TEXT NOT NULL, content TEXT NOT NULL, created TEXT NOT NULL,
          parent_id INTEGER REFERENCES progress_reports(id), root_id INTEGER,
          version INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'valid',
          void_reason TEXT NOT NULL DEFAULT '', void_at TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS progress_root ON progress_reports(root_id,version);
        CREATE TABLE IF NOT EXISTS progress_files(
          id TEXT PRIMARY KEY, report_id INTEGER NOT NULL REFERENCES progress_reports(id),
          name TEXT NOT NULL, size INTEGER NOT NULL, object_key TEXT NOT NULL,
          storage TEXT NOT NULL, removed_at TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
          cleared_at TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS progress_audit(
          id INTEGER PRIMARY KEY AUTOINCREMENT, report_id INTEGER NOT NULL,
          action TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
          file_id TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS progress_deleted_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,report_id INTEGER NOT NULL,subject TEXT NOT NULL,reporter TEXT NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS progress_cleanup(
          id TEXT PRIMARY KEY, object_key TEXT NOT NULL, storage TEXT NOT NULL,
          created TEXT NOT NULL, completed TEXT NOT NULL DEFAULT '',
          attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
          error TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS progress_outbox(
          id TEXT PRIMARY KEY, detail TEXT NOT NULL, created TEXT NOT NULL,
          sent_at TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
          next_try REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '');
        ''')
        cols={r[1] for r in c.execute("PRAGMA table_info(progress_reports)")}
        for col,ddl in [('trash_at',"TEXT NOT NULL DEFAULT ''"),('trash_reason',"TEXT NOT NULL DEFAULT ''"),('trash_previous_status',"TEXT NOT NULL DEFAULT ''")]:
            if col not in cols:c.execute('ALTER TABLE progress_reports ADD COLUMN '+col+' '+ddl)
        if 'task_id' not in cols: c.execute("ALTER TABLE progress_reports ADD COLUMN task_id TEXT NOT NULL DEFAULT ''")
        if 'task_name' not in cols: c.execute("ALTER TABLE progress_reports ADD COLUMN task_name TEXT NOT NULL DEFAULT ''")
        if 'event' not in {r[1] for r in c.execute('PRAGMA table_info(progress_outbox)')}:
            c.execute("ALTER TABLE progress_outbox ADD COLUMN event TEXT NOT NULL DEFAULT ''")
        for label,code in EVENTS.items():
            c.execute("UPDATE progress_outbox SET event=? WHERE event='' AND detail LIKE ?",(code,label+'｜%'))
        if not c.execute("SELECT 1 FROM meta WHERE k='progress_notify_controls_v1'").fetchone():
            cfg=A.notify_config(c)
            cfg['events']=list(dict.fromkeys(cfg.get('events',[])+list(EVENTS.values())))
            c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('notify_config',?)",(json.dumps(cfg),))
            c.execute("INSERT INTO meta(k,v) VALUES('progress_notify_controls_v1','1')")
        if not c.execute("SELECT 1 FROM meta WHERE k='progress_restore_notify_v1'").fetchone():
            cfg=A.notify_config(c)
            cfg['events']=list(dict.fromkeys(cfg.get('events',[])+['progress_restore']))
            c.execute("UPDATE meta SET v=? WHERE k='notify_config'",(json.dumps(cfg),))
            c.execute("INSERT INTO meta(k,v) VALUES('progress_restore_notify_v1','1')")

def event(c, rid, action, actor, reason='', fid=''):
    now = stamp()
    c.execute('INSERT INTO progress_audit(report_id,action,actor,reason,file_id,created) VALUES(?,?,?,?,?,?)',
              (rid, action, actor, reason, fid, now))
    code=EVENTS[action]
    cfg=A.notify_config(c)
    if not cfg.get('enabled') or code not in cfg.get('events',[]): return
    r = c.execute('SELECT * FROM progress_reports WHERE id=?',(rid,)).fetchone()
    detail = f'{action}｜回報 #{rid}・v{r["version"]}\n{r["subject"]}\n回報人：{r["reporter"]}\n時間：{now}\n'
    detail += ('原因：'+reason if reason else r['content'][:900])
    c.execute('INSERT INTO progress_outbox(id,detail,created,event) VALUES(?,?,?,?)', (uuid.uuid4().hex, detail[:1500], now, code))

def worker():
    while True:
        try:
            retry_cleanup()
            with A.LOCK, A.conn() as c:
                removals=[dict(r) for r in c.execute("SELECT * FROM progress_files WHERE removed_at<>'' AND cleared_at='' LIMIT 5")]
            for f in removals:
                try:
                    clear_file(f)
                except Exception as exc:
                    print('progress removal retry:',type(exc).__name__,flush=True)
            webhook = os.environ.get('DISCORD_WEBHOOK_URL','').strip()
            if webhook:
                with A.LOCK, A.conn() as c:
                    cfg=A.notify_config(c)
                    enabled=[code for code in EVENTS.values() if cfg.get('enabled') and code in cfg.get('events',[])]
                    slots=','.join('?' for _ in enabled)
                    items = [dict(r) for r in c.execute(f"SELECT * FROM progress_outbox WHERE sent_at='' AND next_try<=? AND event IN ({slots}) ORDER BY created LIMIT 5",(time.time(),*enabled))] if enabled else []
                for item in items:
                    try:
                        with A.LOCK,A.conn() as c:
                            cfg=A.notify_config(c)
                        if not cfg.get('enabled') or item['event'] not in cfg.get('events',[]): continue
                        domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN','').strip()
                        link = '\nhttps://'+domain+'/#progress' if domain else ''
                        body = json.dumps({'content': ('XLeRobot｜'+item['detail']+link)[:1900], 'allowed_mentions':{'parse':[]}},ensure_ascii=False).encode()
                        req = urllib.request.Request(webhook, data=body, headers={'Content-Type':'application/json','User-Agent':'XLeRobot-Progress'}, method='POST')
                        with urllib.request.urlopen(req,timeout=15) as response:
                            if response.status not in (200,204): raise RuntimeError('Discord rejected')
                        with A.LOCK, A.conn() as c:
                            c.execute('UPDATE progress_outbox SET sent_at=?,error=\'\' WHERE id=?',(stamp(),item['id']))
                        print('progress notification delivered:',item['id'],flush=True)
                    except Exception as exc:
                        with A.LOCK, A.conn() as c:
                            c.execute('UPDATE progress_outbox SET attempts=attempts+1,next_try=?,error=? WHERE id=?',
                                      (time.time()+min(300,5*2**min(item['attempts'],6)),type(exc).__name__,item['id']))
        except Exception as exc:
            print('progress notifier:',type(exc).__name__,flush=True)
        time.sleep(5)

def text_field(value, limit, label, required=False):
    if not isinstance(value,str) or len(value)>limit: raise ValueError(label+'格式或長度不正確')
    value=value.strip()
    if required and not value: raise ValueError('請填寫'+label)
    if '\x00' in value: raise ValueError('無效文字')
    return value

def read_form(h):
    try: n=int(h.headers.get('Content-Length','0'))
    except ValueError: raise ValueError('無效檔案長度')
    if h.headers.get('Transfer-Encoding') or n<=0 or n>MAX+512*1024:
        raise ValueError('每筆附件合計上限 50MB')
    typ=h.headers.get('Content-Type','')
    if not typ.startswith('multipart/form-data;') or len(typ)>300: raise ValueError('請使用表單上傳')
    h.connection.settimeout(30)
    raw=h.rfile.read(n)
    if len(raw)!=n: raise ValueError('上傳未完成')
    # Bound MIME part count before constructing the MIME tree.
    boundary=re.search(r'boundary=(?:"([^"]+)"|([^;\s]+))',typ)
    if not boundary: raise ValueError('無效表單邊界')
    delimiter=(boundary.group(1) or boundary.group(2)).encode('ascii')
    if not 1<=len(delimiter)<=70 or raw.count(b'\r\n--'+delimiter)>25: raise ValueError('表單欄位或附件過多')
    msg=BytesParser(policy=default).parsebytes(('Content-Type: '+typ+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
    if not msg.is_multipart() or msg.defects: raise ValueError('無效上傳表單')
    fields={}; files=[]; total=0
    for part in msg.iter_parts():
        if part.is_multipart() or part.defects: raise ValueError('無效附件')
        key=part.get_param('name',header='content-disposition')
        data=part.get_payload(decode=True) or b''
        name=part.get_filename()
        if name is not None:
            if not name and not data: continue
            if key!='files' or len(files)>=20: raise ValueError('最多 20 個附件')
            name=name.replace('\\','/').split('/')[-1]
            if not name or len(name)>180 or any(ord(ch)<32 or ord(ch)==127 for ch in name): raise ValueError('無效檔名')
            if os.path.splitext(name)[1].lower() not in EXT: raise ValueError('不支援的附件類型：'+name)
            total+=len(data)
            if total>MAX: raise ValueError('每筆附件合計上限 50MB')
            files.append((name,data))
        else:
            if key not in ('reporter','subject','content','parent_id','task_id') or key in fields or len(data)>45000: raise ValueError('無效表單欄位')
            fields[key]=data.decode('utf-8',errors='strict')
    return fields,files

def list_reports(h):
    query=urllib.parse.parse_qs(urllib.parse.urlsplit(h.path).query)
    q=query.get('q',[''])[0].strip().casefold()[:200]
    who=query.get('reporter',[''])[0]; status=query.get('status',['all'])[0]
    with A.LOCK, A.conn() as c:
        is_admin=A.is_admin(h)
        reports=[dict(r) for r in c.execute("SELECT * FROM progress_reports WHERE status!='trash' ORDER BY id")]
        versions={r['id']:r['version'] for r in c.execute('SELECT id,version FROM progress_reports')}
        trash_count=c.execute("SELECT COUNT(*) FROM progress_reports WHERE status='trash'").fetchone()[0] if is_admin else 0
        for r in reports:
            r['parent_version']=versions.get(r['parent_id'])
            if r['task_id']:
                current=c.execute('SELECT task FROM tasks WHERE id=?',(r['task_id'],)).fetchone()
                r['task_display']=current['task'] if current else r['task_name']+'（原工作已移除）'
            else: r['task_display']=''
            r['files']=[{**dict(f),'url':'/api/progress-files/'+f['id'] if not f['removed_at'] else None} for f in c.execute('SELECT id,name,size,removed_at,reason FROM progress_files WHERE report_id=?',(r['id'],))]
        people=sorted({r['reporter'] for r in reports})
        matched=[r['id'] for r in reports if (not who or r['reporter']==who) and (status=='all' or r['status']==status) and (not q or q in '\n'.join([r['reporter'],r['subject'],r['content']]+[f['name'] for f in r['files']]).casefold())]
        # Include full histories for matching topics, even if earlier versions do not match.
        roots={r['root_id'] for r in reports if r['id'] in matched}
        items=[r for r in reports if r['root_id'] in roots]
        return h._send(200,{'items':items,'matched_ids':matched,'reporters':people,'admin':A.is_admin(h),'show_report_ids':(c.execute("SELECT v FROM meta WHERE k='progress_show_ids'").fetchone() or {'v':'0'})['v']=='1','export_all':(c.execute("SELECT v FROM meta WHERE k='progress_export_all'").fetchone() or {'v':'0'})['v']=='1','audit_all':(c.execute("SELECT v FROM meta WHERE k='progress_audit_all'").fetchone() or {'v':'0'})['v']=='1','trash_count':trash_count})

def download(h,fid):
    with A.LOCK, A.conn() as c:
        f=c.execute('SELECT * FROM progress_files WHERE id=?',(fid,)).fetchone()
    if not f or f['removed_at']: return h._send(404,{'error':'附件不存在或已移除'})
    with A.LOCK,A.conn() as c:
        report=c.execute('SELECT status FROM progress_reports WHERE id=?',(f['report_id'],)).fetchone()
    if not report or report['status']=='trash':return h._send(404,{'error':'附件已移至垃圾桶'})
    if f['storage']=='bucket': data,_=A.s3_request('GET',f['object_key'])
    else:
        with open(os.path.join(A.UPLOAD_DIR, f['object_key']), 'rb') as stream: data=stream.read()
    h.send_response(200)
    h.send_header('Content-Type','application/octet-stream')
    h.send_header('X-Content-Type-Options','nosniff')
    h.send_header('Content-Security-Policy',"sandbox; default-src 'none'")
    h.send_header('Content-Disposition',"attachment; filename=download; filename*=UTF-8''"+urllib.parse.quote(f['name'],safe=''))
    h.send_header('Cache-Control','no-store')
    h.send_header('Content-Length',str(len(data))); h.end_headers(); h.wfile.write(data)

def create(h):
    if not UPLOADS.acquire(blocking=False): return h._send(429,{'error':'目前上傳忙碌，請稍後再試'})
    stored=[]
    try:
        fields,files=read_form(h)
        reporter=text_field(fields.get('reporter',''),80,'回報人',True)
        subject=text_field(fields.get('subject',''),200,'主題',True)
        content=text_field(fields.get('content',''),10000,'內容',True)
        parent=fields.get('parent_id','').strip()
        task_id=fields.get('task_id','').strip()
        if task_id and not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',task_id): raise ValueError('無效工作關聯')
        if parent and not re.fullmatch(r'[1-9][0-9]{0,9}',parent): raise ValueError('無效接續回報')
        with A.LOCK, A.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM progress_reports WHERE id=?',(parent,)).fetchone() if parent else None
            if parent and (not old or old['status']!='valid'): raise ValueError('只能接續有效回報')
            root=old['root_id'] if old else None
            version=c.execute('SELECT COALESCE(MAX(version),0)+1 FROM progress_reports WHERE root_id=?',(root,)).fetchone()[0] if old else 1
            if old:
                subject=old['subject']
                task_id=old['task_id']
                task_name=old['task_name']
            else:
                t=c.execute('SELECT task FROM tasks WHERE id=?',(task_id,)).fetchone() if task_id else None
                if task_id and not t: raise ValueError('找不到關聯工作，請重新選擇')
                task_name=t['task'] if t else ''
            rid=c.execute('INSERT INTO progress_reports(reporter,subject,content,created,parent_id,root_id,version,task_id,task_name) VALUES(?,?,?,?,?,?,?,?,?)',
                          (reporter,subject,content,stamp(),int(parent) if parent else None,root,version,task_id,task_name)).lastrowid
            if not old: c.execute('UPDATE progress_reports SET root_id=? WHERE id=?',(rid,rid))
            for name,data in files:
                fid=uuid.uuid4().hex
                key='progress/staging/'+fid
                storage='bucket' if A.S3_ENABLED else 'local'
                # Track before PUT so ambiguous network failures are also cleaned up.
                stored.append((storage,key))
                if storage=='bucket': A.s3_request('PUT',key,data,'application/octet-stream')
                else:
                    path=os.path.join(A.UPLOAD_DIR,key); os.makedirs(os.path.dirname(path),exist_ok=True)
                    with open(path,'xb') as stream: stream.write(data)
                c.execute('INSERT INTO progress_files(id,report_id,name,size,object_key,storage) VALUES(?,?,?,?,?,?)',(fid,rid,name,len(data),key,storage))
            event(c,rid,'接續回報' if old else '新增回報','回報人（自行填寫）：'+reporter)
            A.bump(c)
        stored=[]
        return h._send(201,{'id':rid,'version':version})
    finally:
        for storage,key in stored:
            try:
                if storage=='bucket': A.s3_request('DELETE',key)
                else: os.remove(os.path.join(A.UPLOAD_DIR,key))
            except Exception: print('progress orphan cleanup required:',key,flush=True)
        UPLOADS.release()

def clear_file(f):
    try:
        if f['storage']=='bucket': A.s3_request('DELETE',f['object_key'])
        else: os.remove(os.path.join(A.UPLOAD_DIR,f['object_key']))
    except FileNotFoundError: pass
    with A.LOCK,A.conn() as c:
        c.execute('UPDATE progress_files SET cleared_at=? WHERE id=?',(stamp(),f['id']))


def retry_cleanup(ids=None):
    # Store object identities before deleting report metadata, so a crash or S3
    # outage never loses the durable deletion intention. DELETE is idempotent.
    with A.LOCK,A.conn() as c:
        if ids is None:
            jobs=[dict(r) for r in c.execute("SELECT * FROM progress_cleanup WHERE completed='' AND next_try<=? ORDER BY created LIMIT 5",(time.time(),))]
        else:
            jobs=[]
            for fid in ids:
                row=c.execute("SELECT * FROM progress_cleanup WHERE id=? AND completed=''",(fid,)).fetchone()
                if row:jobs.append(dict(row))
    for job in jobs:
        try:
            try:
                if job['storage']=='bucket':A.s3_request('DELETE',job['object_key'])
                else:os.remove(os.path.join(A.UPLOAD_DIR,job['object_key']))
            except FileNotFoundError:pass
            with A.LOCK,A.conn() as c:
                c.execute("UPDATE progress_cleanup SET completed=?,error='' WHERE id=?",(stamp(),job['id']))
        except Exception as exc:
            with A.LOCK,A.conn() as c:
                c.execute('UPDATE progress_cleanup SET attempts=attempts+1,next_try=?,error=? WHERE id=?',
                          (time.time()+min(300,5*2**min(job['attempts'],6)),type(exc).__name__,job['id']))
            print('progress permanent cleanup retry:',type(exc).__name__,flush=True)

def moderate(h,rid,action):
    if not A.is_admin(h): return h._send(403,{'error':'需要已驗證的管理員'})
    d=h._body()
    if not isinstance(d,dict): raise ValueError('無效操作')
    reason=text_field(d.get('reason',''),1000,'原因',True)
    with A.LOCK, A.conn() as c:
        c.execute('BEGIN IMMEDIATE')
        r=c.execute('SELECT * FROM progress_reports WHERE id=?',(rid,)).fetchone()
        if not r: return h._send(404,{'error':'找不到回報'})
        if action=='trash':
            if r['status']=='trash':return h._send(409,{'error':'回報已在垃圾桶'})
            c.execute("UPDATE progress_reports SET trash_previous_status=status,status='trash',trash_at=?,trash_reason=? WHERE id=?",(stamp(),reason,rid))
            c.execute('INSERT INTO progress_audit(report_id,action,actor,reason,created) VALUES(?,?,?,?,?)',(rid,'移至垃圾桶','已驗證管理員',reason,stamp()))
        elif action=='untrash':
            if r['status']!='trash':return h._send(409,{'error':'回報不在垃圾桶'})
            c.execute("UPDATE progress_reports SET status=CASE WHEN trash_previous_status='void' THEN 'void' ELSE 'valid' END,trash_at='',trash_reason='',trash_previous_status='' WHERE id=?",(rid,))
            c.execute('INSERT INTO progress_audit(report_id,action,actor,reason,created) VALUES(?,?,?,?,?)',(rid,'從垃圾桶還原','已驗證管理員',reason,stamp()))
        elif action=='void':
            if r['status']!='valid': return h._send(409,{'error':'回報已作廢'})
            c.execute('UPDATE progress_reports SET status=\'void\',void_reason=?,void_at=? WHERE id=?',(reason,stamp(),rid))
            event(c,rid,'作廢回報','已驗證管理員',reason)
        elif action=='restore':
            if r['status']!='void': return h._send(409,{'error':'回報已是有效狀態'})
            c.execute("UPDATE progress_reports SET status='valid',void_reason='',void_at='' WHERE id=?",(rid,))
            event(c,rid,'恢復有效','已驗證管理員',reason)
        else:
            fid=d.get('file_id')
            if not isinstance(fid,str): raise ValueError('請選擇附件')
            f=c.execute('SELECT * FROM progress_files WHERE id=? AND report_id=?',(fid,rid)).fetchone()
            if not f or f['removed_at']: return h._send(404,{'error':'附件不存在或已移除'})
            # 管理員可移除有效或已作廢回報的附件
            # Commit a durable removal intention first; retries finish an interrupted deletion.
            c.execute('UPDATE progress_files SET removed_at=?,reason=? WHERE id=?',(stamp(),reason,fid))
            event(c,rid,'附件移除','已驗證管理員',reason+'；檔名：'+f['name'],fid)
        A.bump(c)
    if action=='remove-file':
        # Public download is disabled before storage deletion. Retained metadata remains searchable.
        try:
            clear_file(f)
        except Exception:
            return h._send(202,{'warning':'附件已停用下載，實體清除待重試'})
    return h._send(200,{'ok':True})

def trash_list(h):
    if not A.is_admin(h):return h._send(403,{'error':'需要已驗證的管理員'})
    with A.LOCK,A.conn() as c:
        rows=[dict(r) for r in c.execute("SELECT * FROM progress_reports WHERE status='trash' ORDER BY trash_at DESC")]
        for r in rows:
            r['files']=[dict(f) for f in c.execute('SELECT id,name,size,removed_at,reason FROM progress_files WHERE report_id=?',(r['id'],))]
        deleted=[dict(r) for r in c.execute('SELECT * FROM progress_deleted_audit ORDER BY id DESC LIMIT 100')]
    h._send(200,{'items':rows,'deleted':deleted})

def permanently_delete(h,rid):
    if not A.is_admin(h):return h._send(403,{'error':'需要已驗證的管理員'})
    d=h._body()
    if not isinstance(d,dict):raise ValueError('無效操作')
    reason=text_field(d.get('reason',''),1000,'原因',True)
    with A.LOCK,A.conn() as c:
        c.execute('BEGIN IMMEDIATE')
        r=c.execute('SELECT * FROM progress_reports WHERE id=?',(rid,)).fetchone()
        if not r:return h._send(404,{'error':'找不到回報'})
        if r['status']!='trash':return h._send(409,{'error':'僅能永久刪除垃圾桶內的回報'})
        if c.execute('SELECT 1 FROM progress_reports WHERE parent_id=? LIMIT 1',(rid,)).fetchone():
            return h._send(409,{'error':'此回報仍有接續回報，請先從最新的接續回報開始處理'})
        files=[dict(f) for f in c.execute('SELECT * FROM progress_files WHERE report_id=?',(rid,))]
        for f in files:
            if not f['cleared_at']:
                c.execute('INSERT OR IGNORE INTO progress_cleanup(id,object_key,storage,created) VALUES(?,?,?,?)',
                          (f['id'],f['object_key'],f['storage'],stamp()))
        c.execute('INSERT INTO progress_deleted_audit(report_id,subject,reporter,actor,reason,created) VALUES(?,?,?,?,?,?)',
                  (rid,r['subject'],r['reporter'],'已驗證管理員',reason,stamp()))
        c.execute('DELETE FROM progress_audit WHERE report_id=?',(rid,))
        c.execute('DELETE FROM progress_files WHERE report_id=?',(rid,))
        c.execute('DELETE FROM progress_reports WHERE id=?',(rid,))
        A.bump(c)
    retry_cleanup([f['id'] for f in files if not f['cleared_at']])
    with A.LOCK,A.conn() as c:
        pending=any(c.execute("SELECT 1 FROM progress_cleanup WHERE id=? AND completed=''",(f['id'],)).fetchone() for f in files)
    return h._send(200,{'ok':True,'warning':'回報已刪除，部分附件清理尚未完成，系統將自動重試' if pending else ''})

def route(h,method):
    p=h._path()
    if not (p=='/api/progress' or p.startswith('/api/progress/') or p.startswith('/api/progress-files/')): return False
    try:
        if method in ('POST','PATCH','DELETE'):
            origin=h.headers.get('Origin')
            if origin and urllib.parse.urlsplit(origin).netloc!=h.headers.get('Host'):
                h._send(403,{'error':'不允許跨網站操作'}); return True
        if method=='POST' and p=='/api/progress/export':
            import progress_export
            progress_export.export(h)
        elif method=='POST' and re.fullmatch(r'/api/progress/[1-9][0-9]*/relink',p):
            if not A.is_admin(h): h._send(403,{'error':'需要管理員'})
            else:
                d=h._body()
                task_id=str(d.get('task_id','')).strip()
                reason=str(d.get('reason','')).strip()
                if not reason or len(reason)>500: raise ValueError('請填寫修正原因')
                with A.LOCK,A.conn() as c:
                    t=c.execute('SELECT task FROM tasks WHERE id=?',(task_id,)).fetchone() if task_id else None
                    if task_id and not t: raise ValueError('找不到工作')
                    rid=int(p.split('/')[3])
                    old=c.execute('SELECT task_id,task_name FROM progress_reports WHERE id=?',(rid,)).fetchone()
                    if not old: raise ValueError('找不到回報')
                    new_name=t['task'] if t else ''
                    c.execute('UPDATE progress_reports SET task_id=?,task_name=? WHERE id=?',(task_id,new_name,rid))
                    c.execute('INSERT INTO progress_audit(report_id,action,actor,reason,created) VALUES(?,?,?,?,?)',
                              (rid,'修正工作關聯','管理員',str(old['task_name'])+' → '+new_name+'；'+reason,stamp()))
                    A.bump(c)
                h._send(200,{'ok':True})
        elif method=='POST' and p=='/api/progress/settings':
            if not A.is_admin(h): h._send(403,{'error':'需要管理員'})
            else:
                d=h._body()
                if not isinstance(d,dict) or not d or any(k not in ('show_report_ids','export_all','audit_all') or type(v) is not bool for k,v in d.items()):raise ValueError('設定格式錯誤')
                with A.LOCK,A.conn() as c:
                    if 'show_report_ids' in d:c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('progress_show_ids',?)",('1' if d['show_report_ids'] else '0',))
                    if 'export_all' in d:c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('progress_export_all',?)",('1' if d['export_all'] else '0',))
                    if 'audit_all' in d:c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('progress_audit_all',?)",('1' if d['audit_all'] else '0',))
                h._send(200,{'ok':True})
        elif method=='GET' and p=='/api/progress/trash':trash_list(h)
        elif method=='POST' and re.fullmatch(r'/api/progress/[1-9][0-9]*/delete',p):permanently_delete(h,int(p.split('/')[3]))
        elif method=='GET' and p=='/api/progress': list_reports(h)
        elif method=='GET' and re.fullmatch('/api/progress-files/[a-f0-9]{32}',p): download(h,p.rsplit('/',1)[1])
        elif method=='POST' and p=='/api/progress': create(h)
        elif method=='POST' and re.fullmatch(r'/api/progress/[1-9][0-9]*/(void|restore|remove-file|trash|untrash)',p):
            _,_,_,rid,action=p.split('/'); moderate(h,int(rid),action)
        elif method=='GET' and re.fullmatch(r'/api/progress/[1-9][0-9]*/audit',p):
            with A.LOCK,A.conn() as c:
                allowed=A.is_admin(h) or (c.execute("SELECT v FROM meta WHERE k='progress_audit_all'").fetchone() or {'v':'0'})['v']=='1'
                if not allowed:h._send(403,{'error':'目前僅管理員可查看操作紀錄'})
                else:h._send(200,{'items':[dict(r) for r in c.execute('SELECT * FROM progress_audit WHERE report_id=? ORDER BY id',(int(p.split('/')[3]),))]})
        elif method=='GET' and p=='/api/progress/notification-status':
            if not A.is_admin(h): h._send(403,{'error':'需要管理員'})
            else:
                with A.LOCK,A.conn() as c:
                    recent=c.execute("SELECT error FROM progress_outbox WHERE sent_at='' AND error<>'' ORDER BY created DESC LIMIT 1").fetchone()
                    h._send(200,{'configured':bool(os.environ.get('DISCORD_WEBHOOK_URL')), 'enabled':bool(A.notify_config(c).get('enabled')), 'pending':c.execute("SELECT count(*) FROM progress_outbox WHERE sent_at='' ").fetchone()[0], 'failed':c.execute("SELECT count(*) FROM progress_outbox WHERE sent_at='' AND attempts>0").fetchone()[0], 'recent_error':recent['error'] if recent else ''})
        else: h._send(405,{'error':'回報送出後不可修改；請接續建立新版本'})
    except (ValueError,UnicodeError) as exc:
        h.close_connection=True; h._send(400,{'error':str(exc)})
    except Exception as exc:
        print('progress request failed:',type(exc).__name__,flush=True)
        h.close_connection=True; h._send(503,{'error':'儲存服務暫時無法使用，請重新整理確認後再試'})
    return True


