"""Build docs/laporan.md -> docs/laporan.docx (academic format: TNR 11pt, A4, 4-3-3-3 cm)."""
import re, os
from docx import Document
from docx.shared import Pt, Cm, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

OUT = "docs/laporan.docx"
MD  = "docs/laporan.md"

# ── helpers ──────────────────────────────────────────────────────────────────

def enforce_tnr(style, size=11, bold=False, color=(0,0,0)):
    style.font.name = 'Times New Roman'
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(*color)
    rPr = style._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = parse_xml(f'<w:rFonts {nsdecls("w")}/>')
        rPr.append(rFonts)
    for attr in ['w:asciiTheme','w:hAnsiTheme','w:cstheme','w:eastAsiaTheme']:
        if attr in rFonts.attrib: del rFonts.attrib[attr]
    rFonts.set(qn('w:ascii'), 'Times New Roman')
    rFonts.set(qn('w:hAnsi'), 'Times New Roman')
    rFonts.set(qn('w:cs'),    'Times New Roman')
    rFonts.set(qn('w:eastAsia'), 'Times New Roman')

def set_spacing(para, before=0, after=6, line=1.4):
    pf = para.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after  = Pt(after)
    pf.line_spacing = line

def add_run_tnr(para, text, bold=False, italic=False, size=11):
    r = para.add_run(text)
    r.font.name  = 'Times New Roman'
    r.font.size  = Pt(size)
    r.font.bold  = bold
    r.font.italic = italic
    r.font.color.rgb = RGBColor(0,0,0)
    return r

def make_row_cant_split(row):
    row._tr.get_or_add_trPr().append(
        parse_xml(f'<w:cantSplit {nsdecls("w")}/>')
    )

def make_row_header(row):
    trPr = row._tr.get_or_add_trPr()
    trPr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))
    trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))

def set_cell_shading(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    old = tcPr.find(qn('w:shd'))
    if old is not None: tcPr.remove(old)
    tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}" w:val="clear"/>'))

def cell_margins(cell, top=60, bottom=60, left=100, right=100):
    tcPr = cell._tc.get_or_add_tcPr()
    old = tcPr.find(qn('w:tcMar'))
    if old is not None: tcPr.remove(old)
    tcPr.append(parse_xml(
        f'<w:tcMar {nsdecls("w")}>'
        f'<w:top w:w="{top}" w:type="dxa"/>'
        f'<w:bottom w:w="{bottom}" w:type="dxa"/>'
        f'<w:left w:w="{left}" w:type="dxa"/>'
        f'<w:right w:w="{right}" w:type="dxa"/>'
        f'</w:tcMar>'
    ))

TOTAL_DXA = 8709  # printable width 15.4 cm for 4-3-3-3 margins

def col_widths_auto(rows, total_w=TOTAL_DXA):
    n = len(rows[0])
    def cw(ch):
        if re.match(r'[A-Z0-9#\[\]]', ch): return 140
        if re.match(r'[ilftjr.,:;()/\-]', ch): return 62
        return 98
    mins, weights = [], []
    for c in range(n):
        longest, tot = 0, 0
        for ri, row in enumerate(rows):
            cell_str = re.sub(r'[*_`\[\]]', '', row[c] if c < len(row) else '')
            tot += len(cell_str)
            f = 1.12 if ri == 0 else 1.0
            for w in cell_str.split():
                wl = f * sum(cw(ch) for ch in w)
                if wl > longest: longest = wl
        mins.append(min(longest + 170, 3000))
        weights.append(max(8, min(tot / max(len(rows),1), 120)))
    sm = sum(mins)
    if sm >= total_w:
        w = [int(m * total_w / sm) for m in mins]
    else:
        extra = total_w - sm
        sw = sum(weights)
        w = [int(m + extra * weights[i]/sw) for i, m in enumerate(mins)]
    w[-1] += total_w - sum(w)
    return w

# ── inline markup parser ─────────────────────────────────────────────────────

