"""Render docs/STUDY_GUIDE.md to a self-contained docs/STUDY_GUIDE.html (print to PDF in a browser).

Optional developer tool: needs `pip install markdown` (not part of the app's requirements).
Run from the repository root:  python scripts/build_study_guide.py
"""

from __future__ import annotations

from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
CSS = """
body{font-family:'Segoe UI',Calibri,Arial,sans-serif;line-height:1.55;color:#14181f;max-width:980px;
margin:2rem auto;padding:0 1.2rem;}
h1{color:#1f3a5f;border-bottom:3px solid #1f3a5f;padding-bottom:.3rem;margin-top:2.4rem;}
h2{color:#1f3a5f;margin-top:1.8rem;border-bottom:1px solid #d6dbe3;padding-bottom:.2rem;}
h3{color:#2b5486;}
table{border-collapse:collapse;margin:1rem 0;width:100%;font-size:.92rem;}
th{background:#1f3a5f;color:#fff;text-align:left;padding:.45rem .6rem;}
td{border:1px solid #d6dbe3;padding:.4rem .6rem;vertical-align:top;}
tr:nth-child(even) td{background:#f6f8fb;}
code{background:#eef1f6;padding:.1rem .3rem;border-radius:3px;font-size:.9em;}
pre{background:#f3f5f9;border:1px solid #d6dbe3;border-radius:6px;padding:.8rem 1rem;
overflow-x:auto;}
pre code{background:none;padding:0;}
blockquote{border-left:4px solid #2a78d6;background:#eef4fc;margin:1rem 0;padding:.5rem 1rem;}
hr{border:none;border-top:1px solid #d6dbe3;margin:2rem 0;}
.toc{background:#f6f8fb;border:1px solid #d6dbe3;border-radius:8px;padding:.5rem 1.2rem;}
@media print{body{max-width:none;margin:0} h1{page-break-before:always}
h1:first-of-type{page-break-before:avoid}
pre,table{page-break-inside:avoid}}
"""


def build() -> Path:
    """Convert the markdown guide to HTML and return the output path."""
    src = ROOT / "docs" / "STUDY_GUIDE.md"
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"toc_depth": "1-2"}},
    )
    body = md.convert(src.read_text(encoding="utf-8"))
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        "<title>AuditLens Study Guide</title>"
        f"<style>{CSS}</style></head><body>"
        f'<div class="toc"><b>Quick navigation</b>{md.toc}</div>{body}</body></html>'
    )
    out = ROOT / "docs" / "STUDY_GUIDE.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    print(f"Wrote {build()}")
