"""Purchase revisions and durable, auditable attachment cleanup."""
import os,time,uuid,threading

def install(app):
    global A
    A=app

def init(c):
    cols={r[1] for r in c.execute('PRAGMA table_info(purchases)')}
    for col,ddl in [('revision','INTEGER NOT NULL DEFAULT 1'),('deleting','INTEGER NOT NULL DEFAULT 0')]:
        if col not in cols:c.execute('ALTER TABLE purchases ADD COLUMN '+col+' '+ddl)
    c.executescript('''CREATE TABLE IF NOT EXISTS purchase_cleanup(
      id TEXT PRIMARY KEY,file_table TEXT NOT NULL,file_id TEXT NOT NULL,purchase_id TEXT NOT NULL,
      name TEXT NOT NULL,object_key TEXT NOT NULL,local_key TEXT NOT NULL,storage TEXT NOT NULL,
      created TEXT NOT NULL,completed TEXT NOT NULL DEFAULT '',attempts INTEGER NOT NULL DEFAULT 0,
      next_try REAL NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',UNIQUE(file_table,file_id));
      CREATE TABLE IF NOT EXISTS purchase_delete_audit(
      id TEXT PRIMARY KEY,purchase_id TEXT NOT NULL,name TEXT NOT NULL,created TEXT NOT NULL,
      completed TEXT NOT NULL DEFAULT '',actor TEXT NOT NULL);''')

def queued(c,table,fid):
    return bool(c.execute('SELECT 1 FROM purchase_cleanup WHERE file_table=? AND file_id=?',(table,fid)).fetchone())

def queue_file(c,table,row):
    prefix='purchases/' if table=='purchase_images' else 'receipts/'
    c.execute('''INSERT OR IGNORE INTO purchase_cleanup(id,file_table,file_id,purchase_id,name,object_key,local_key,storage,created)
      VALUES(?,?,?,?,?,?,?,?,?)''',(uuid.uuid4().hex,table,row['id'],row['purchase_id'],row['original_name'],prefix+row['stored_name'],row['stored_name'],row['storage'],A.now_s()))

def snapshot(c,ident,admin):
    return next((r for r in A.purchase_rows(c,admin) if r['id']==ident),None)

def patch(h,ident):
    try:
        raw=h._body()
        if not isinstance(raw,dict):raise ValueError('無效資料')
        allowed={'name','spec','qty','price','status','owner','url','note','stock','actual_price','refund','revision'}
        if any(k not in allowed for k in raw):raise ValueError('未知欄位')
        with A.LOCK,A.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM purchases WHERE id=?',(ident,)).fetchone()
            if not old:return h._send(404,{'error':'採購項目已不存在'})
            admin=A.is_admin(h)
            if old['deleting']:return h._send(409,{'error':'此項目正在刪除，無法再修改','current':snapshot(c,ident,admin)})
            if type(raw.get('revision')) is not int or raw['revision']!=old['revision']:
                return h._send(409,{'error':'此項目已被更新，請比較最新資料後再儲存','current':snapshot(c,ident,admin)})
            merged={**dict(old),**raw}
            d=A.clean_purchase(merged);h._purchase_raw=raw
            extra=h._purchase_extra(d,old,admin,A.purchase_permissions(c))
            if extra is None:return h._send(403,{'error':'沒有權限修改此欄位'})
            d.update(extra)
            c.execute('UPDATE purchases SET '+','.join(k+'=?' for k in d)+',revision=revision+1 WHERE id=?',(*d.values(),ident))
            for field,event,title in [('status','buy_status','採購狀態更新'),('stock','buy_stock','庫存確認更新'),('owner','buy_owner','採購負責人更新'),('refund','buy_refund','報銷狀態更新')]:
                if str(old[field])!=str(d[field]):A.queue_notify(c,event,title,d['name']+'：'+str(old[field])+' → '+str(d[field]))
            changes=A.notify_changes(old,d,A.PURCHASE_NOTIFY_FIELDS)
            if changes:A.queue_notify(c,'buy_edit','採購資料修改','商品：'+d['name']+'\n'+changes)
            return h._send(200,{'purchases':A.purchase_rows(c,admin)})
    except (ValueError,TypeError,OverflowError) as exc:return h._send(400,{'error':str(exc)})

