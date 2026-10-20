import unittest,json
import test_progress as helpers
import server as app

class TaskFixTests(unittest.TestCase):
    setUpClass=classmethod(helpers.ProgressTests.setUpClass.__func__)
    tearDownClass=classmethod(helpers.ProgressTests.tearDownClass.__func__)
    req=helpers.ProgressTests.req
    create=helpers.ProgressTests.create

    def test_completion_settings(self):
        path='/api/tasks/completion-settings'
        self.assertEqual(self.req(path,'POST',{'allow_members':True})[0],403)
        self.assertEqual(self.req(path,'POST',{'allow_members':'true'},True)[0],400)
        self.assertEqual(self.req(path,'POST',{'allow_members':True},True)[0],200)
        before=self.req('/api/tasks')[1]['rev']
        self.assertEqual(self.req(path,admin=True)[1],{'allow_members':True})
        self.assertEqual(self.req('/api/tasks')[1]['rev'],before)
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'done':True})[0],200)
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'note':'unauthorized'})[0],403)
        self.assertEqual(self.req(path,'POST',{'allow_members':False},True)[0],200)
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'done':False})[0],403)

    def test_long_goals_no_silent_truncation(self):
        goal='測'*10000
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'note':goal},True)[0],200)
        self.assertEqual(self.req('/api/tasks/s0','PATCH',{'note':goal+'超'},True)[0],400)
        task=next(t for t in self.req('/api/tasks')[1]['tasks'] if t['id']=='s0')
        self.assertEqual(task['note'],goal)
        self.assertEqual(self.req('/api/tasks','POST',{'task':'new','note':goal},True)[0],200)
        before=self.req('/api/tasks')[1]['tasks']
        self.assertEqual(self.req('/api/import','POST',{'mode':'replace','tasks':[{'task':'valid'},{'task':'bad','note':goal+'超'}]},True)[0],400)
        self.assertEqual(self.req('/api/tasks')[1]['tasks'],before)
        self.assertEqual(self.req('/api/import','POST',{'mode':'merge','tasks':[{'task':'imported','note':goal}]},True)[0],200)

    def test_report_mutations_invalidate_task_poll(self):
        def mutate(path,data):
            rev=self.req('/api/tasks')[1]['rev']
            code,d,_=self.req(path,'POST',data,True)
            self.assertEqual(code,200,(path,d))
            polled=self.req('/api/tasks?since='+str(rev))[1]
            self.assertIn('tasks',polled);return polled
        rev=self.req('/api/tasks')[1]['rev']
        rid=self.create({'reporter':'甲','subject':'linked','content':'latest','task_id':'s0'})[1]['id']
        self.assertIn('tasks',self.req('/api/tasks?since='+str(rev))[1])
        d=mutate(f'/api/progress/{rid}/trash',{'reason':'trash'})
        self.assertEqual(next(t for t in d['tasks'] if t['id']=='s0')['report_count'],0)
        d=mutate(f'/api/progress/{rid}/untrash',{'reason':'restore'})
        self.assertEqual(next(t for t in d['tasks'] if t['id']=='s0')['latest_report']['content'],'latest')
        d=mutate(f'/api/progress/{rid}/relink',{'reason':'correct','task_id':'s1'})
        self.assertEqual(next(t for t in d['tasks'] if t['id']=='s0')['report_count'],0)
        self.assertEqual(next(t for t in d['tasks'] if t['id']=='s1')['report_count'],1)
        mutate(f'/api/progress/{rid}/void',{'reason':'void'})
        mutate(f'/api/progress/{rid}/restore',{'reason':'restore'})

if __name__=='__main__':unittest.main()
