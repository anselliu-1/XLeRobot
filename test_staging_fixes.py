"""Regression checks using disposable SQLite/storage, never live services."""
import io, json, os, zipfile, unittest
from pathlib import Path
from unittest.mock import patch
import test_progress as helpers
import server as app
import progress, progress_export


class StagingFixTests(unittest.TestCase):
    setUpClass=classmethod(helpers.ProgressTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.ProgressTests.tearDownClass.__func__)
    req=helpers.ProgressTests.req
    create=helpers.ProgressTests.create

    def setUp(self):
        with app.conn() as c:
            for table in ('progress_files','progress_reports','progress_audit','progress_deleted_audit','progress_cleanup','progress_outbox','notify_queue','purchase_receipts'):
                c.execute('DELETE FROM '+table)
            c.execute("INSERT OR REPLACE INTO meta VALUES('notify_config',?)",(json.dumps({'enabled':False,'mode':'instant','events':[]}),))
            for key in ('progress_export_all','progress_audit_all'):
                c.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,'0'))

    def test_trash_excluded_from_task_summary_and_download(self):
        fields={'reporter':'甲','subject':'摘要','content':'公開','task_id':'s0'}
        rid=self.create(fields)[1]['id']
        hidden=self.create(dict(fields,content='垃圾桶內容'),[('secret.txt',b'secret')])[1]['id']
        with app.conn() as c:fid=c.execute('SELECT id FROM progress_files WHERE report_id=?',(hidden,)).fetchone()[0]
        self.assertEqual(self.req(f'/api/progress/{hidden}/trash','POST',{'reason':'誤植'},True)[0],200)
        code,d,_=self.req('/api/tasks')
        task=next(t for t in d['tasks'] if t['id']=='s0')
        self.assertEqual(task['report_count'],1)
        self.assertEqual(task['latest_report']['content'],'公開')
        self.assertEqual(self.req('/api/progress-files/'+fid)[0],404)
        self.assertEqual(self.req(f'/api/progress/{hidden}/untrash','POST',{'reason':'還原'},True)[0],200)
        self.assertEqual(self.req('/api/progress-files/'+fid)[0],200)

    def test_actual_continuation_source_even_when_parent_in_trash(self):
        rid=self.create()[1]['id']
        fields={'reporter':'乙','subject':'ignored','content':'分支','parent_id':str(rid)}
        self.create(fields)
        third=self.create(fields)[1]['id']
        self.req(f'/api/progress/{rid}/trash','POST',{'reason':'隱藏'},True)
        _,d,_=self.req('/api/progress')
        r=next(r for r in d['items'] if r['id']==third)
        self.assertEqual((r['version'],r['parent_id'],r['parent_version']),(3,rid,1))

    def test_exports_pdf_zip_permissions_and_trash(self):
        rid=self.create(files=[('code.py',b'print(1)')])[1]['id']
        hidden=self.create({'reporter':'乙','subject':'垃圾桶','content':'hidden'})[1]['id']
        self.req(f'/api/progress/{hidden}/trash','POST',{'reason':'隱藏'},True)
        self.assertEqual(self.req('/api/progress/export','POST',{'format':'pdf'})[0],403)
        with app.conn() as c:c.execute("INSERT OR REPLACE INTO meta VALUES('progress_export_all','1')")
        original=progress_export.pdf_report
        captured=[]
        def capture(rows,audit,generated):
            captured.append((rows,audit));return original(rows,audit,generated)
        with patch.object(progress_export,'pdf_report',side_effect=capture):
            code,pdf,_=self.req('/api/progress/export','POST',{'format':'pdf'})
            self.assertEqual(code,200);self.assertTrue(pdf.startswith(b'%PDF-'));self.assertIn(b'%%EOF',pdf)
            self.assertEqual([r['id'] for r in captured[-1][0]],[rid])
            self.assertFalse(any(captured[-1][1].values()))
            code,data,_=self.req('/api/progress/export','POST',{'format':'zip'},True)
            self.assertEqual(code,200);self.assertTrue(any(captured[-1][1].values()))
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(sum(n.endswith('.py') for n in z.namelist()),1)
                self.assertEqual(z.read(next(n for n in z.namelist() if n.endswith('.py'))),b'print(1)')
            with app.conn() as c:c.execute("INSERT OR REPLACE INTO meta VALUES('progress_audit_all','1')")
            self.assertEqual(self.req('/api/progress/export','POST',{'scope':'single','report_id':rid,'format':'pdf'})[0],200)
            self.assertTrue(any(captured[-1][1].values()))
        self.assertEqual(self.req('/api/progress/export','POST',{'format':'pdf'},True,{'Origin':'https://evil.example'})[0],403)

    def test_receipts_still_require_verified_header(self):
        fid='a'*32
        Path(app.UPLOAD_DIR).mkdir(parents=True,exist_ok=True)
        Path(app.UPLOAD_DIR,'receipt.pdf').write_bytes(b'%PDF-receipt')
        with app.conn() as c:c.execute('INSERT INTO purchase_receipts VALUES(?,?,?,?,?,?,?,?)',(fid,'p','receipt.pdf','receipt.pdf','application/pdf',12,'local','now'))
        self.assertEqual(self.req('/api/purchase-receipts/'+fid)[0],403)
        self.assertEqual(self.req('/api/purchase-receipts/'+fid,headers={'X-Admin-Key':'wrong'})[0],403)
        code,data,hdr=self.req('/api/purchase-receipts/'+fid,admin=True)
        self.assertEqual((code,data),(200,b'%PDF-receipt'))
        self.assertEqual(hdr['Cache-Control'],'no-store')
        self.assertEqual(self.req('/admin-files.js')[0],200)

    def test_export_timestamps_in_taiwan_time_without_microseconds(self):
        self.assertEqual(progress_export.display_time('2026-10-19T18:43:56.668071+08:00'),'2026/10/19 18:43:56')
        self.assertEqual(progress_export.display_time('2026-10-19T20:43:56.668071Z'),'2026/10/20 04:43:56')
        self.assertEqual(progress_export.display_time('2026-10-19T18:43:56'),'2026/10/19 18:43:56')
        self.assertEqual(progress_export.display_time(''),'時間未提供')
        self.assertEqual(progress_export.display_time('legacy unknown'),'legacy unknown')
        rid=self.create()[1]['id']
        paragraphs=[]
        original=progress_export.Paragraph
        def capture(text,style):
            paragraphs.append(text);return original(text,style)
        with patch.object(progress_export,'Paragraph',side_effect=capture):
            code,pdf,_=self.req('/api/progress/export','POST',{'format':'pdf'},True)
        self.assertEqual(code,200);self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertIn('時間均為台灣時間（UTC+8）',paragraphs)
        dates=[t for t in paragraphs if t.startswith(('回報時間：','操作紀錄：'))]
        self.assertTrue(dates)
        for text in dates:
            self.assertNotIn('T',text);self.assertNotIn('+08:00',text)

    def test_task_completion_uses_completion_events_not_edit_event(self):
        # Only completion/reopen are selected; content edits must not be required.
        with app.conn() as c:
            c.execute("UPDATE tasks SET done=0,done_date='' WHERE id='s0'")
            c.execute("INSERT OR REPLACE INTO meta VALUES('notify_config',?)",(json.dumps({'enabled':True,'mode':'instant','events':['task_done','task_reopen']}),))
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'done':True},True)[0],200)
        with app.conn() as c:
            self.assertEqual([r['event'] for r in c.execute('SELECT event FROM notify_queue ORDER BY created')],['task_done'])
        # An unchanged checkbox must not send a second completion notification.
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'done':True},True)[0],200)
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'done':False},True)[0],200)
        with app.conn() as c:
            self.assertEqual([r['event'] for r in c.execute('SELECT event FROM notify_queue ORDER BY created')],['task_done','task_reopen'])
            c.execute("DELETE FROM notify_queue")
            c.execute("INSERT OR REPLACE INTO meta VALUES('notify_config',?)",(json.dumps({'enabled':True,'mode':'instant','events':['task_edit']}),))
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'done':True},True)[0],200)
        with app.conn() as c:self.assertFalse(c.execute('SELECT 1 FROM notify_queue').fetchone())
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'note':'ordinary edit'},True)[0],200)
        with app.conn() as c:self.assertEqual(c.execute('SELECT event FROM notify_queue').fetchone()[0],'task_edit')

    def test_notification_queue_survives_restart_and_respects_controls(self):
        cfg={'enabled':True,'mode':'instant','events':['buy_add']}
        with app.conn() as c:
            for ident,event,created in [('before','buy_add',100),('future','buy_add',2000),('disabled','task_add',100)]:
                c.execute('INSERT INTO notify_queue(id,event,subject,detail,created,sent) VALUES(?,?,?,?,?,0)',(ident,event,'test','test',created))
        app.init();progress.init()
        with app.conn() as c:
            self.assertEqual([r['id'] for r in app.pending_notifications(c,cfg,1000)],['before'])
            self.assertEqual(app.pending_notifications(c,dict(cfg,enabled=False),1000),[])
            self.assertEqual(app.pending_notifications(c,dict(cfg,mode='digest'),650),[])
            self.assertEqual([r['id'] for r in app.pending_notifications(c,dict(cfg,mode='digest'),701)],['before'])
        class Stop(BaseException):pass
        def stop(_):raise Stop()
        with app.conn() as c:c.execute("INSERT OR REPLACE INTO meta VALUES('notify_config',?)",(json.dumps(cfg),))
        response=unittest.mock.MagicMock();response.__enter__.return_value.status=204
        with patch.dict(os.environ,{'DISCORD_WEBHOOK_URL':'https://discord.invalid/test'}),patch.object(app.urllib.request,'urlopen',return_value=response) as send,patch.object(app.time,'time',return_value=1000),patch.object(app.time,'sleep',side_effect=stop):
            with self.assertRaises(Stop):app.mail_worker()
            self.assertEqual(json.loads(send.call_args[0][0].data)['allowed_mentions'],{'parse':[]})
        with app.conn() as c:self.assertEqual(c.execute("SELECT sent FROM notify_queue WHERE id='before'").fetchone()[0],1)

    def test_permanent_delete_retains_retry_after_s3_failure_and_restart(self):
        rid=self.create(files=[('cleanup.txt',b'cleanup')])[1]['id']
        with app.conn() as c:
            f=dict(c.execute('SELECT * FROM progress_files WHERE report_id=?',(rid,)).fetchone())
            c.execute("UPDATE progress_files SET storage='bucket' WHERE id=?",(f['id'],))
        self.req(f'/api/progress/{rid}/trash','POST',{'reason':'誤植'},True)
        path=f'/api/progress/{rid}/delete'
        self.assertEqual(self.req(path,'POST',{'reason':'刪除'})[0],403)
        with patch.object(app,'s3_request',side_effect=OSError('offline')):
            code,d,_=self.req(path,'POST',{'reason':'刪除'},True)
            self.assertEqual(code,200);self.assertTrue(d['warning'])
        with app.conn() as c:
            job=dict(c.execute('SELECT * FROM progress_cleanup WHERE id=?',(f['id'],)).fetchone())
            self.assertEqual(job['object_key'],f['object_key']);self.assertEqual(job['attempts'],1)
            self.assertFalse(c.execute('SELECT 1 FROM progress_reports WHERE id=?',(rid,)).fetchone())
            self.assertTrue(c.execute('SELECT 1 FROM progress_deleted_audit WHERE report_id=?',(rid,)).fetchone())
            c.execute('UPDATE progress_cleanup SET next_try=0')
        progress.init()
        with patch.object(app,'s3_request',return_value=(b'',{})) as delete:
            progress.retry_cleanup();delete.assert_called_once_with('DELETE',f['object_key'])
            progress.retry_cleanup();delete.assert_called_once()
        with app.conn() as c:self.assertTrue(c.execute('SELECT completed FROM progress_cleanup WHERE id=?',(f['id'],)).fetchone()[0])

    def test_task_notification_failure_keeps_queue_and_error(self):
        cfg={'enabled':True,'mode':'instant','events':['task_done']}
        with app.conn() as c:
            c.execute("INSERT OR REPLACE INTO meta VALUES('notify_config',?)",(json.dumps(cfg),))
            c.execute("INSERT INTO notify_queue(id,event,subject,detail,created,sent) VALUES('retry','task_done','test','test',100,0)")
        class Stop(BaseException):pass
        def stop(_):raise Stop()
        error=app.urllib.error.HTTPError('https://discord.invalid/test',429,'rate limited',{},None)
        with patch.dict(os.environ,{'DISCORD_WEBHOOK_URL':'https://discord.invalid/test'}),patch.object(app.urllib.request,'urlopen',side_effect=error),patch.object(app.time,'sleep',side_effect=stop):
            with self.assertRaises(Stop):app.mail_worker()
        with app.conn() as c:
            row=c.execute("SELECT sent,error FROM notify_queue WHERE id='retry'").fetchone()
            self.assertEqual((row['sent'],row['error']),(0,'HTTP 429'))

if __name__=='__main__':unittest.main()
