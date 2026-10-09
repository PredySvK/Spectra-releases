"""One Help topic as a self-contained HTML document (Markdown + offline KaTeX)."""

import html
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from markdown_it import MarkdownIt

from io_modules.help import resolve_help_resource_dir

from ._toc import resolve_help_markdown
from ._tree import build_help_title

_MATH = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$", re.DOTALL)
_MATH_TOKEN = re.compile(r"@@MATH(\d+)@@")
_NOT_TRANSLATED = {
    "cs": "Tato stránka zatím není přeložena, zobrazuje se anglická verze.",
}
_NOT_TRANSLATED_DEFAULT = "This page is not translated into this language yet; showing the English version."
_CSS = """html{color-scheme:dark}body{font:15px 'Segoe UI',Arial,sans-serif;margin:1.5em 2em;background:#1e1e1e;color:#d4d4d4;line-height:1.5}
h1,h2{color:#fff;border-bottom:1px solid #555;padding-bottom:4px}h3{color:#569cd6}a{color:#6aa9ff}
code{background:#2d2d2d;padding:1px 4px}table{border-collapse:collapse}td,th{border:1px solid #555;padding:3px 8px}
table{display:block;max-width:100%;overflow-x:auto}pre,.katex-display{max-width:100%;overflow-x:auto}
img{max-width:100%}.help-note{background:#4a3b12;color:#ffe08a;padding:6px 10px;margin-bottom:1em}"""
# Runs after katex.min.js + auto-render.min.js; the window and the manual share it.
HELP_MATH_RENDER_SCRIPT = ('renderMathInElement(document.body,{delimiters:[{left:"$$",right:"$$",display:true},'
                           '{left:"$",right:"$",display:false}]});')


@dataclass(frozen=True)
class HelpPage:
    topic_id: str
    title: str
    html: str
    anchors: tuple[str, ...]
    translated: bool  # False: the requested language had no page, English is shown


def _slug(text: str) -> str:
    return re.sub(r"[\W_]+", "-", text.lower()).strip("-")


def _render_markdown(markdown: str, image_dir: Path) -> tuple[str, list[str]]:
    # Formulas are lifted out first: markdown would eat `_` and `\` inside them.
    formulas: list[str] = []

    def lift(match: re.Match) -> str:
        formulas.append(match.group(0))
        return f"@@MATH{len(formulas) - 1}@@"

    parser = MarkdownIt("commonmark", {"html": True}).enable("table")
    tokens = parser.parse(_MATH.sub(lift, markdown))
    anchors: list[str] = []
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            base = _slug(tokens[index + 1].content) or "section"
            anchor, n = base, 1
            while anchor in anchors:
                n += 1
                anchor = f"{base}-{n}"
            anchors.append(anchor)
            token.attrSet("id", anchor)
        for child in token.children or ():
            if child.type == "image" and "://" not in child.attrGet("src"):
                child.attrSet("src", (image_dir / child.attrGet("src")).as_uri())
    body = parser.renderer.render(tokens, parser.options, {})
    return _MATH_TOKEN.sub(lambda m: html.escape(formulas[int(m.group(1))], quote=False), body), anchors


def build_help_body(topic_id: str, language: str, root: str | None = None) -> HelpPage:
    """One topic with ``html`` = the page body only: English with a visible
    "translation missing" note when that language lacks the page, a "not found" page
    when nobody has it. Formulas stay as ``$..$`` text for KaTeX; images are ``file:`` URIs."""
    markdown, translated = resolve_help_markdown(topic_id, language, root)
    if markdown is None:
        markdown, translated = f"# {topic_id}\n\n_Topic not found._\n", True
    body, anchors = _render_markdown(markdown, resolve_help_resource_dir(root) / "images")
    if not translated:
        text = _NOT_TRANSLATED.get(language, _NOT_TRANSLATED_DEFAULT)
        body = f'<div class="help-note">{html.escape(text)}</div>{body}'
    return HelpPage(topic_id, build_help_title(markdown, topic_id), body, tuple(anchors), translated)


def build_help_page(topic_id: str, language: str, fragment: str = "",
                    root: str | None = None) -> HelpPage:
    """``build_help_body`` wrapped into a self-contained HTML document for the window,
    scrolled to ``fragment``."""
    page = build_help_body(topic_id, language, root)
    katex = (resolve_help_resource_dir(root) / "katex").as_uri()
    document = (
        f'<!doctype html><meta charset="utf-8"><style>{_CSS}</style>'
        f'<link rel="stylesheet" href="{katex}/katex.min.css">'
        f'<script src="{katex}/katex.min.js"></script><script src="{katex}/auto-render.min.js"></script>'
        f"{page.html}<script>{HELP_MATH_RENDER_SCRIPT}"
        f"var f={json.dumps(fragment)};if(f){{var e=document.getElementById(f);if(e)e.scrollIntoView();}}</script>"
    )
    return replace(page, html=document)
