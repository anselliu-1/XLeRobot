import io,json,os,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import server as app
import backup,restore_backup
import test_progress as helpers

class ReviewFeatures(unittest.TestCase):
    setUpClass=classmethod(helpers.ProgressTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.ProgressTests.tearDownClass.__func__)
    req=helpers.ProgressTests.req
    create=helpers.ProgressTests.create
    def setUp(self):
        temp_patch=patch.object(tempfile,'tempdir',self.temp.name);temp_patch.start();self.addCleanup(temp_patch.stop)
    def tearDown(self):
        import shutil
        for s in restore_backup.SESSIONS.values():shutil.rmtree(s['folder'],ignore_errors=True)
        restore_backup.SESSIONS.clear()
    def test_preview_security_and_range(self):
        code,d,_=self.create(files=[('photo.png',b'\x89PNG\r\n\x1a\n'+b'image'),('script.py',b'<script>alert(1)</script>'),('fake.png',b'<html>oops</html>'),('movie.mp4',b'0000ftypisom'+b'video')])
        self.assertEqual(code,201)
        rows=self.req('/api/progress')[1]['items'];r=next(r for r in rows if r['id']==d['id'])
        byname={f['name']:f for f in r['files']}
        for name,kind in [('photo.png','image/png'),('script.py','text/plain'),('movie.mp4','video/mp4')]:
            code,body,headers=self.req(byname[name]['url']+'/preview')
            self.assertEqual(code,200);self.assertIn(kind,headers['Content-Type']);self.assertIn('sandbox',headers['Content-Security-Policy'])
        self.assertEqual(self.req(byname['fake.png']['url']+'/preview')[0],415)
        code,body,headers=self.req(byname['movie.mp4']['url']+'/preview',headers={'Range':'bytes=4-7'})
        self.assertEqual((code,body),(206,b'ftyp'));self.assertEqual(headers['Content-Range'],'bytes 4-7/17')
        self.assertIn('attachment',self.req(byname['photo.png']['url'])[2]['Content-Disposition'])
        self.req('/api/progress/'+str(d['id'])+'/trash','POST',{'reason':'test'},True)
        self.assertEqual(self.req(byname['photo.png']['url']+'/preview')[0],404)
    def test_admin_ids_independent(self):
        self.assertEqual(self.req('/api/progress/settings','POST',{'admin_show_report_ids':False})[0],403)
        self.assertEqual(self.req('/api/progress/settings','POST',{'admin_show_report_ids':False,'show_report_ids':True},True)[0],200)
        self.assertFalse(self.req('/api/progress',admin=True)[1]['admin_show_report_ids'])
        self.assertTrue(self.req('/api/progress')[1]['show_report_ids'])
        self.assertEqual(self.req('/api/progress/settings','POST',{'admin_show_report_ids':'yes'},True)[0],400)
    def archive(self):
        with tempfile.TemporaryDirectory() as folder:
            path,_=backup.build(folder);return path.read_bytes()
    def preview(self,raw):
        return self.req('/api/admin/restore/preview','POST',raw,True,{'Content-Type':'application/zip'})
    def test_restore_auth_and_no_production(self):
        self.assertEqual(self.req('/api/admin/restore/preview','POST',b'zip')[0],403)
        with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_NAME':'production'}):self.assertEqual(self.preview(b'zip')[0],403)
    def test_older_v1_schema_is_migrated_without_archived_code(self):
        import sqlite3,hashlib
        raw=self.archive()
        with tempfile.TemporaryDirectory(dir=self.temp.name) as folder,zipfile.ZipFile(io.BytesIO(raw)) as source:
            db=Path(folder)/'old.db';db.write_bytes(source.read('database/data.sqlite3'))
            with sqlite3.connect(db) as c:
                c.execute('DROP TABLE purchase_cleanup');c.execute('DROP TABLE purchase_delete_audit')
                c.execute('ALTER TABLE purchases DROP COLUMN revision')
            c.close()
            data=db.read_bytes();manifest=json.loads(source.read('manifest.json'));manifest['database_sha256']=hashlib.sha256(data).hexdigest()
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w') as z:
                for info in source.infolist():
                    z.writestr(info,data if info.filename=='database/data.sqlite3' else json.dumps(manifest).encode() if info.filename=='manifest.json' else source.read(info.filename))
            with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_NAME':'staging'}):
                code,d,_=self.preview(output.getvalue());self.assertEqual(code,200,d)
    def test_restore_validate_cancel_tamper_and_conflict(self):
        raw=self.archive()
        with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_NAME':'staging'}):
            code,d,_=self.preview(raw);self.assertEqual(code,200,d)
            self.assertEqual(self.req('/api/admin/restore/apply','POST',{'token':d['token'],'confirm':'wrong','reason':'test'},True)[0],400)
            self.req('/api/tasks/s0','PATCH',{'note':'changed after preview'},True)
            code,result,_=self.req('/api/admin/restore/apply','POST',{'token':d['token'],'confirm':'還原測試站','reason':'test'},True)
            self.assertEqual(code,400);self.assertIn('已變更',result['error'])
            self.assertEqual(self.req('/api/admin/restore/cancel','POST',{'token':d['token']},True)[0],200)
            with zipfile.ZipFile(io.BytesIO(raw)) as source:
                out=io.BytesIO()
                with zipfile.ZipFile(out,'w') as z:
                    for item in source.infolist():z.writestr(item,source.read(item.filename))
                    z.writestr('../escape.txt',b'bad')
            self.assertEqual(self.preview(out.getvalue())[0],400)
    def test_local_restore_transaction_and_safety_copy(self):
        code,report,_=self.create({'reporter':'local','subject':'restore fixture','content':'original'},[('restore.txt',b'restore fixture')])
        self.assertEqual(code,201);raw=self.archive()
        code,new,_=self.create({'reporter':'local','subject':'after backup','content':'will disappear in disposable database'})
        with patch.dict(os.environ,{'RAILWAY_ENVIRONMENT_NAME':'staging'}):
            code,preview,_=self.preview(raw);self.assertEqual(code,200,preview)
            code,d,_=self.req('/api/admin/restore/apply','POST',{'token':preview['token'],'confirm':'還原測試站','reason':'isolated local test'},True)
            self.assertEqual(code,200,d)
            with app.conn() as c:
                self.assertFalse(c.execute('SELECT 1 FROM progress_reports WHERE id=?',(new['id'],)).fetchone())
                self.assertFalse(app.notify_config(c)['enabled'])
                file=c.execute('SELECT * FROM progress_files WHERE report_id=?',(report['id'],)).fetchone()
                self.assertIn('restored',file['object_key']);self.assertEqual((Path(app.UPLOAD_DIR)/file['object_key']).read_bytes(),b'restore fixture')
            code,safety,_=self.req('/api/admin/restore/safety/'+d['safety_id'],admin=True)
            self.assertEqual(code,200);self.assertTrue(zipfile.is_zipfile(io.BytesIO(safety)))
