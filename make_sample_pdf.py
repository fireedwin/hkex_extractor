# -*- coding: utf-8 -*-
"""
make_sample_pdf.py — 產生一份模擬的港交所年報,用來測試整條 pipeline。

刻意加入真實年報的幾個「陷阱」:
  - 封面/目錄不編頁碼 → PDF 頁序 與 印刷頁碼 不一致
  - 財務報表沒有框線 → extract_tables() 抓不到,必須靠行解析
  - 負數用括號、空值用破折號
  - 夾雜無關的百分比(持股 51%)→ 測試合理性檢查是否擋得住
  - 一頁幾乎沒有文字 → 模擬掃描頁,測試 OCR 佇列
"""

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

W, H = A4
LEAD = 15


def page(c, lines, printed_no=None, top=H - 70):
    y = top
    for ln in lines:
        if ln.startswith("##"):
            c.setFont("Helvetica-Bold", 12)
            ln = ln[2:].strip()
        elif ln.startswith("#"):
            c.setFont("Helvetica-Bold", 15)
            ln = ln[1:].strip()
        else:
            c.setFont("Helvetica", 9)
        c.drawString(60, y, ln)
        y -= LEAD
    if printed_no is not None:
        c.setFont("Helvetica", 8)
        c.drawCentredString(W / 2, 40, str(printed_no))
    c.showPage()


