"""PDF timestamp formatting regression checks; no network or live data."""
import unittest
from unittest.mock import patch
import progress_export as export


class ExportTimeTests(unittest.TestCase):
    def test_timezone_and_precision(self):
        self.assertEqual(export.display_time('2026-10-19T18:43:56.668071+08:00'),'2026/10/19 18:43:56')
        self.assertEqual(export.display_time('2026-10-19T20:43:56.668071Z'),'2026/10/20 04:43:56')
        self.assertEqual(export.display_time('2026-10-19T18:43:56'),'2026/10/19 18:43:56')
        self.assertEqual(export.display_time(''),'時間未提供')
        self.assertEqual(export.display_time('legacy unknown'),'legacy unknown')

    def test_pdf_report_and_audit_dates_are_readable(self):
        row={'id':1,'subject':'時間格式驗證','reporter':'測試','created':'2026-10-19T18:43:56.668071+08:00','task_name':'','status':'valid','parent_id':None,'content':'測試內容','version':1,'files':[]}
        audit={1:[{'created':'2026-10-19T19:07:46.631620+08:00','action':'作廢回報','reason':'測試'}]}
        texts=[]
        original=export.Paragraph
        def capture(text,style):
            texts.append(text);return original(text,style)
        with patch.object(export,'Paragraph',side_effect=capture):
            pdf=export.pdf_report([row],audit,'2026/10/19 23:38:16')
        self.assertTrue(pdf.startswith(b'%PDF-'));self.assertIn(b'%%EOF',pdf)
        self.assertIn('時間均為台灣時間（UTC+8）',texts)
        self.assertIn('回報時間：2026/10/19 18:43:56',texts)
        self.assertIn('操作紀錄：2026/10/19 19:07:46／作廢回報／測試',texts)


if __name__=='__main__':unittest.main()
