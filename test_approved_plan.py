import unittest,json,os,tempfile
from pathlib import Path
from unittest.mock import patch
import test_progress as helpers
import server as app,purchase_safety as safety

class ApprovedPlanTests(unittest.TestCase):
    setUpClass=classmethod(helpers.ProgressTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.ProgressTests.tearDownClass.__func__)
    req=helpers.ProgressTests.req

    def setUp(self):
        with app.conn() as c:
            for table in ['purchase_images','purchase_receipts','purchases','purchase_cleanup','purchase_delete_audit','notify_queue','task_time_audit']:
                c.execute('DELETE FROM '+table)
            c.execute("UPDATE tasks SET done=0,done_date='' WHERE id='s0'")
            c.execute("INSERT OR REPLACE INTO meta VALUES('notify_config',?)",(json.dumps({'enabled':True,'mode':'instant','events':['task_done','task_reopen']}),))
    def purchase(self):
        code,d,_=self.req('/api/purchases','POST',{'name':'audit','qty':1,'price':10,'spec':'規'*10000,'note':'備'*10000})
        self.assertEqual(code,200)
        return next(p for p in d['purchases'] if p['name']=='audit')
    def task(self):return next(t for t in self.req('/api/tasks')[1]['tasks'] if t['id']=='s0')

    def test_completion_date_bidirectional_and_notifications(self):
        path='/api/tasks/s0'
        self.assertEqual(self.req(path,'PATCH',{'done_date':'2026-10-20T12:34'},True)[0],200)
        self.assertEqual((self.task()['done'],self.task()['done_date']),(True,'2026-10-20 12:34'))
        self.req(path,'PATCH',{'done_date':'2026-10-20T13:45'},True)
        self.assertTrue(self.task()['done'])
        with app.conn() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM notify_queue').fetchone()[0],1)
        self.req(path,'PATCH',{'done':False},True)
        self.assertEqual((self.task()['done'],self.task()['done_date']),(False,''))
        self.req(path,'PATCH',{'done':True},True)
        self.assertTrue(self.task()['done_date'])
        self.req(path,'PATCH',{'done_date':''},True)
        self.assertFalse(self.task()['done'])
        with app.conn() as c:
            self.assertEqual([r['event'] for r in c.execute('SELECT event FROM notify_queue ORDER BY created')],['task_done','task_reopen','task_done','task_reopen'])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM task_time_audit').fetchone()[0],5)
        self.assertEqual(self.req(path,'PATCH',{'done_date':'2026-99-99T99:99'},True)[0],400)
        self.assertEqual(self.req(path,'PATCH',{'done':'false'},True)[0],400)
        self.assertEqual(self.req(path,'PATCH',{'done_date':'2026-10-20T13:00'})[0],403)

    def test_purchase_revision_partial_patch_and_permissions(self):
        p=self.purchase();path='/api/purchases/'+p['id']
        self.assertEqual(self.req(path,'PATCH',{'qty':2,'revision':p['revision']})[0],200)
        code,conflict,_=self.req(path,'PATCH',{'note':'new','revision':p['revision']})
        self.assertEqual(code,409);self.assertEqual(conflict['current']['qty'],2)
        latest=conflict['current']
        self.assertEqual(self.req(path,'PATCH',{'note':'new','revision':latest['revision']})[0],200)
        current=next(x for x in self.req('/api/purchases')[1]['purchases'] if x['id']==p['id'])
        self.assertEqual(current['qty'],2);self.assertEqual(current['note'],'new');self.assertEqual(len(current['spec']),10000)
        self.assertEqual(self.req(path,'PATCH',{'note':'x'*10001,'revision':current['revision']})[0],400)
        self.assertEqual(self.req(path,'PATCH',{'owner':'unauthorized','revision':current['revision']})[0],403)
        self.assertEqual(self.req(path,'PATCH',{'qty':3})[0],409)

    def test_durable_delete_with_failure_restart_and_backup_inventory(self):
        p=self.purchase();pid=p['id'];path='/api/purchases/'+pid
        with app.conn() as c:
            for i in ['1','2']:
                c.execute('INSERT INTO purchase_images VALUES(?,?,?,?,?,?,?,?)',(i*32,pid,i+'.png',i+'.png','image/png',1,'bucket','now'))
        self.assertEqual(self.req(path,'DELETE',{'revision':p['revision']})[0],403)
        self.assertEqual(self.req(path,'DELETE',{'revision':0},True)[0],409)
        self.assertEqual(self.req(path,'DELETE',{'revision':p['revision']},True)[0],202)
        self.assertFalse(any(x['id']==pid for x in self.req('/api/purchases')[1]['purchases']))
        self.assertTrue(next(x for x in self.req('/api/purchases',admin=True)[1]['purchases'] if x['id']==pid)['deleting'])
        with app.conn() as c:
            files,removed=app.backup.inventory(c)
            self.assertFalse(any(f['table']=='purchase_images' for f in files));self.assertEqual(len(removed),2)
        deleted=[]
        def storage(method,key,*args):
            if key.endswith('2.png'):raise OSError('offline')
            deleted.append(key);return b'',{}
        with patch.object(app,'s3_request',side_effect=storage):safety.retry_cleanup()
        with app.conn() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM purchase_cleanup WHERE completed='' ").fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM purchase_images').fetchone()[0],1)
        self.assertEqual(self.req('/api/purchase-images/'+'2'*32)[0],404)
        self.assertEqual(self.req('/api/purchases/cleanup-status')[0],403)
        self.assertTrue(self.req('/api/purchases/cleanup-status',admin=True)[1]['jobs'])
        app.init()
        with app.conn() as c:c.execute('UPDATE purchase_cleanup SET next_try=0')
        with patch.object(app,'s3_request',return_value=(b'',{})) as send:
            safety.retry_cleanup();send.assert_called_once_with('DELETE','purchases/2.png')
            safety.retry_cleanup();send.assert_called_once()
        with app.conn() as c:
            self.assertFalse(c.execute('SELECT 1 FROM purchases WHERE id=?',(pid,)).fetchone())
            self.assertTrue(c.execute('SELECT completed FROM purchase_delete_audit WHERE purchase_id=?',(pid,)).fetchone()[0])

    def test_single_receipt_cleanup_and_late_upload_intention(self):
        p=self.purchase();fid='a'*32
        with app.conn() as c:c.execute('INSERT INTO purchase_receipts VALUES(?,?,?,?,?,?,?,?)',(fid,p['id'],'receipt.pdf','gone.pdf','application/pdf',1,'local','now'))
        self.assertEqual(self.req('/api/purchase-receipts/'+fid,'DELETE',{'revision':p['revision']},True)[0],202)
        self.assertEqual(self.req('/api/purchase-receipts/'+fid,admin=True)[0],404)
        safety.retry_cleanup()
        with app.conn() as c:
            self.assertTrue(c.execute('SELECT 1 FROM purchases WHERE id=?',(p['id'],)).fetchone())
            safety.queue_file(c,'purchase_images',dict(id='b'*32,purchase_id='already-gone',original_name='late.png',stored_name='late.png',storage='bucket'))
        with patch.object(app,'s3_request',return_value=(b'',{})) as send:
            safety.retry_cleanup();send.assert_called_once_with('DELETE','purchases/late.png')

if __name__=='__main__':unittest.main()