def build(path="sample_annual_report.pdf"):
    c = canvas.Canvas(path, pagesize=A4)

    # --- 封面 (無頁碼) ---
    page(c, ["", "", "# SAMPLE HOLDINGS LIMITED",
             "(Incorporated in the Cayman Islands with limited liability)",
             "Stock Code: 09999", "", "## ANNUAL REPORT 2024"])

    # --- 目錄 (無頁碼) --- 注意這裡出現關鍵字,測試會不會誤判成報表頁
    page(c, ["# CONTENTS",
             "Corporate Information ................................ 2",
             "Management Discussion and Analysis .................. 5",
             "Consolidated Statement of Profit or Loss ........... 20",
             "Consolidated Statement of Financial Position ....... 22",
             "Consolidated Statement of Cash Flows ............... 24",
             "Notes to the Consolidated Financial Statements ..... 26"])

    # --- p.3 → 印刷頁 1 ---
    page(c, ["# MANAGEMENT DISCUSSION AND ANALYSIS", "",
             "## Business Review",
             "During the year, the Group recorded revenue of HK$1,284,500,000,",
             "representing an increase of 12.4% over the prior year. The gross profit",
             "margin was 38.5% (2023: 36.2%), driven by an improved product mix.",
             "",
             "The Company holds a 51% equity interest in Sample Technology Limited,",
             "which remains its principal operating subsidiary.",
             "",
             "## Research and Development",
             "Research and development expenditure for the year amounted to",
             "HK$96,340,000 (2023: HK$78,110,000), representing 7.5% of revenue.",
             "Capitalised development costs of HK$22,400,000 were recognised as",
             "intangible assets during the year."], printed_no=1)

    # --- p.4 → 印刷頁 2 : ESG ---
    page(c, ["# ENVIRONMENTAL, SOCIAL AND GOVERNANCE REPORT", "",
             "## Emissions",
             "Scope 1 greenhouse gas emissions      12,480 tCO2e",
             "Scope 2 greenhouse gas emissions      34,910 tCO2e",
             "Total GHG emissions                   47,390 tCO2e",
             "Emission intensity                    0.037 tCO2e per HK$'000 revenue",
             "",
             "## Energy",
             "Total energy consumption              68,220 MWh",
             "Renewable energy accounted for 18.0% of total consumption.",
             "The Group targets a 25% reduction in carbon intensity by 2030."],
         printed_no=2)

    # --- p.5 → 模擬掃描頁 (幾乎無文字) ---
    page(c, ["."], printed_no=3)

    # --- p.6 → 印刷頁 20 : 損益表 (無框線) ---
    page(c, ["# CONSOLIDATED STATEMENT OF PROFIT OR LOSS",
             "For the year ended 31 December 2024", "",
             "                                     Notes        2024         2023",
             "                                              HK$'000      HK$'000",
             "Revenue                                  5   1,284,500    1,142,800",
             "Cost of sales                                 (789,967)    (729,105)",
             "Gross profit                                    494,533      413,695",
             "Other income                             6       18,220       15,940",
             "Selling and distribution expenses              (142,880)    (128,400)",
             "Administrative expenses                        (188,450)    (171,220)",
             "Research and development expenses        7      (96,340)     (78,110)",
             "Operating profit                                 85,183       51,905",
             "Finance costs                            8      (18,940)     (21,330)",
             "Profit before tax                                66,243       30,575",
             "Income tax expense                       9      (14,120)      (6,880)",
             "Profit for the year                              52,123       23,695",
             "",
             "Depreciation                                     64,210       58,940",
             "Amortisation                                     19,880       16,220"],
         printed_no=20)

    # --- p.7 → 印刷頁 22 : 財務狀況表 ---
    page(c, ["# CONSOLIDATED STATEMENT OF FINANCIAL POSITION",
             "As at 31 December 2024", "",
             "                                     Notes        2024         2023",
             "                                              HK$'000      HK$'000",
             "Non-current assets",
             "Property, plant and equipment           12      618,440      591,220",
             "Investment properties                   13      284,000      262,000",
             "Goodwill                                14      196,750      196,750",
             "Intangible assets                       15      142,880      131,400",
             "Total non-current assets                      1,242,070    1,181,370",
             "",
             "Current assets",
             "Inventories                             16      218,340      241,880",
             "Trade and other receivables             17      312,660      288,420",
             "Cash and cash equivalents               18      184,920      142,310",
             "Total current assets                            715,920      672,610",
             "",
             "Total assets                                  1,957,990    1,853,980",
             "",
             "Current liabilities",
             "Trade and other payables                19      248,110      262,440",
             "Bank borrowings                         20      196,000      224,000",
             "Total current liabilities                       444,110      486,440",
             "",
             "Total liabilities                               812,660      889,220",
             "Total equity                                  1,145,330      964,760"],
         printed_no=22)

    # --- p.8 → 印刷頁 24 : 現金流量表 ---
    page(c, ["# CONSOLIDATED STATEMENT OF CASH FLOWS",
             "For the year ended 31 December 2024", "",
             "                                                  2024         2023",
             "                                               HK$'000      HK$'000",
             "Net cash generated from operating activities     168,420      121,880",
             "Purchase of property, plant and equipment        (91,340)     (84,220)",
             "Net cash used in investing activities           (113,760)    (102,540)",
             "Net cash used in financing activities            (12,050)     (34,610)",
             "Net increase in cash and cash equivalents         42,610      (15,270)"],
         printed_no=24)

    # --- p.9 → 印刷頁 58 : 商譽減值測試 (估值參數重鎮) ---
    page(c, ["# NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS", "",
             "## 14. GOODWILL",
             "Goodwill acquired through business combinations has been allocated",
             "to two cash-generating units (CGUs) for impairment testing.",
             "",
             "The recoverable amount of each CGU has been determined based on a",
             "value in use calculation using cash flow projections covering a",
             "five-year period approved by management.",
             "",
             "The pre-tax discount rate applied to the cash flow projections of the",
             "Manufacturing CGU is 13.2% (2023: 12.8%). For the Technology CGU, a",
             "pre-tax discount rate of 15.5% was applied.",
             "",
             "Cash flows beyond the five-year period are extrapolated using a",
             "terminal growth rate of 2.5%, which does not exceed the long-term",
             "average growth rate of the industry in which each CGU operates.",
             "",
             "The weighted average cost of capital used in the assessment was 11.8%.",
             "",
             "Management determined that a reasonably possible change in the",
             "discount rate of 100 basis points would not result in an impairment loss."],
         printed_no=58)

    # --- p.10 → 印刷頁 61 : 無形資產 ---
    page(c, ["## 15. INTANGIBLE ASSETS", "",
             "                          Customer      Development",
             "                     Relationships            Costs     Trademarks",
             "                           HK$'000          HK$'000        HK$'000",
             "Cost at 1 January            84,200          112,600         41,500",
             "Additions                          -           22,400              -",
             "Cost at 31 December          84,200          135,000         41,500",
             "",
             "The useful lives of intangible assets are as follows:",
             "  Customer relationships     10 years, amortised on a straight-line basis",
             "  Development costs           5 years",
             "  Trademarks                  Indefinite useful life",
             "",
             "Trademarks with indefinite useful life are tested for impairment",
             "annually. The recoverable amount was determined using the relief-from-",
             "royalty method with a discount rate of 14.0% and a notional royalty",
             "rate of 3.0% of revenue."],
         printed_no=61)

    # --- p.11 → 印刷頁 64 : 投資物業 (物業估值參數) ---
    page(c, ["## 13. INVESTMENT PROPERTIES", "",
             "The Group's investment properties were revalued at 31 December 2024",
             "by an independent professional valuer, on the basis of fair value.",
             "",
             "The valuation was arrived at using the income capitalisation approach,",
             "adopting a capitalisation rate of 3.8% (2023: 4.0%) for the retail",
             "portion and a capitalisation rate of 4.5% for the office portion.",
             "",
             "The fair value measurement is categorised within Level 3 of the fair",
             "value hierarchy. Significant unobservable inputs include the market",
             "rent of HK$52 per square foot per month and the capitalisation rate.",
             "",
             "The total gross floor area of the investment properties is 128,400",
             "square feet."],
         printed_no=64)

    # --- p.12 → 印刷頁 70 : 購股權 ---
    page(c, ["## 28. SHARE-BASED PAYMENT", "",
             "The fair value of share options granted during the year was determined",
             "using the binomial model, with the following key inputs:",
             "",
             "  Expected volatility of 42.0%",
             "  Risk-free rate of 3.6%",
             "  Expected dividend yield of 1.8%",
             "  Expected option life of 6 years",
             "",
             "## 30. RELATED PARTY TRANSACTIONS",
             "During the year the Group entered into connected transactions with",
             "a company controlled by a director amounting to HK$8,420,000."],
         printed_no=70)

    c.save()
    print(f"已產生測試檔: {path}")
    return path


if __name__ == "__main__":
    build()
