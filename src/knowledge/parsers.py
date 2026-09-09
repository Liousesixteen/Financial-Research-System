"""Source-aware extraction. PDF pages are physical, one-based pages."""
import re
from pathlib import Path

PARSER_VERSION = 'structure-v1'
SUPPORTED = {'.pdf', '.docx', '.md', '.txt'}


class NeedsOCR(ValueError):
    pass


def extract(path: Path):
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        import pdfplumber
        blocks = []
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                text = page.extract_text(layout=False) or ''
                if text.strip():
                    blocks.append({'text': text, 'locator': f'PDF p.{number}', 'page': number, 'kind': 'text'})
                for index, table in enumerate(page.extract_tables() or [], 1):
                    rows = [' | '.join(str(cell or '').replace('\n', ' ') for cell in row) for row in table]
                    if rows:
                        blocks.append({'text': '\n'.join(rows), 'locator': f'PDF p.{number}, table {index}',
                                       'page': number, 'kind': 'table'})
        if not blocks:
            raise NeedsOCR('No extractable text. This PDF requires OCR.')
        return blocks
    if suffix == '.docx':
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        doc = Document(path)
        blocks, section = [], ''
        for index, child in enumerate(doc.element.body, 1):
            if child.tag.endswith('}p'):
                paragraph = Paragraph(child, doc)
                text = paragraph.text.strip()
                if paragraph.style and paragraph.style.name.startswith('Heading'):
                    section = text
                    continue
                kind = 'text'
            elif child.tag.endswith('}tbl'):
                table = Table(child, doc)
                text = '\n'.join(' | '.join(cell.text for cell in row.cells) for row in table.rows)
                kind = 'table'
            else:
                continue
            if text:
                blocks.append({'text': text, 'locator': f'{section} / block {index}'.strip(' /'),
                               'page': None, 'kind': kind})
        return blocks
    text = path.read_text(encoding='utf-8-sig')
    blocks, heading = [], ''
    for index, paragraph in enumerate(re.split(r'\n\s*\n', text), 1):
        if not paragraph.strip():
            continue
        match = re.match(r'^#{1,6}\s+(.+)', paragraph)
        if match:
            heading = match.group(1)
            paragraph = paragraph[match.end():].strip()
            if not paragraph:
                continue
        blocks.append({'text': paragraph.strip(), 'locator': f'{heading} / paragraph {index}'.strip(' /'),
                       'page': None, 'kind': 'text'})
    return blocks


def chunk_blocks(blocks, max_chars=1800, overlap=180):
    """Never cross a source locator. Repeat table headers in long table pieces."""
    for block in blocks:
        text = block['text']
        if block['kind'] == 'table':
            lines = text.splitlines()
            header = lines[0]
            piece = header
            for line in lines[1:]:
                if len(piece) + len(line) > max_chars and piece != header:
                    yield {**block, 'text': piece}
                    piece = header
                piece += '\n' + line
            yield {**block, 'text': piece}
            continue
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            if end < len(text):
                boundary = max(text.rfind('\n', start + max_chars // 2, end),
                               text.rfind('。', start + max_chars // 2, end))
                if boundary > start:
                    end = boundary + 1
            yield {**block, 'text': text[start:end]}
            if end == len(text):
                break
            start = max(start + 1, end - overlap)