def add_inline(para, text, base_size=11):
    """Parse **bold**, *italic*, `code`, [text](url) inline markup into runs."""
    # strip markdown links -> keep text only
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    pattern = re.compile(r'(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)')
    parts = pattern.split(text)
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            add_run_tnr(para, part[2:-2], bold=True, size=base_size)
        elif part.startswith('*') and part.endswith('*'):
            add_run_tnr(para, part[1:-1], italic=True, size=base_size)
        elif part.startswith('`') and part.endswith('`'):
            r = para.add_run(part[1:-1])
            r.font.name = 'Courier New'
            r.font.size = Pt(base_size - 1)
        else:
            add_run_tnr(para, part, size=base_size)

# ── document setup ────────────────────────────────────────────────────────────

doc = Document()

# A4, margins 4-3-3-3 cm (top-right-bottom-left)
for sec in doc.sections:
    sec.page_width  = Cm(21)
    sec.page_height = Cm(29.7)
    sec.top_margin    = Cm(4)
    sec.right_margin  = Cm(3)
    sec.bottom_margin = Cm(3)
    sec.left_margin   = Cm(3)

# apply TNR to built-in styles
for sname, sz, bd in [
    ('Normal',    11, False),
    ('Heading 1', 13, True),
    ('Heading 2', 12, True),
    ('Heading 3', 11, True),
]:
    try:
        enforce_tnr(doc.styles[sname], size=sz, bold=bd)
    except KeyError:
        pass

# set language id-ID
try:
    styles_elm = doc.styles.element
    docRpr = styles_elm.find(qn('w:docDefaults'))
    if docRpr is not None:
        rprDef = docRpr.find(qn('w:rPrDefault'))
        if rprDef is not None:
            rpr = rprDef.find(qn('w:rPr'))
            if rpr is not None:
                rpr.append(parse_xml(
                    f'<w:lang {nsdecls("w")} w:val="id-ID" w:eastAsia="id-ID" w:bidi="ar-SA"/>'
                ))
except Exception:
    pass

# ── parse markdown ────────────────────────────────────────────────────────────

with open(MD, encoding='utf-8') as f:
    lines = f.readlines()

def clean(s): return s.strip()

i = 0
in_code_block = False
code_lines = []
in_table = False
table_rows = []
list_counter = 0
caption_next = False  # next bold line after table is caption

def flush_table():
    global table_rows
    if not table_rows: return
    # filter separator rows
    data_rows = [r for r in table_rows if not all(re.match(r'^[-:]+$', c.strip()) for c in r)]
    if not data_rows:
        table_rows = []
        return
    widths = col_widths_auto(data_rows)
    tbl = doc.add_table(rows=len(data_rows), cols=len(data_rows[0]))
    tbl.alignment = WD_TABLE_ALIGNMENT.LEFT
    tbl.style = 'Table Grid'
    # remove all borders -> clean lines
    tbl_el = tbl._tbl
    tbl_pr = tbl_el.find(qn('w:tblPr'))
    if tbl_pr is None:
        tbl_pr = parse_xml(f'<w:tblPr {nsdecls("w")}/>')
        tbl_el.insert(0, tbl_pr)
    old_borders = tbl_pr.find(qn('w:tblBorders'))
    if old_borders is not None:
        tbl_pr.remove(old_borders)
    tbl_borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="BDBDBD"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="BDBDBD"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="BDBDBD"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="BDBDBD"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="BDBDBD"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="BDBDBD"/>'
        f'</w:tblBorders>'
    )
    tbl_pr.append(tbl_borders)
    for ri, row_data in enumerate(data_rows):
        row = tbl.rows[ri]
        if ri == 0:
            make_row_header(row)
            set_cell_shading(row.cells[0], 'E8EAF6')  # light indigo header
        else:
            make_row_cant_split(row)
            if ri % 2 == 0:
                for cell in row.cells:
                    set_cell_shading(cell, 'F5F5F5')
        for ci, cell in enumerate(row.cells):
            if ci < len(widths):
                cell.width = Cm(widths[ci] / 567)  # dxa -> cm (1 cm = 567 dxa)
            cell_margins(cell)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            cell_text = row_data[ci].strip() if ci < len(row_data) else ''
            if ri == 0:
                add_run_tnr(p, re.sub(r'[*_`]','', cell_text), bold=True, size=10)
            else:
                add_inline(p, cell_text, base_size=10)
            set_spacing(p, before=0, after=0, line=1.15)
    table_rows = []

