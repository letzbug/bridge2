"""Browser-agnostic page driver interface.

Adapters talk to a PageDriver, never to Playwright directly. That keeps
adapters testable (fake page) and makes alternative backends (e.g. Selenium)
possible without touching adapter logic.

Selector syntax (configurable in providers.json):

    CSS (default)            textarea#prompt-textarea, button[aria-label*="Send" i]
    role:<role>              accessibility role, e.g. role:textbox
    role:<role>:<regex>      role + accessible name (case-insensitive regex), e.g. role:button:^send
    text:<regex>             visible text (case-insensitive regex)
    xpath=<expr>             XPath (discouraged – fragile)
"""

from __future__ import annotations

from typing import Protocol


class PageDriver(Protocol):
    async def count(self, selector: str) -> int: ...
    async def any_visible(self, selector: str) -> bool: ...
    async def first_visible_enabled(self, selector: str) -> bool: ...
    async def extract_text(self, selector: str, index: int, exclude: list[str], mode: str) -> str: ...
    async def get_attribute(self, selector: str, index: int, name: str) -> str | None: ...
    async def fill(self, selector: str, text: str, method: str) -> None: ...
    async def read_input(self, selector: str) -> str: ...
    async def click(self, selector: str) -> None: ...
    async def press(self, selector: str, key: str) -> None: ...
    async def texts(self, selector: str, limit: int) -> list[str]: ...
    async def highlight(self, selector: str, color: str) -> int: ...
    async def url(self) -> str: ...
    def is_closed(self) -> bool: ...
    async def bring_to_front(self) -> None: ...


#: Reads the visible text of a message element, skipping UI artefacts (buttons,
#: aria-hidden duplicates …). Produces light markdown (code fences, list markers,
#: inline code) so the receiving assistant sees the structure the human sees.
#: The element and the exclusion list are passed as ARGUMENTS – message content
#: is never interpolated into script source.
EXTRACT_JS = r"""
(root, args) => {
  const exclude = args.exclude || [];
  const mode = args.mode || 'markdown';
  if (mode === 'innertext') return root.innerText || root.textContent || '';
  const skip = (el) => {
    for (const s of exclude) { try { if (el.matches(s)) return true; } catch (e) {} }
    return false;
  };
  const parts = [];
  const push = (t, pre) => parts.push([t, !!pre]);
  const br = (n) => parts.push([n, false]);
  const listStack = [];
  const walk = (node, inPre) => {
    if (node.nodeType === 3) {
      if (inPre) { push(node.nodeValue, true); return; }
      const parent = node.parentElement;
      const ws = parent ? getComputedStyle(parent).whiteSpace : 'normal';
      if (ws.startsWith('pre') || ws === 'break-spaces') push(node.nodeValue, true);
      else push(node.nodeValue.replace(/\s+/g, ' '), false);
      return;
    }
    if (node.nodeType !== 1) return;
    if (node !== root && skip(node)) return;
    const tag = node.tagName;
    if (/^(STYLE|SCRIPT|NOSCRIPT|TEMPLATE|SVG)$/i.test(tag)) return;
    const style = getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden') return;
    if (tag === 'BR') { push('\n', true); return; }
    if (tag === 'PRE') {
      const code = node.querySelector('code');
      let lang = '';
      if (code) { const m = (code.className || '').match(/language-([\w+#.-]+)/); if (m) lang = m[1]; }
      const src = (code || node).textContent.replace(/\n$/, '');
      br(2); push('```' + lang + '\n' + src + '\n```', true); br(2);
      return;
    }
    if (tag === 'CODE') { push('`' + node.textContent + '`', false); return; }
    if (tag === 'HR') { br(2); push('---', false); br(2); return; }
    const d = style.display;
    const block = /^(P|DIV|SECTION|ARTICLE|BLOCKQUOTE|H[1-6]|UL|OL|LI|TABLE|TR|HEADER|FOOTER|FIGURE|FIGCAPTION|DL|DT|DD)$/.test(tag)
      || d === 'block' || d === 'flex' || d === 'grid' || d === 'list-item' || d === 'table' || d === 'table-row';
    const gap = (tag === 'P' || /^H[1-6]$/.test(tag) || tag === 'BLOCKQUOTE' || tag === 'TABLE') ? 2 : 1;
    if (block) br(gap);
    if (tag === 'UL' || tag === 'OL') listStack.push({ ordered: tag === 'OL', n: 0 });
    if (tag === 'LI') {
      const l = listStack[listStack.length - 1];
      const indent = '  '.repeat(Math.max(0, listStack.length - 1));
      if (l) { l.n += 1; push(indent + (l.ordered ? l.n + '. ' : '- '), true); }
    }
    if (/^H([1-6])$/.test(tag)) push('#'.repeat(Number(tag[1])) + ' ', true);
    for (const child of node.childNodes) walk(child, inPre);
    if (tag === 'TD' || tag === 'TH') push(' | ', true);
    if (tag === 'UL' || tag === 'OL') listStack.pop();
    if (block) br(gap);
  };
  try { walk(root, false); } catch (e) { return root.innerText || root.textContent || ''; }
  let out = '', buf = '', pending = 0, started = false;
  const flushBuf = () => { out += buf.replace(/ *\n */g, '\n'); buf = ''; };
  for (const [t, pre] of parts) {
    if (typeof t === 'number') { pending = Math.max(pending, t); continue; }
    if (t === '') continue;
    if (!started && !pre && t.trim() === '') continue;
    let text = t;
    if (pending) {
      if (started) buf += '\n'.repeat(pending);
      if (!pre) text = text.replace(/^ +/, '');
      pending = 0;
    }
    if (pre) { flushBuf(); out += text; } else { buf += text; }
    started = true;
  }
  flushBuf();
  return out.replace(/[ \t]+$/gm, '').replace(/\n{3,}/g, '\n\n').trim();
}
"""

READ_INPUT_JS = r"""
(el) => {
  if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') return el.value || '';
  return el.innerText || el.textContent || '';
}
"""

HIGHLIGHT_JS = r"""
(els, color) => {
  for (const el of els) {
    const prev = el.style.outline;
    el.style.outline = '3px solid ' + color;
    el.style.outlineOffset = '2px';
    setTimeout(() => { el.style.outline = prev; el.style.outlineOffset = ''; }, 4000);
  }
  return els.length;
}
"""
