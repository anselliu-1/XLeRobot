import json,os,unittest,uuid
from unittest.mock import patch
import server as app
import progress
import test_progress as helpers

class NotificationPolish(unittest.TestCase):
    setUpClass=classmethod(helpers.ProgressTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.ProgressTests.tearDownClass.__func__)
    req=helpers.ProgressTests.req
    create=helpers.ProgressTests.create
    setUp=helpers.ProgressTests.setUp
    def test_independent_notification_setting(self):
        self.assertTrue(self.req('/api/progress',admin=True)[1]['notify_show_report_ids'])
        self.assertEqual(self.req('/api/progress/settings','POST',{'notify_show_report_ids':False})[0],403)
        self.assertEqual(self.req('/api/progress/settings','POST',{'notify_show_report_ids':False},True)[0],200)
        d=self.req('/api/progress',admin=True)[1]
        self.assertFalse(d['notify_show_report_ids']);self.assertTrue(d['admin_show_report_ids'])
        self.assertEqual(self.req('/api/progress/settings','POST',{'notify_show_report_ids':'false'},True)[0],400)
        self.req('/api/progress/settings','POST',{'notify_show_report_ids':True},True)
    def test_all_events_have_human_version_and_time(self):
        _,r,_=self.create()
        with app.conn() as c:
            for action in progress.EVENTS:
                progress.event(c,r['id'],action,'local fixture','reason')
                detail=c.execute('SELECT detail FROM progress_outbox ORDER BY rowid DESC LIMIT 1').fetchone()[0]
                self.assertIn('第 1 次回報',detail);self.assertNotIn('・v1',detail)
                self.assertRegex(detail,r'時間：[0-9]{4}/[0-9]{2}/[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}')
    def test_legacy_pending_notification_is_formatted_at_delivery(self):
        legacy='接續回報｜回報 #10・v2\nsubject\n回報人：fixture\n時間：2026-10-20T21:51:08.253843+08:00\nbody'
        self.assertIn('回報 #10｜第 2 次回報',progress.notification_detail(legacy,True))
        hidden=progress.notification_detail(legacy,False)
        self.assertNotIn('#10',hidden);self.assertIn('第 2 次回報',hidden)
        self.assertIn('時間：2026/10/20 21:51:08',hidden)
        sent=[]
        with app.conn() as c:
            c.execute('DELETE FROM progress_outbox')
            c.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('progress_notify_show_ids','0')")
            c.execute('INSERT INTO progress_outbox(id,detail,created,event) VALUES(?,?,?,?)',(uuid.uuid4().hex,legacy,progress.stamp(),'progress_continue'))
        class Response:
            status=204
            def __enter__(self):return self
            def __exit__(self,*args):pass
        def deliver(request,**kwargs):sent.append(json.loads(request.data));return Response()
        with patch.dict(os.environ,{'DISCORD_WEBHOOK_URL':'https://example.invalid/test-only'}),patch('urllib.request.urlopen',side_effect=deliver),patch.object(progress.time,'sleep',side_effect=StopIteration):
            with self.assertRaises(StopIteration):progress.worker()
        self.assertEqual(len(sent),1);self.assertIn('第 2 次回報',sent[0]['content']);self.assertNotIn('#10',sent[0]['content'])
        self.assertEqual(sent[0]['allowed_mentions'],{'parse':[]})