while i < len(lines):
    line = lines[i].rstrip('\n').rstrip('\r')

    # code block
    if line.strip().startswith('```'):
        if not in_code_block:
            in_code_block = True
            code_lines = []
            i += 1
            continue
        else:
            in_code_block = False
            if code_lines:
                p = doc.add_paragraph()
                p.style = 'Normal'
                set_spacing(p, before=2, after=2, line=1.1)
                p.paragraph_format.left_indent = Inches(0.3)
                r = p.add_run('\n'.join(code_lines))
                r.font.name = 'Courier New'
                r.font.size = Pt(9)
                r.font.color.rgb = RGBColor(30, 30, 30)
            code_lines = []
            i += 1
            continue
    if in_code_block:
        code_lines.append(line)
        i += 1
        continue

    # table row
    if line.strip().startswith('|'):
        if not in_table:
            in_table = True
            flush_table()
            table_rows = []
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        table_rows.append(cells)
        i += 1
        continue
    else:
        if in_table:
            in_table = False
            flush_table()

    stripped = line.strip()

    # blank
    if not stripped:
        i += 1
        continue

    # headings
    m = re.match(r'^(#{1,3})\s+(.*)', stripped)
    if m:
        level = len(m.group(1))
        heading_text = m.group(2).strip()
        hstyle = {1: 'Heading 1', 2: 'Heading 2', 3: 'Heading 3'}[level]
        p = doc.add_paragraph(style=hstyle)
        add_inline(p, heading_text, base_size={1:13,2:12,3:11}[level])
        p.runs[0].font.bold = True if p.runs else True
        set_spacing(p, before=12 if level==1 else 6, after=4, line=1.2)
        i += 1
        continue

    # H1 setext (===)
    if i+1 < len(lines) and re.match(r'^=+$', lines[i+1].strip()):
        p = doc.add_paragraph(style='Heading 1')
        add_inline(p, stripped, base_size=13)
        set_spacing(p, before=12, after=4, line=1.2)
        i += 2
        continue

    # numbered list
    m = re.match(r'^(\d+)\.\s+(.*)', stripped)
    if m:
        num = m.group(1)
        content = m.group(2)
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.4)
        p.paragraph_format.first_line_indent = Inches(-0.25)
        set_spacing(p, before=0, after=2, line=1.4)
        add_run_tnr(p, f"{num}. ", bold=False, size=11)
        add_inline(p, content, base_size=11)
        i += 1
        continue

    # bold caption / figure label
    if re.match(r'^\*\*[^*]+\*\*$', stripped):
        # standalone bold line -> caption
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_spacing(p, before=2, after=6, line=1.2)
        add_run_tnr(p, re.sub(r'\*\*','', stripped), bold=True, size=10)
        i += 1
        continue

    # normal paragraph
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    set_spacing(p, before=0, after=6, line=1.4)
    add_inline(p, stripped, base_size=11)
    i += 1

# flush trailing table
if in_table:
    flush_table()

# ── title page (prepend) ──────────────────────────────────────────────────────
# Insert cover at the very beginning by building a new doc and prepending
# (python-docx doesn't support prepend easily; we'll just add a page break
#  after the preamble instead and note the cover is manual)

# ── save ─────────────────────────────────────────────────────────────────────
try:
    doc.save(OUT)
    print(f"Saved: {OUT}")
except PermissionError:
    alt = OUT.replace('.docx', '_v2.docx')
    doc.save(alt)
    print(f"PermissionError on primary; saved: {alt}")
