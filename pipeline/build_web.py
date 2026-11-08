"""Bundle web/template.html + web/data.json into self-contained pages.

  web/index.html     full HTML document: open it directly in a browser
  web/artifact.html  body-only version used for publishing as a claude.ai Artifact

Usage:  python pipeline/build_web.py   (run after analyse.py)
"""
from __future__ import annotations

from common import WEB

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>*,*::before,*::after{box-sizing:border-box}body{margin:0}[hidden]{display:none!important}
:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}</style>
</head>
<body>
"""


def main() -> None:
    tpl = (WEB / "template.html").read_text()
    data = (WEB / "data.json").read_text()
    # keep the JSON from closing the <script> tag early
    data = data.replace("</", "<\\/")
    page = tpl.replace("/*__DATA__*/", data)
    (WEB / "artifact.html").write_text(page)
    (WEB / "index.html").write_text(HEAD + page + "\n</body>\n</html>\n")
    print(f"web/index.html  {len(page)/1e6:.1f} MB")


if __name__ == "__main__":
    main()
