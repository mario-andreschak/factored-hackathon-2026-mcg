"""Savia product topology and technical-document renderer (stdlib only)."""
from html import escape
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent


def system_svg(Diagram):
    from product_topology import render
    return render(Diagram)


def inline(value):
    """Render the deliberately small Markdown vocabulary used by this document."""
    tokens = []
    def protect(match):
        tokens.append('<code>'+escape(match.group(1))+'</code>')
        return f'\x00{len(tokens)-1}\x00'
    value = re.sub(r'`([^`]+)`', protect, value)
    value = escape(value)
    def link(match):
        href = match.group(2)
        if href.startswith('../'):
            relative = (ROOT / href).resolve().relative_to(ROOT.parents[1]).as_posix()
            revision = 'main' if relative.startswith('docs/submission/') else '9d77a7599128b668b0e34f9c2937eb40b6bd3824'
            href = 'https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/'+revision+'/'+relative
        return '<a href="'+href+'">'+match.group(1)+'</a>'
    value = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, value)
    value = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', value)
    value = re.sub(r'\x00(\d+)\x00', lambda m: tokens[int(m.group(1))], value)
    return value


def document_body(svg):
    lines = (ROOT / 'system-landscape.md').read_text(encoding='utf-8').splitlines()
    parts, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line == '<!-- topology -->':
            parts.append('<figure class="topology">'+svg+'<figcaption>Savia is the customer application on the left. The target fleet on the right reuses the recovered FLUJO swarm template: ten Machines, each with one lead and nine specialists. Dashed connections identify customer integrations still to qualify; development/reviewer hosts are outside this system.</figcaption></figure>')
            i += 1
            continue
        if line.startswith('#'):
            level = len(line)-len(line.lstrip('#'))
            title = line[level:].strip()
            slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
            parts.append(f'<h{level} id="{slug}">{inline(title)}</h{level}>')
            i += 1
            continue
        if line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                rows.append(lines[i].strip().strip('|').split('|'))
                i += 1
            head, *body = [row for row in rows if not all(re.fullmatch(r'\s*:?-+:?\s*', cell) for cell in row)]
            parts.append('<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+inline(cell.strip())+'</th>' for cell in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+inline(cell.strip())+'</td>' for cell in row)+'</tr>' for row in body)+'</tbody></table></div>')
            continue
        if re.match(r'\d+\. ', line):
            items = []
            while i < len(lines) and re.match(r'\d+\. ', lines[i]):
                items.append('<li>'+inline(re.sub(r'^\d+\. ', '', lines[i]))+'</li>')
                i += 1
            parts.append('<ol>'+''.join(items)+'</ol>')
            continue
        paragraph = []
        while i < len(lines) and lines[i].strip():
            paragraph.append(lines[i])
            i += 1
        parts.append('<p>'+inline(' '.join(paragraph))+'</p>')
    return '\n'.join(parts)


DOCUMENT_CSS = '''
.technical{max-width:1500px;margin:0 auto;padding:30px 38px 55px;background:white;line-height:1.55;font-size:15px;border:0;border-radius:0}
.technical h1{font-size:30px;margin:0 0 12px}.technical h2{font-size:22px;margin:32px 0 12px;border-top:2px solid #b9cbd4;padding-top:16px;scroll-margin-top:100px}
.technical p{margin:12px 0}.technical code{font:12.5px Consolas,monospace;overflow-wrap:anywhere;background:#edf3f6;padding:1px 3px}
.technical table{width:100%;border-collapse:collapse;margin:12px 0 20px;font-size:14px;table-layout:fixed}.technical th{text-align:left;background:#e8f0f5;color:#18323d}
.technical th,.technical td{vertical-align:top;border:1px solid #c8d5db;padding:9px 12px;overflow-wrap:anywhere}.technical th:first-child{width:27%}.technical tr:nth-child(even) td{background:#f7fafb}
.technical .table-wrap{overflow:auto}.technical li{margin:12px 0}.technical figure{margin:18px -20px 28px}.technical figure svg{display:block;width:100%;height:auto}
.technical figcaption{font-size:12px;color:#57707c;margin:8px 20px}.technical .document-links{display:flex;gap:20px;margin:18px 0;flex-wrap:wrap}.print-cover{display:none}
body.zoom .technical figure{overflow:auto}body.zoom .technical figure svg{width:2400px;max-width:none}
@page{size:A4 portrait;margin:15mm}
@page topology{size:A3 landscape;margin:7mm}
@media print{header,.document-links{display:none!important}body{background:white}.print-cover{display:block;page:topology;break-after:page}.print-cover svg{width:100%;height:auto;display:block}.technical{max-width:none;margin:0;padding:0;font-size:14px;line-height:1.4}.technical h1{font-size:24px}.technical h2{font-size:18px;margin:22px 0 10px;break-after:avoid}.technical p{margin:9px 0;orphans:3;widows:3}.technical code{font-size:12px}.technical table{font-size:12.5px}.technical th,.technical td{padding:7px 9px}.technical tr{break-inside:avoid}.technical thead{display:table-header-group}.technical figure{display:none}a{color:inherit;text-decoration:none}section[hidden]{display:none!important}}
@media(max-width:650px){.technical{padding:24px 16px}.technical h1{font-size:24px}.technical table{font-size:12px;min-width:650px}.technical figure{margin:12px -8px}}
'''


def system_section(svg):
    links = '<div class="document-links"><a href="system-landscape.pdf" download>Technical document PDF</a><a href="system-landscape.svg" download>Topology SVG</a><a href="system-landscape.png" download>Topology PNG</a><a href="system-landscape.md">Markdown source</a></div>'
    print_svg = svg
    for svg_id in re.findall(r'id="([^"]+)"', svg):
        print_svg = print_svg.replace('id="'+svg_id+'"', 'id="print-'+svg_id+'"').replace('url(#'+svg_id+')', 'url(#print-'+svg_id+')')
    print_svg = re.sub(r'aria-labelledby="([^"]+)"', lambda m: 'aria-labelledby="'+' '.join('print-'+part for part in m.group(1).split())+'"', print_svg)
    return '<section id="system"><div class="print-cover">'+print_svg+'</div><article class="technical">'+links+document_body(svg)+'</article></section>'


def standalone(svg):
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Savia · technical product architecture</title><style>body{margin:0;color:#18323d;background:#e9eff2;font-family:Arial,Helvetica,sans-serif}a{color:#2869b2}'+DOCUMENT_CSS+'</style></head><body>'+system_section(svg)+'</body></html>'
