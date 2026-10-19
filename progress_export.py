"""Progress export: PDF report and original attachments in ZIP, with server-side permissions."""
import io, os, re, json, zipfile
from xml.sax.saxutils import escape
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

def pdf_report(rows, audit, generated):
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    out=io.BytesIO()
    doc=SimpleDocTemplate(out,pagesize=(595,842),leftMargin=42,rightMargin=42,topMargin=42,bottomMargin=42)
    title=ParagraphStyle('xle-title',fontName='STSong-Light',fontSize=17,leading=25,spaceAfter=12)
    heading=ParagraphStyle('xle-heading',fontName='STSong-Light',fontSize=12,leading=20,spaceBefore=14,spaceAfter=7,textColor=colors.HexColor('#12394a'))
    body=ParagraphStyle('xle-body',fontName='STSong-Light',fontSize=10,leading=17,spaceAfter=5,wordWrap='CJK')
    def line(text):return Paragraph(escape(str(text or '')).replace('\n','<br/>'),body)
    story=[Paragraph('XLeRobot 進度回報彙整',title),line('匯出時間：'+generated),line('回報筆數：'+str(len(rows)))]
    for r in rows:
        story.append(Paragraph(escape(r['subject'])+' · 第 '+str(r['version'])+' 次回報',heading))
        for label,value in [('回報編號',r['id']),('回報人',r['reporter']),('回報時間',r['created']),('關聯工作',r['task_name'] or '未關聯'),('狀態','已作廢' if r['status']=='void' else '有效'),('接續來源',r['parent_id'] or '無'),('回報內容',r['content'])]:
            story.append(line(label+'：'+str(value)))
        files=r['files']
        story.append(line('附件：'+('、'.join(f['name']+('（已移除：'+f['reason']+'）' if f['removed_at'] else '') for f in files) if files else '無')))
        for a in audit.get(r['id'],[]):
            story.append(line('操作紀錄：'+a['created']+'／'+a['action']+'／'+a['reason']))
        story.append(Spacer(1,8))
    doc.build(story)
    return out.getvalue()

def export(h):
    A=__import__('progress').A
    if h.command!='POST':return h._send(405,{'error':'只接受 POST'})
    origin=h.headers.get('Origin')
    if origin and __import__('urllib.parse',fromlist=['urlsplit']).urlsplit(origin).netloc!=h.headers.get('Host'):
        return h._send(403,{'error':'不允許跨網站操作'})
    with A.LOCK,A.conn() as c:
        allow=(c.execute("SELECT v FROM meta WHERE k='progress_export_all'").fetchone() or {'v':'0'})['v']=='1'
        if not allow and not A.is_admin(h):return h._send(403,{'error':'目前僅管理員可匯出進度回報'})
    try:
        d=h._body()
        if not isinstance(d,dict):raise ValueError('格式錯誤')
        scope=d.get('scope','all');fmt=d.get('format','zip')
        if scope not in ('all','filtered','task','single') or fmt not in ('zip','pdf'):raise ValueError('匯出範圍或格式錯誤')
        rid=int(d.get('report_id') or 0);task_id=str(d.get('task_id') or '')
        if scope=='single' and rid<1:raise ValueError('請選擇回報')
        if scope=='task' and not task_id:raise ValueError('請選擇工作主題')
        ids=d.get('ids',[])
        if scope=='filtered' and (not isinstance(ids,list) or len(ids)>10000 or any(type(i)!=int for i in ids)):
            raise ValueError('篩選清單無效')
        with A.LOCK,A.conn() as c:
            allrows=[dict(r) for r in c.execute('SELECT * FROM progress_reports WHERE status!='trash' ORDER BY root_id,version,id')]
            if scope=='single':rows=[r for r in allrows if r['id']==rid]
            elif scope=='task':rows=[r for r in allrows if r['task_id']==task_id]
            elif scope=='filtered':rows=[r for r in allrows if r['id'] in set(ids)]
            else:rows=allrows
            if not rows:return h._send(400,{'error':'沒有符合條件的回報'})
            if len(rows)>3000:raise ValueError('一次最多匯出 3000 筆，請縮小範圍')
            audit={}
            for r in rows:
                r['files']=[dict(f) for f in c.execute('SELECT * FROM progress_files WHERE report_id=? ORDER BY rowid',(r['id'],))]
                audit[r['id']]=[dict(a) for a in c.execute('SELECT * FROM progress_audit WHERE report_id=? ORDER BY id',(r['id'],))]
        generated=datetime.now(A.TZ).strftime('%Y/%m/%d %H:%M:%S')
        pdf=pdf_report(rows,audit,generated)
        if fmt=='pdf':data=pdf;mime='application/pdf';name='XLeRobot_progress.pdf'
        else:
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('進度回報總表.pdf',pdf)
                for r in rows:
                    for f in r['files']:
                        if f['removed_at']:continue
                        if f['storage']=='bucket':b,_=A.s3_request('GET',f['object_key'])
                        else:
                            with open(os.path.join(A.UPLOAD_DIR,f['object_key']),'rb') as fh:b=fh.read()
                        safe=os.path.basename(f['name'].replace('\\','/')).replace('..','_')
                        z.writestr('附件/回報_'+str(r['id'])+'/'+f['id'][:8]+'_'+safe,b)
            data=buffer.getvalue();mime='application/zip';name='XLeRobot_progress.zip'
        h.send_response(200);h.send_header('Content-Type',mime)
        h.send_header('Content-Disposition','attachment; filename="'+name+'"')
        h.send_header('Cache-Control','no-store');h.send_header('Content-Length',str(len(data)))
        h.end_headers();h.wfile.write(data)
    except (ValueError,TypeError) as e:h._send(400,{'error':str(e)})
    except Exception as e:
        print('progress export failed:',repr(e),flush=True)
        h._send(502,{'error':'匯出失敗，請檢查附件與 PDF 服務'})
