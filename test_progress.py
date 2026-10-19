"""Run against disposable local SQLite/storage only: python -m unittest -v test_progress."""
import os, tempfile, threading, unittest, json, urllib.request, urllib.error, hashlib
from pathlib import Path
from unittest.mock import patch
import server as app
import progress

class ProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent)
        app.DB=os.path.join(cls.temp.name,'test.db')
        app.UPLOAD_DIR=os.path.join(cls.temp.name,'uploads')
        app.S3_ENABLED=False
        app.ADMIN_HASH=hashlib.sha256(b'test-only-key').hexdigest()
        app.init(); progress.init(); app.backup.init(app)
        cls.http=None
        cls.base='http://127.0.0.1'
        if not os.environ.get('PROGRESS_IN_PROCESS'):
            cls.http=app.ThreadingHTTPServer(('127.0.0.1',0),app.H)
            cls.base+=':'+str(cls.http.server_port)
            threading.Thread(target=cls.http.serve_forever,daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        if cls.http: cls.http.shutdown();cls.http.server_close()
        cls.temp.cleanup()

    def req(self,path,method='GET',data=None,admin=False,headers=None):
        hdr=dict(headers or {})
        if admin: hdr['X-Admin-Key']='test-only-key'
        if isinstance(data,dict): data=json.dumps(data).encode();hdr['Content-Type']='application/json'
        if os.environ.get('PROGRESS_IN_PROCESS'):
            # Exercise the actual HTTP handlers without opening network sockets.
            import io
            from email.parser import BytesParser
            from types import SimpleNamespace
            h=app.H.__new__(app.H)
            h.path=path;h.command=method;h.request_version='HTTP/1.1';h.requestline=method+' '+path+' HTTP/1.1'
            hdr['Content-Length']=str(len(data or b''))
            h.headers=BytesParser().parsebytes(('\r\n'.join(k+': '+v for k,v in hdr.items())+'\r\n\r\n').encode())
            h.rfile=io.BytesIO(data or b'');h.wfile=io.BytesIO();h.connection=SimpleNamespace(settimeout=lambda n:None)
            getattr(h,'do_'+method)()
            head,raw=h.wfile.getvalue().split(b'\r\n\r\n',1)
            status=int(head.split(b' ',2)[1]);headers=BytesParser().parsebytes(head.split(b'\r\n',1)[1]+b'\r\n\r\n')
            return status,json.loads(raw) if 'application/json' in headers.get('Content-Type','') else raw,headers
        req=urllib.request.Request(self.base+path,data=data,headers=hdr,method=method)
        try: r=urllib.request.urlopen(req,timeout=60)
        except urllib.error.HTTPError as e: r=e
        with r:
            raw=r.read()
            return r.status,json.loads(raw) if 'application/json' in r.headers.get('Content-Type','') else raw,r.headers

    def setUp(self):
        with app.conn() as c:
            c.execute("UPDATE meta SET v=? WHERE k='notify_config'",(json.dumps({'enabled':True,'mode':'instant','events':list(app.NOTIFY_EVENTS)}),))

    def create(self,fields=None,files=None,headers=None):
        boundary='test-progress-boundary'
        parts=[]
        for k,v in (fields or {'reporter':'測試甲','subject':'手臂測試','content':'定位偏差'}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
        for name,body in files or []:
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\nContent-Type: text/html\r\n\r\n'.encode()+body+b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        return self.req('/api/progress','POST',b''.join(parts),headers={'Content-Type':'multipart/form-data; boundary='+boundary,**(headers or {})})

    def test_lifecycle(self):
        code,d,_=self.create(files=[('控制.py',b'print(1)'),('成果.mp4',b'video')]);self.assertEqual(code,201)
        rid=d['id']
        code,d,_=self.create({'reporter':'測試乙','subject':'ignored','content':'改善','parent_id':str(rid)})
        self.assertEqual((code,d['version']),(201,2));second=d['id']
        code,d,_=self.create({'reporter':'測試丙','subject':'ignored','content':'另一方向','parent_id':str(rid)})
        self.assertEqual(d['version'],3)
        _,d,_=self.req('/api/progress?q='+urllib.parse.quote('控制.py'))
        self.assertEqual(d['matched_ids'],[rid]);self.assertEqual(len(d['items']),3)
        root=d['items'][0];self.assertTrue(root['created'].endswith('+08:00'))
        self.assertEqual(d['items'][1]['files'],[]);self.assertEqual(d['items'][1]['parent_id'],rid)
        self.assertEqual(d['items'][1]['subject'],root['subject'])
        fid=root['files'][0]['id'];url=root['files'][0]['url']
        code,raw,hdr=self.req(url);self.assertEqual(raw,b'print(1)');self.assertEqual(hdr['Content-Type'],'application/octet-stream')
        self.assertIn('attachment;',hdr['Content-Disposition']);self.assertEqual(hdr['X-Content-Type-Options'],'nosniff')
        self.assertEqual(self.req('/api/progress/'+str(rid),'PATCH',{'content':'overwrite'},True)[0],405)
        self.assertEqual(self.req('/api/progress/'+str(rid),'DELETE',admin=True)[0],405)
        self.assertEqual(self.req(f'/api/progress/{rid}/void','POST',{'reason':'誤傳'})[0],403)
        self.assertEqual(self.req(f'/api/progress/{rid}/void','POST',{'reason':''},True)[0],400)
        self.assertEqual(self.req(f'/api/progress/{rid}/remove-file','POST',{'reason':'','file_id':fid},True)[0],400)
        self.assertEqual(self.req(f'/api/progress/{rid}/void','POST',{'reason':'誤傳'},True)[0],200)
        self.assertEqual(self.create({'reporter':'甲','subject':'a','parent_id':str(rid)})[0],400)
        self.assertEqual(self.req(f'/api/progress/{rid}/void','POST',{'reason':'重複'},True)[0],409)
        self.assertEqual(self.req(f'/api/progress/{rid}/remove-file','POST',{'reason':'清除','file_id':fid},True)[0],200)
        self.assertEqual(self.req(url)[0],404)
        self.assertEqual(self.req(f'/api/progress/{rid}/audit')[0],403)
        _,audit,_=self.req(f'/api/progress/{rid}/audit',admin=True)
        self.assertEqual([x['action'] for x in audit['items']],['新增回報','作廢回報','附件移除'])
        with app.conn() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM progress_outbox WHERE detail LIKE ?',(f'%回報 #{rid}・%',)).fetchone()[0],3)
        _,filtered,_=self.req('/api/progress?status=void&reporter='+urllib.parse.quote('測試甲'))
        self.assertIn(rid,filtered['matched_ids']);self.assertNotIn(second,filtered['matched_ids'])

    def test_validation(self):
        self.assertEqual(self.create({'reporter':'  ','subject':'a'})[0],400)
        self.assertEqual(self.create({'reporter':'a','subject':''})[0],400)
        self.assertEqual(self.create({'reporter':'a','subject':'a','parent_id':'999999'})[0],400)
        self.assertEqual(self.create(files=[('virus.exe',b'MZ')])[0],400)
        self.assertEqual(self.create(files=[(str(i)+'.txt',b'a') for i in range(21)])[0],400)
        self.assertEqual(self.create(headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.req('/api/progress','POST',b'a',headers={'Content-Type':'application/json'})[0],400)

    def test_size_boundary(self):
        self.assertEqual(self.create(files=[('limit.zip',b'x'*(25*1024*1024)),('limit2.zip',b'y'*(25*1024*1024))])[0],201)
        self.assertEqual(self.create(files=[('limit.zip',b'x'*(50*1024*1024)),('extra.txt',b'y')])[0],400)

    def test_storage_rollback(self):
        with app.conn() as c: before=c.execute('SELECT count(*) FROM progress_reports').fetchone()[0]
        calls=[]
        def storage(method,key,data=None,content_type=None):
            calls.append((method,key))
            if method=='PUT': raise OSError('storage failure')
            return b'',{}
        with patch.object(app,'S3_ENABLED',True),patch.object(app,'s3_request',storage):
            self.assertEqual(self.create(files=[('test.py',b'a')])[0],503)
        with app.conn() as c: self.assertEqual(c.execute('SELECT count(*) FROM progress_reports').fetchone()[0],before)
        self.assertEqual([x[0] for x in calls],['PUT','DELETE'])

    def test_static_private_files(self):
        for path in ('/server.py','/progress.py','/.git/config','/data.db','/test_progress.py'):
            self.assertEqual(self.req(path)[0],404)
        for path in ('/','/progress.js','/progress.css','/api/tasks','/api/health'):
            self.assertEqual(self.req(path)[0],200)

    def test_notification_retry_and_mentions(self):
        from contextlib import contextmanager
        with app.conn() as c:
            c.execute('DELETE FROM progress_outbox')
        self.create({'reporter':'驗證','subject':'@everyone 通知','content':'<@1234>'})
        class StopWorker(BaseException): pass
        def stop(_): raise StopWorker()
        with patch.dict(os.environ,{'DISCORD_WEBHOOK_URL':'https://discord.invalid/test'}),patch.object(progress.urllib.request,'urlopen',side_effect=OSError('offline')),patch.object(progress.time,'sleep',stop):
            with self.assertRaises(StopWorker): progress.worker()
        with app.conn() as c:
            row=c.execute('SELECT * FROM progress_outbox').fetchone()
            self.assertEqual(row['attempts'],1);self.assertFalse(row['sent_at'])
            c.execute('UPDATE progress_outbox SET next_try=0')
        payloads=[]
        @contextmanager
        def success(req,timeout):
            payloads.append(json.loads(req.data))
            class Response: status=204
            yield Response()
        # Re-entering worker simulates restart: the unsent persisted event is delivered.
        with patch.dict(os.environ,{'DISCORD_WEBHOOK_URL':'https://discord.invalid/test'}),patch.object(progress.urllib.request,'urlopen',success),patch.object(progress.time,'sleep',stop):
            with self.assertRaises(StopWorker): progress.worker()
        self.assertEqual(payloads[0]['allowed_mentions'],{'parse':[]})
        with app.conn() as c:
            self.assertTrue(c.execute('SELECT sent_at FROM progress_outbox').fetchone()[0])

    def test_notification_controls(self):
        cfg={'enabled':False,'mode':'digest','events':list(progress.EVENTS.values())}
        self.assertEqual(self.req('/api/notifications/config','POST',cfg)[0],403)
        self.assertEqual(self.req('/api/notifications/config','POST',dict(cfg,enabled='false'),True)[0],400)
        self.assertEqual(self.req('/api/notifications/config','POST',cfg,True)[0],200)
        first=self.create()[1]['id']
        with app.conn() as c:
            self.assertFalse(c.execute('SELECT 1 FROM progress_outbox WHERE detail LIKE ?',(f'%回報 #{first}・%',)).fetchone())
            self.assertTrue(c.execute('SELECT 1 FROM progress_audit WHERE report_id=?',(first,)).fetchone())
        cfg['enabled']=True;cfg['events']=['progress_add']
        self.assertEqual(self.req('/api/notifications/config','POST',cfg,True)[0],200)
        second=self.create()[1]['id']
        third=self.create({'reporter':'甲','subject':'a','content':'接續內容','parent_id':str(second)})[1]['id']
        with app.conn() as c:
            self.assertEqual(c.execute('SELECT event FROM progress_outbox WHERE detail LIKE ?',(f'%回報 #{second}・%',)).fetchone()[0],'progress_add')
            self.assertFalse(c.execute('SELECT 1 FROM progress_outbox WHERE detail LIKE ?',(f'%回報 #{third}・%',)).fetchone())
        cfg['enabled']=False
        self.req('/api/notifications/config','POST',cfg,True)
        class StopWorker(BaseException): pass
        def stop(_): raise StopWorker()
        with patch.dict(os.environ,{'DISCORD_WEBHOOK_URL':'https://discord.invalid/test'}),patch.object(progress.urllib.request,'urlopen') as send,patch.object(progress.time,'sleep',stop):
            with self.assertRaises(StopWorker): progress.worker()
            send.assert_not_called()
        progress.init()
        _,saved,_=self.req('/api/notifications/config',admin=True)
        self.assertEqual(saved,cfg,'Restart must preserve event preferences and master switch')
        _,status,_=self.req('/api/progress/notification-status',admin=True)
        self.assertFalse(status['enabled']);self.assertIn('recent_error',status)

    def test_restore_effective(self):
        rid=self.create(files=[('restore.txt',b'restore-test')])[1]['id']
        path=f'/api/progress/{rid}/restore'
        self.assertEqual(self.req(path,'POST',{'reason':'修正誤按'})[0],403)
        self.assertEqual(self.req(path,'POST',{'reason':'修正誤按'},True)[0],409)
        self.req(f'/api/progress/{rid}/void','POST',{'reason':'誤按作廢'},True)
        self.assertEqual(self.req(path,'POST',{'reason':' '},True)[0],400)
        with app.conn() as c:
            fid=c.execute('SELECT id FROM progress_files WHERE report_id=?',(rid,)).fetchone()[0]
        self.req(f'/api/progress/{rid}/remove-file','POST',{'reason':'移除誤傳','file_id':fid},True)
        self.assertEqual(self.req(path,'POST',{'reason':'修正誤按'},True)[0],200)
        with app.conn() as c:
            self.assertEqual(c.execute('SELECT status FROM progress_reports WHERE id=?',(rid,)).fetchone()[0],'valid')
            actions=[r[0] for r in c.execute('SELECT action FROM progress_audit WHERE report_id=? ORDER BY id',(rid,))]
            self.assertEqual(actions,['新增回報','作廢回報','附件移除','恢復有效'])
            self.assertEqual(c.execute('SELECT event FROM progress_outbox WHERE detail LIKE ? ORDER BY created DESC LIMIT 1',(f'%回報 #{rid}・%',)).fetchone()[0],'progress_restore')
        self.assertEqual(self.req('/api/progress-files/'+fid)[0],404)
        self.assertEqual(self.create({'reporter':'甲','subject':'a','content':'接續內容','parent_id':str(rid)})[0],201)

    def test_backup_all_data_and_files(self):
        import io,zipfile,uuid
        self.assertEqual(self.req('/api/admin/backup','POST')[0],403)
        self.create(files=[('progress-example.py',b'print(1)')])
        os.makedirs(app.UPLOAD_DIR,exist_ok=True)
        Path(app.UPLOAD_DIR,'backup-task.txt').write_bytes(b'task')
        Path(app.UPLOAD_DIR,'backup-receipt.pdf').write_bytes(b'receipt')
        with app.conn() as c:
            c.execute("INSERT INTO attachments(id,task_id,original_name,stored_name,size,storage) VALUES('backup-task','s0','task.txt','backup-task.txt',4,'local')")
            c.execute("INSERT INTO purchase_images VALUES('backup-image','p','image.png','backup-image.png','image/png',5,'bucket','now')")
            c.execute("INSERT INTO purchase_receipts VALUES('backup-receipt','p','receipt.pdf','backup-receipt.pdf','application/pdf',7,'local','now')")
        secret=uuid.uuid4().hex
        def storage(method,key,*args):
            self.assertEqual((method,key),('GET','purchases/backup-image.png'));return b'image',{}
        try:
            with patch.dict(os.environ,{'BACKUP_TMP_DIR':self.temp.name,'AWS_SECRET_ACCESS_KEY':secret}),patch.object(app,'s3_request',storage):
                code,raw,headers=self.req('/api/admin/backup','POST',admin=True)
            self.assertEqual(code,200);self.assertEqual(headers['Content-Type'],'application/zip')
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                self.assertIsNone(z.testzip())
                manifest=json.loads(z.read('manifest.json'))
                self.assertTrue({'tasks','purchases','project_risks','progress_reports','meta','progress_audit'}<=set(manifest['tables']))
                self.assertTrue({'attachments','purchase_images','purchase_receipts','progress_files'}<=set(f['table'] for f in manifest['files']))
                for f in manifest['files']:
                    self.assertEqual(hashlib.sha256(z.read(f['archive_path'])).hexdigest(),f['sha256'])
                self.assertEqual(hashlib.sha256(z.read('database/data.sqlite3')).hexdigest(),manifest['database_sha256'])
                for name in z.namelist(): self.assertNotIn(secret.encode(),z.read(name))
                dest=Path(self.temp.name)/'restored-test.sqlite3';dest.write_bytes(z.read('database/data.sqlite3'))
                from contextlib import closing
                with closing(app.sqlite3.connect(dest)) as c:
                    self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                    self.assertTrue(c.execute('SELECT COUNT(*) FROM progress_reports').fetchone()[0])
            with app.conn() as c:
                self.assertEqual(c.execute('SELECT status FROM admin_backup_audit ORDER BY created DESC LIMIT 1').fetchone()[0],'transferred')
        finally:
            with app.conn() as c:
                c.execute("DELETE FROM attachments WHERE id='backup-task'")
                c.execute("DELETE FROM purchase_images WHERE id='backup-image'")
                c.execute("DELETE FROM purchase_receipts WHERE id='backup-receipt'")

    def test_backup_missing_file_fails_closed(self):
        rid=self.create(files=[('missing.txt',b'missing')])[1]['id']
        with app.conn() as c: key=c.execute('SELECT object_key FROM progress_files WHERE report_id=?',(rid,)).fetchone()[0]
        path=Path(app.UPLOAD_DIR)/key;path.unlink()
        try:
            with patch.dict(os.environ,{'BACKUP_TMP_DIR':self.temp.name}):
                code,data,headers=self.req('/api/admin/backup','POST',admin=True)
            self.assertEqual(code,503);self.assertIn('error',data);self.assertNotEqual(headers['Content-Type'],'application/zip')
        finally: path.write_bytes(b'missing')

    def test_backup_last_success_time(self):
        self.assertEqual(self.req('/api/admin/backup/status')[0],403)
        with app.conn() as c:
            c.execute("INSERT INTO admin_backup_audit(id,created,completed,actor,status) VALUES('status-success','2098-01-01','2098-01-01T10:00:00+08:00','test','transferred')")
            c.execute("INSERT INTO admin_backup_audit(id,created,completed,actor,status) VALUES('status-failed','2099-01-01','2099-01-01T10:00:00+08:00','test','failed')")
        try:
            code,d,_=self.req('/api/admin/backup/status',admin=True)
            self.assertEqual(code,200);self.assertEqual(d['last_backup_at'],'2098-01-01T10:00:00+08:00')
        finally:
            with app.conn() as c:c.execute("DELETE FROM admin_backup_audit WHERE id IN ('status-success','status-failed')")

if __name__=='__main__': unittest.main()

