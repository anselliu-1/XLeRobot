"""Administrator-only complete data export, built on disk before sending any ZIP."""
import hashlib, json, os, re, shutil, sqlite3, tempfile, threading, uuid, zipfile
from pathlib import Path
from contextlib import closing

BUSY=threading.BoundedSemaphore(1)

def init(app):
    global A
    A=app
    with A.LOCK,A.conn() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS admin_backup_audit(
          id TEXT PRIMARY KEY, created TEXT NOT NULL, completed TEXT NOT NULL DEFAULT '',
          actor TEXT NOT NULL, status TEXT NOT NULL, file_count INTEGER NOT NULL DEFAULT 0,
          archive_bytes INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '')''')

def inventory(c):
    files=[]; removed=[]
    for table,prefix in [('attachments','uploads'),('purchase_images','purchases'),('purchase_receipts','receipts')]:
        for row in c.execute('SELECT * FROM '+table):
            r=dict(row)
            if table!='attachments' and c.execute('SELECT 1 FROM purchase_cleanup WHERE file_table=? AND file_id=?',(table,r['id'])).fetchone():
                removed.append({'table':table,'id':r['id'],'name':r['original_name'],'reason':'管理員已要求永久移除，清理中或已完成'});continue
            files.append({'table':table,'id':r['id'],'name':r['original_name'],'size':r['size'],
                          'storage':r.get('storage') or 'local','local_key':r['stored_name'],
                          'object_key':prefix+'/'+r['stored_name']})
    for row in c.execute('SELECT * FROM progress_files'):
        r=dict(row)
        if r['removed_at']:
            removed.append({'id':r['id'],'report_id':r['report_id'],'name':r['name'],'removed_at':r['removed_at'],'reason':r['reason']})
        else:
            files.append({'table':'progress_files','id':r['id'],'name':r['name'],'size':r['size'],
                          'storage':r['storage'],'local_key':r['object_key'],'object_key':r['object_key']})
    return files,removed

def local_path(key):
    root=Path(A.UPLOAD_DIR).resolve();path=(root/key).resolve()
    if root not in path.parents: raise ValueError('Invalid attachment path')
    return path

def filename(value):
    value=str(value).replace('\\','/').split('/')[-1]
    return re.sub(r'[\x00-\x1f\x7f<>:"|?*]','_',value)[:180] or 'attachment'

def build(folder):
    snapshot=Path(folder)/'data.sqlite3'
    # SQLite's backup API creates a consistent database, including WAL changes.
    with A.LOCK,A.conn() as source,closing(sqlite3.connect(snapshot)) as dest:
        source.backup(dest)
    with closing(sqlite3.connect(snapshot)) as check:
        check.row_factory=sqlite3.Row
        if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise ValueError('Database integrity check failed')
        files,removed=inventory(check)
        tables=[r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts={name:check.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables}
        required=snapshot.stat().st_size*2+sum(max(0,int(f['size'])) for f in files)*1.02+16*1024*1024
        if shutil.disk_usage(folder).free<required: raise OSError('Insufficient temporary disk space')
        manifest={'format':'XLeRobot-backup-v1','created':A.progress.stamp(),'version':A.APP_VERSION,
                  'database':'database/data.sqlite3','database_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                  'tables':counts,'files':[],'removed_files_not_included':removed,
                  'scope':'All SQLite records and all active attachments referenced by this database; excludes credentials and already removed files.'}
        archive=Path(folder)/'backup.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
            z.write(snapshot,'database/data.sqlite3')
            # Include readable data alongside SQLite for inspection and future migration.
            for table in tables:
                data=[dict(r) for r in check.execute('SELECT * FROM "'+table.replace('"','""')+'"')]
                z.writestr('data/'+table+'.json',json.dumps(data,ensure_ascii=False,indent=2))
            for f in files:
                target='files/'+f['table']+'/'+filename(f['id'])+'/'+filename(f['name'])
                digest=hashlib.sha256();size=0
                with z.open(target,'w',force_zip64=True) as out:
                    if f['storage']=='bucket':
                        body,_=A.s3_request('GET',f['object_key'])
                        size=len(body);digest.update(body);out.write(body)
                    else:
                        with open(local_path(f['local_key']),'rb') as stream:
                            while True:
                                chunk=stream.read(1024*1024)
                                if not chunk: break
                                size+=len(chunk);digest.update(chunk);out.write(chunk)
                if size!=f['size']: raise ValueError('Attachment size mismatch')
                manifest['files'].append({**f,'archive_path':target,'sha256':digest.hexdigest()})
            # Include the deployed application files so fixed project content is preserved too.
            root=Path(__file__).resolve().parent
            for path in sorted(root.iterdir()):
                if path.is_file() and path.suffix.lower() in {'.py','.js','.css','.html','.md','.png','.jpg','.jpeg','.svg'}:
                    z.write(path,'application/'+path.name)
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            z.writestr('README.txt',
                'XLeRobot 完整資料備份\n\n'
                'database/data.sqlite3：SQLite 一致性快照。data/：各資料表 JSON。\n'
                'files/：分工附件、採購圖片、報銷憑證、進度回報附件。\n'
                'application/：此部署的程式與固定網站內容。manifest.json：原始儲存位置、檔案大小及 SHA-256。\n'
                '已永久移除、或管理員已要求永久移除而正在清理的附件不包含檔案內容，操作及清理紀錄仍在資料庫。\n'
                '還原前請檢查 purchase_cleanup 與 purchase_delete_audit 中的刪除意圖，避免把清理中的檔案誤認為可還原。\n'
                '還原需先停站、備份當前資料，再以快照及 manifest 對照還原附件；本功能不會自動覆寫線上資料。\n'
                '還原後先停用 Discord 通知並檢查待送佇列，避免重複補送。\n'
                '不包含管理員金鑰、S3 憑證、Discord webhook 或其他 Railway 環境變數；這些需另行安全保存。\n'
                '若有附件無法讀取，整份備份會失敗，不會產生看似完整但漏檔的 ZIP。\n')
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise ValueError('Archive integrity check failed')
    return archive,len(files)

def route(h,method='POST'):
    path=h._path()
    if path not in ('/api/admin/backup','/api/admin/backup/status'): return False
    if not A.is_admin(h): h._send(403,{'error':'需要已驗證的管理員'}); return True
    if path=='/api/admin/backup/status' and method=='GET':
        with A.LOCK,A.conn() as c:
            row=c.execute("SELECT completed FROM admin_backup_audit WHERE status='transferred' AND completed<>'' ORDER BY completed DESC LIMIT 1").fetchone()
        h._send(200,{'last_backup_at':row['completed'] if row else None});return True
    if path!='/api/admin/backup' or method!='POST':
        h._send(405,{'error':'不支援此操作'});return True
    from urllib.parse import urlsplit
    origin=h.headers.get('Origin')
    if origin and urlsplit(origin).netloc!=h.headers.get('Host'):
        h._send(403,{'error':'不允許跨網站操作'}); return True
    if not BUSY.acquire(blocking=False):
        h._send(409,{'error':'已有備份正在進行，請稍後再試'});return True
    ident=uuid.uuid4().hex;sent=False
    try:
        with A.LOCK,A.conn() as c:
            c.execute('INSERT INTO admin_backup_audit(id,created,actor,status) VALUES(?,?,?,?)',(ident,A.progress.stamp(),'已驗證管理員','building'))
        with tempfile.TemporaryDirectory(prefix='xle-backup-',dir=os.environ.get('BACKUP_TMP_DIR') or None) as folder:
            archive,count=build(folder)
            size=archive.stat().st_size
            h.send_response(200)
            h.send_header('Content-Type','application/zip')
            h.send_header('Content-Disposition','attachment; filename="XLeRobot-backup-'+A.datetime.now(A.TZ).strftime('%Y%m%d-%H%M%S')+'.zip"')
            h.send_header('Cache-Control','no-store, private')
            h.send_header('X-Content-Type-Options','nosniff')
            h.send_header('Content-Length',str(size));h.end_headers();sent=True
            with open(archive,'rb') as stream: shutil.copyfileobj(stream,h.wfile,length=1024*1024)
            with A.LOCK,A.conn() as c:
                c.execute("UPDATE admin_backup_audit SET status='transferred',completed=?,file_count=?,archive_bytes=? WHERE id=?",(A.progress.stamp(),count,size,ident))
    except Exception as exc:
        with A.LOCK,A.conn() as c:
            c.execute("UPDATE admin_backup_audit SET status='failed',completed=?,error=? WHERE id=?",(A.progress.stamp(),type(exc).__name__,ident))
        if not sent: h._send(503,{'error':'備份未完成：有附件無法讀取、資料在備份期間變動，或暫存空間不足。未提供不完整備份，請稍後重試。'})
        else: h.close_connection=True
    finally: BUSY.release()
    return True

