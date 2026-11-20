"""
Minimal rich-text sanitiser for product descriptions: bold, italic, lists, paragraphs and
line breaks only. Everything else (scripts, styles, attributes, links, images) is dropped, so a
pasted HTML blob can never reach the storefront. No third-party dependency.
"""
import re
from html import escape
from html.parser import HTMLParser

ALLOWED = {'b', 'strong', 'i', 'em', 'u', 'ul', 'ol', 'li', 'p', 'br'}
NORMALISE = {'strong': 'b', 'em': 'i'}
VOID = {'br'}
DROP_CONTENT = {'script', 'style', 'iframe', 'object', 'embed', 'noscript', 'template', 'svg', 'math'}
MAX_LEN = 8000


class _Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in ALLOWED:
            return
        tag = NORMALISE.get(tag, tag)
        if tag in VOID:
            self.out.append(f'<{tag}>')
        else:
            self.out.append(f'<{tag}>')
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in ALLOWED:
            return
        tag = NORMALISE.get(tag, tag)
        if tag in self.stack:                       # close any unclosed children first
            while self.stack:
                top = self.stack.pop()
                self.out.append(f'</{top}>')
                if top == tag:
                    break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data, quote=False))

    def close_all(self):
        while self.stack:
            self.out.append(f'</{self.stack.pop()}>')


def clean_html(value: str) -> str:
    p = _Cleaner()
    p.feed((value or '')[:MAX_LEN * 2])
    p.close()
    p.close_all()
    html = ''.join(p.out).strip()
    html = re.sub(r'(<br>\s*){3,}', '<br><br>', html)
    html = re.sub(r'<p>\s*</p>', '', html)
    return html[:MAX_LEN]


def to_text(html: str) -> str:
    """Plain text of sanitised HTML (for SEO auto-fill and length checks)."""
    text = re.sub(r'<(br|/p|/li)>', ' ', html or '')
    text = re.sub(r'<[^>]+>', '', text)
    from html import unescape
    return re.sub(r'\s+', ' ', unescape(text)).strip()
