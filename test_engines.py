# -*- coding: utf-8 -*-
"""
test_engines.py — 鎖住「PyMuPDF 表格被拆行」這個 bug

這個 bug 很隱蔽:合成的簡單 PDF 測不出來,只有在「每個儲存格分開繪製」
的真實年報排版下才會出現,而且症狀是財務科目「靜靜地」歸零,不會報錯。

用法: python3 test_engines.py
"""
import sys, os, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def make_table_pdf(path):
    """模擬真實年報:每個儲存格分開畫,而不是整行一次畫完。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    W, H = A4
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont('Helvetica-Bold', 13)
    c.drawString(60, H-70, 'CONSOLIDATED STATEMENT OF PROFIT OR LOSS')
    y = H-130
    for lab, a, b, n in [('', '2024', '2023', None),
                         ('Revenue', '1,284,500', '1,142,800', '5'),
                         ('Gross profit', '494,533', '413,695', None),
                         ('Profit for the year', '52,123', '23,695', None)]:
        c.setFont('Helvetica', 9)
        c.drawString(60, y, lab)
        if n: c.drawString(300, y, n)
        c.drawRightString(450, y, a)
        c.drawRightString(530, y, b)
        y -= 15
    c.setFont('Helvetica', 8)
    c.drawCentredString(W/2, 40, '82')
    c.showPage(); c.save()


def main():
    from pdf_reader import read_pdf, engine_available
    from financials import extract_financials

    tmp = os.path.join(tempfile.gettempdir(), '_engine_test.pdf')
    make_table_pdf(tmp)

    ok = True
    results = {}
    for eng in ('pdfplumber', 'pymupdf'):
        if not engine_available(eng):
            print(f'  略過 {eng}(未安裝)')
            continue
        pages = read_pdf(tmp, verbose=False, engine=eng)
        fin = extract_financials(pages, verbose=False)
        items = {i.item: i.current_year for i in fin.items}
        results[eng] = (items, pages[0].cite)
        print(f'  {eng:12} 財務科目 {len(items)} 筆  {pages[0].cite}')

    print()
    if len(results) == 2:
        a, b = results['pdfplumber'], results['pymupdf']
        if a[0] == b[0]:
            print('  ✓ 兩引擎財務科目完全相同')
        else:
            ok = False
            print(f'  ✗ 財務科目不同\n    pdfplumber: {a[0]}\n    pymupdf:    {b[0]}')
        if a[1] == b[1]:
            print('  ✓ 兩引擎頁碼標註相同')
        else:
            ok = False
            print(f'  ✗ 頁碼標註不同: {a[1]} vs {b[1]}')

    for eng, (items, _) in results.items():
        if items.get('Revenue') != 1284500.0:
            ok = False
            print(f'  ✗ {eng} 的 Revenue 應為 1284500,實際 {items.get("Revenue")}')

    os.remove(tmp)
    print()
    print('全部通過' if ok else '有測試失敗')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
