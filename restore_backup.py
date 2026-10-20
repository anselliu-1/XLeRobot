"""Staging-only, administrator-confirmed data restore; never executes archived code."""
import hashlib,json,os,re,shutil,sqlite3,tempfile,time,uuid,zipfile
from pathlib import Path,PurePosixPath
from contextlib import closing
from urllib.parse import urlsplit

SESSIONS={}
MAX_ZIP=512*1024*1024
MAX_EXPANDED=2*1024*1024*1024
TTL=20*60
SKIP={'admin_restore_audit'}

def schema(c):
    return {r[0]:[v[1] for v in c.execute('PRAGMA table_info("'+r[0]+'")')] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'") if re.fullmatch('[a-z_]+',r[0]) and r[0] not in SKIP}

def fingerprint(c):
    digest=hashlib.sha256()
    for table in sorted(schema(c)):
        if table in ('admin_backup_audit','notify_queue','progress_outbox'):continue
        digest.update(table.encode())
        for row in c.execute('SELECT * FROM "'+table+'" ORDER BY rowid'):
            digest.update(json.dumps(list(row),ensure_ascii=False,separators=(',',':')).encode())
    return digest.hexdigest()

def audit(A,ident,status,detail=''):
    with A.LOCK,A.conn() as c:
        c.execute('CREATE TABLE IF NOT EXISTS admin_restore_audit(id TEXT PRIMARY KEY,created TEXT NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL)')
        c.execute('INSERT OR REPLACE INTO admin_restore_audit VALUES(?,?,?,?)',(ident,A.progress.stamp(),status,detail[:2000]))

def inspect_archive(A,archive,folder):
    import backup
    db=Path(folder)/'checked.sqlite3'
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist();names=[i.filename for i in infos]
        if len(names)!=len(set(names)) or len(names)>20000:raise ValueError('ZIP 含重複項目或檔案數過多')
        if sum(i.file_size for i in infos)>MAX_EXPANDED:raise ValueError('ZIP 解壓總大小上限為 2 GB')
        for i in infos:
            p=PurePosixPath(i.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in i.filename or ':' in i.filename or (i.external_attr>>16)&0o170000==0o120000:raise ValueError('ZIP 含不安全路徑')
            if i.flag_bits&1:raise ValueError('不支援加密 ZIP')
        if z.getinfo('manifest.json').file_size>10*1024*1024:raise ValueError('備份清單過大')
        m=json.loads(z.read('manifest.json'))
        if m.get('format')!='XLeRobot-backup-v1' or m.get('database')!='database/data.sqlite3':raise ValueError('不是支援的 XLeRobot 備份')
        if z.getinfo(m['database']).file_size>256*1024*1024:raise ValueError('資料庫快照超過 256 MB')
        if shutil.disk_usage(folder).free<sum(i.file_size for i in infos)*2+32*1024*1024:raise ValueError('暫存空間不足')
        with z.open(m['database']) as src,open(db,'wb') as dst:shutil.copyfileobj(src,dst)
        if hashlib.sha256(db.read_bytes()).hexdigest()!=m.get('database_sha256'):raise ValueError('資料庫雜湊核對失敗')
        with closing(sqlite3.connect(db)) as c,A.LOCK,A.conn() as current:
            c.row_factory=sqlite3.Row;c.execute('PRAGMA trusted_schema=OFF')
            if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('資料庫完整性檢查失敗')
            if c.execute("SELECT 1 FROM sqlite_master WHERE type IN ('view','trigger') OR lower(sql) LIKE '%virtual table%'").fetchone():raise ValueError('不接受含觸發器、檢視或虛擬表的備份')
            expected=schema(current);actual=schema(c)
            core={'tasks','meta','attachments','purchases','purchase_images','purchase_receipts','progress_reports','progress_files','progress_audit'}
            if not core.issubset(actual) or set(actual)-set(expected):raise ValueError('備份資料表版本不相容')
            # Only current, trusted schema definitions supply migrations; archived code is never executed.
            for table,columns in expected.items():
                if table not in actual:
                    ddl=current.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()[0];c.execute(ddl);continue
                if set(actual[table])-set(columns):raise ValueError('備份含目前版本不支援的欄位')
                for col in current.execute('PRAGMA table_info("'+table+'")'):
                    if col[1] in actual[table]:continue
                    if col[5] or col[3] and col[4] is None:raise ValueError('備份缺少必要欄位')
                    definition='"'+col[1]+'" '+col[2]+(' NOT NULL' if col[3] else '')+(' DEFAULT '+col[4] if col[4] is not None else '')
                    c.execute('ALTER TABLE "'+table+'" ADD COLUMN '+definition)
            c.commit();actual=schema(c)
            if set(actual)!=set(expected) or any(set(actual[t])!=set(expected[t]) for t in actual):raise ValueError('資料表版本檢查未通過')
            if c.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('備份資料關聯不完整')
            c.execute('PRAGMA query_only=ON')
            required,_=backup.inventory(c);base=fingerprint(current)
            counts={t:c.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in actual}
            current_counts={t:current.execute('SELECT COUNT(*) FROM "'+t+'"').fetchone()[0] for t in actual}
        entries=m.get('files')
        if not isinstance(entries,list) or len(entries)!=len(required):raise ValueError('附件數量與資料庫不符')
        records={(f['table'],str(f['id'])):f for f in required};seen=set()
        for f in entries:
            if type(f.get('size')) is not int or not 0<=f['size']<=50*1024*1024:raise ValueError('單一附件不得超過 50 MB')
            key=(f.get('table'),str(f.get('id')))
            if key not in records or key in seen:raise ValueError('附件清單重複或不符')
            seen.add(key);record=records[key]
            if any(f.get(k)!=record[k] for k in ('name','size','object_key','storage','local_key')):raise ValueError('附件資料與快照不符')
            path=f.get('archive_path','')
            if not path.startswith('files/') or z.getinfo(path).file_size!=record['size']:raise ValueError('附件路徑或大小不符')
            digest=hashlib.sha256()
            with z.open(path) as stream:
                while True:
                    chunk=stream.read(1024*1024)
                    if not chunk:break
                    digest.update(chunk)
            if digest.hexdigest()!=f.get('sha256'):raise ValueError('附件雜湊核對失敗')
    return {'manifest':m,'database':str(db),'base':base,'counts':counts,'current_counts':current_counts,'schema':expected}

def apply_restore(A,session,ident):
    import backup
    # Stage all restored attachments at new keys; existing objects are never overwritten.
    staged=Path(session['folder'])/'staged.sqlite3';shutil.copy2(session['database'],staged)
    safety_root=Path(A.DB).resolve().parent/'restore-safety';safety_root.mkdir(exist_ok=True)
    safety=safety_root/(ident+'.zip')
    with tempfile.TemporaryDirectory(prefix='before-restore-') as folder:
        archive,_=backup.build(folder);shutil.copy2(archive,safety)
    with closing(sqlite3.connect(staged)) as c,zipfile.ZipFile(session['archive']) as z:
        for f in session['manifest']['files']:
            name='restore-'+ident+'-'+uuid.uuid4().hex+Path(f['name']).suffix[:12]
            key=('progress/restored/' if f['table']=='progress_files' else {'attachments':'uploads/','purchase_images':'purchases/','purchase_receipts':'receipts/'}[f['table']])+name
            data=z.read(f['archive_path'])
            if A.S3_ENABLED:A.s3_request('PUT',key,data)
            else:
                destination=Path(A.UPLOAD_DIR)/(key if f['table']=='progress_files' else name)
                destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
            storage='bucket' if A.S3_ENABLED else 'local'
            if f['table']=='progress_files':c.execute('UPDATE progress_files SET object_key=?,storage=? WHERE id=?',(key,storage,f['id']))
            else:c.execute('UPDATE "'+f['table']+'" SET stored_name=?,storage=? WHERE id=?',(name,storage,f['id']))
        c.commit()
    with A.LOCK,A.conn() as c:
        c.execute('BEGIN IMMEDIATE')
        if fingerprint(c)!=session['base']:raise ValueError('預覽後資料已變更，未套用還原；請重新上傳檢查')
        old_rev=A.rev(c)
        c.execute('PRAGMA trusted_schema=OFF')
        c.execute('ATTACH DATABASE ? AS restored',(str(staged),))
        for table,columns in session['schema'].items():
            names=','.join('"'+name+'"' for name in columns)
            c.execute('DELETE FROM main."'+table+'"')
            c.execute('INSERT INTO main."'+table+'"('+names+') SELECT '+names+' FROM restored."'+table+'"')
        cfg=A.notify_config(c);cfg['enabled']=False
        c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('notify_config',?)",(json.dumps(cfg),))
        c.execute("UPDATE notify_queue SET sent=1,error='整站還原：略過舊待送通知' WHERE sent=0")
        c.execute("UPDATE progress_outbox SET sent_at=?,error='整站還原：略過舊待送通知' WHERE sent_at=''",(A.progress.stamp(),))
        for table in ('purchase_cleanup','progress_cleanup'):
            c.execute('UPDATE '+table+" SET completed=?,error='整站還原：暫停舊清理意圖，保留現有物件' WHERE completed=''",(A.progress.stamp(),))
        c.execute("UPDATE meta SET v=? WHERE k='rev'",(str(max(old_rev,A.rev(c))+1),))
        c.execute('INSERT OR REPLACE INTO admin_restore_audit VALUES(?,?,?,?)',(ident,A.progress.stamp(),'restored','管理員確認還原；安全副本 '+safety.name))
    return safety

def route(A,h,method):
    path=h._path()
    if not path.startswith('/api/admin/restore'):return False
    if not A.is_admin(h):h._send(403,{'error':'需要已驗證的管理員'});return True
    if os.environ.get('RAILWAY_ENVIRONMENT_NAME')!='staging':h._send(403,{'error':'整站還原僅開放 staging 測試環境'});return True
    origin=h.headers.get('Origin')
    if origin and urlsplit(origin).netloc!=h.headers.get('Host'):h._send(403,{'error':'不允許跨網站操作'});return True
    import backup
    if not backup.BUSY.acquire(blocking=False):h._send(409,{'error':'備份或還原正在進行'});return True
    try:
        for ident,s in list(SESSIONS.items()):
            if time.time()>s['expires']:shutil.rmtree(s['folder'],ignore_errors=True);SESSIONS.pop(ident,None)
        if method=='GET' and re.fullmatch('/api/admin/restore/safety/[a-f0-9]{32}',path):
            file=Path(A.DB).resolve().parent/'restore-safety'/(path.rsplit('/',1)[1]+'.zip')
            if not file.is_file():raise ValueError('沒有可下載的還原前副本')
            h.send_response(200);h.send_header('Content-Type','application/zip');h.send_header('Content-Disposition','attachment; filename="XLeRobot-before-restore.zip"');h.send_header('Cache-Control','no-store');h.send_header('Content-Length',str(file.stat().st_size));h.end_headers()
            with open(file,'rb') as stream:shutil.copyfileobj(stream,h.wfile)
        elif method=='POST' and path=='/api/admin/restore/preview':
            if len(SESSIONS)>=2:raise ValueError('已有待確認的備份，請先取消或等待 20 分鐘過期')
            length=int(h.headers.get('Content-Length','0'))
            if not 0<length<=MAX_ZIP:raise ValueError('ZIP 上傳上限為 512 MB')
            ident=uuid.uuid4().hex;folder=tempfile.mkdtemp(prefix='xle-restore-');archive=Path(folder)/'upload.zip'
            try:
                h.connection.settimeout(120)
                with open(archive,'wb') as out:
                    left=length
                    while left:
                        part=h.rfile.read(min(left,1024*1024))
                        if not part:raise ValueError('ZIP 上傳不完整')
                        out.write(part);left-=len(part)
                inspected=inspect_archive(A,archive,folder)
                SESSIONS[ident]={**inspected,'folder':folder,'archive':str(archive),'expires':time.time()+TTL}
                audit(A,ident,'previewed','附件與資料庫驗證通過；尚未還原')
                h._send(200,{'token':ident,'created':inspected['manifest']['created'],'version':inspected['manifest'].get('version'),'tables':inspected['counts'],'current_tables':inspected['current_counts'],'files':len(inspected['manifest']['files']),'bytes':sum(f['size'] for f in inspected['manifest']['files']),'expires_seconds':TTL,'warning':'僅還原資料與附件，不執行備份內的程式。不還原環境變數；完成後停用通知並略過舊待送通知。'})
            except Exception:
                shutil.rmtree(folder,ignore_errors=True);SESSIONS.pop(ident,None);raise
        elif method=='POST' and path in ('/api/admin/restore/apply','/api/admin/restore/cancel'):
            d=h._body();ident=d.get('token','');session=SESSIONS.get(ident)
            if not session:raise ValueError('檢查預覽已過期，請重新上傳')
            if path.endswith('/cancel'):
                shutil.rmtree(session['folder'],ignore_errors=True);SESSIONS.pop(ident,None);h._send(200,{'ok':True})
            else:
                if d.get('confirm')!='還原測試站':raise ValueError('請輸入「還原測試站」確認')
                if not str(d.get('reason','')).strip():raise ValueError('請填寫還原原因')
                with A.LOCK,A.conn() as c:
                    if fingerprint(c)!=session['base']:raise ValueError('預覽後資料已變更，請重新上傳檢查')
                audit(A,ident,'restoring',str(d['reason']))
                try:apply_restore(A,session,ident)
                except Exception:
                    audit(A,ident,'failed','未完成還原；原資料庫交易已回復，請檢查安全副本。');raise
                shutil.rmtree(session['folder'],ignore_errors=True);SESSIONS.pop(ident,None)
                h._send(200,{'ok':True,'safety_id':ident,'message':'還原完成；通知已停用，舊待送通知已略過。請重新整理並檢查資料。'})
        else:h._send(405,{'error':'不支援此操作'})
    except (ValueError,KeyError,zipfile.BadZipFile,sqlite3.Error) as exc:h._send(400,{'error':'還原檢查未通過：'+str(exc)[:200]})
    except Exception:h._send(503,{'error':'還原未完成：儲存空間、附件或服務連線異常。未完成資料庫交易會回復原狀。'})
    finally:backup.BUSY.release()
    return True