def request_delete(h,ident,table=None):
    if not A.is_admin(h):return h._send(403,{'error':'需要已驗證的管理員'})
    try:
        raw=h._body()
        with A.LOCK,A.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            file=c.execute('SELECT * FROM '+table+' WHERE id=?',(ident,)).fetchone() if table else None
            pid=file['purchase_id'] if file else ident
            old=c.execute('SELECT * FROM purchases WHERE id=?',(pid,)).fetchone()
            if not old or (table and not file):return h._send(404,{'error':'找不到項目'})
            if old['deleting']:return h._send(409,{'error':'此項目已在刪除處理中'})
            if type(raw.get('revision')) is not int or raw['revision']!=old['revision']:
                return h._send(409,{'error':'此項目已更新，請重新確認刪除內容','current':snapshot(c,pid,True)})
            if table:
                queue_file(c,table,file)
                A.queue_notify(c,'buy_delete','移除採購附件',file['original_name'])
            else:
                c.execute('UPDATE purchases SET deleting=1 WHERE id=?',(pid,))
                for ft in ('purchase_images','purchase_receipts'):
                    for row in c.execute('SELECT * FROM '+ft+' WHERE purchase_id=?',(pid,)).fetchall():queue_file(c,ft,row)
                c.execute('INSERT INTO purchase_delete_audit VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,pid,old['name'],A.now_s(),'','已驗證管理員'))
                A.queue_notify(c,'buy_delete','刪除採購項目',old['name'])
            c.execute('UPDATE purchases SET revision=revision+1 WHERE id=?',(pid,))
        # The worker handles remote deletion after the intention is committed.
        with A.LOCK,A.conn() as c:
            return h._send(202,{'ok':True,'message':'已開始刪除，附件清理將自動重試','purchases':A.purchase_rows(c,True)})
    except (ValueError,TypeError) as exc:return h._send(400,{'error':str(exc)})

def retry_cleanup():
    with A.LOCK,A.conn() as c:
        jobs=[dict(r) for r in c.execute("SELECT * FROM purchase_cleanup WHERE completed='' AND next_try<=? ORDER BY created LIMIT 10",(time.time(),))]
    for job in jobs:
        try:
            try:
                if job['storage']=='bucket':A.s3_request('DELETE',job['object_key'])
                else:os.remove(os.path.join(A.UPLOAD_DIR,job['local_key']))
            except FileNotFoundError:pass
            with A.LOCK,A.conn() as c:
                c.execute("UPDATE purchase_cleanup SET completed=?,error='' WHERE id=?",(A.now_s(),job['id']))
                c.execute('DELETE FROM '+job['file_table']+' WHERE id=?',(job['file_id'],))
        except Exception as exc:
            with A.LOCK,A.conn() as c:
                c.execute('UPDATE purchase_cleanup SET attempts=attempts+1,next_try=?,error=? WHERE id=?',
                          (time.time()+min(300,5*2**min(job['attempts'],6)),type(exc).__name__,job['id']))
    with A.LOCK,A.conn() as c:
        for p in c.execute('SELECT id FROM purchases WHERE deleting=1').fetchall():
            if c.execute("SELECT 1 FROM purchase_cleanup WHERE purchase_id=? AND completed=''",(p['id'],)).fetchone():continue
            c.execute('DELETE FROM purchases WHERE id=?',(p['id'],))
            c.execute("UPDATE purchase_delete_audit SET completed=? WHERE purchase_id=? AND completed=''",(A.now_s(),p['id']))

def worker():
    while True:
        try:retry_cleanup()
        except Exception as exc:print('purchase cleanup retry:',type(exc).__name__,flush=True)
        time.sleep(5)

def status(h):
    if not A.is_admin(h):return h._send(403,{'error':'需要已驗證的管理員'})
    with A.LOCK,A.conn() as c:
        jobs=[dict(r) for r in c.execute("SELECT name,created,completed,attempts,error FROM purchase_cleanup ORDER BY completed='' DESC,created DESC LIMIT 30")]
        audit=[dict(r) for r in c.execute('SELECT name,created,completed FROM purchase_delete_audit ORDER BY created DESC LIMIT 20')]
        pending=c.execute("SELECT COUNT(*) FROM purchase_cleanup WHERE completed=''").fetchone()[0]
    h._send(200,{'jobs':jobs,'deletions':audit,'pending_total':pending})
