"""Check tracked HTML asset references and inline JavaScript without network calls."""
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys
import posixpath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent


class Page(HTMLParser):
    def __init__(self, path):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.script = None
        self.errors = []
        self.checked = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        ref = attrs.get("src") if tag in {"img", "script", "source", "iframe"} else None
        if tag == "link" and set(attrs.get("rel", "").split()) & {"stylesheet", "icon"}:
            ref = attrs.get("href")
        if ref:
            url = urlsplit(ref.replace(chr(92), "/"))
            if not url.scheme and not url.netloc and url.path:
                relative = unquote(url.path)
                target = (ROOT / relative.lstrip("/") if relative.startswith("/")
                          else self.path.parent / relative)
                # Compare against git's case-sensitive paths, including on Windows.
                target_name = posixpath.normpath(target.relative_to(ROOT).as_posix())
                if target_name not in tracked:
                    self.errors.append(f"{self.path.relative_to(ROOT)}: missing local asset {ref}")
                self.checked += 1
        if tag == "script":
            kind = attrs.get("type", "").lower()
            if not attrs.get("src") and kind in {"", "text/javascript", "application/javascript", "module"}:
                self.script = (kind, [])

    def handle_data(self, data):
        if self.script is not None:
            self.script[1].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            kind, chunks = self.script
            command = ["node", "--check"]
            if kind == "module":
                command.append("--input-type=module")
            result = subprocess.run(command, input="".join(chunks), text=True,
                                    encoding="utf-8", capture_output=True)
            if result.returncode:
                self.errors.append(f"{self.path.relative_to(ROOT)}: JavaScript syntax error\n{result.stderr}")
            self.checked += 1
            self.script = None


tracked = set(subprocess.check_output(
    ["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0"))
pages = sorted(name for name in tracked if name.endswith(".html"))
if not pages:
    sys.exit("No tracked HTML pages found")
errors = []
checks = 0
for name in pages:
    page = Page(ROOT / name)
    page.feed(page.path.read_text(encoding="utf-8"))
    page.close()
    errors.extend(page.errors)
    checks += page.checked
print(f"Checked {len(pages)} HTML pages and {checks} local assets/scripts.")
for error in errors:
    print(error, file=sys.stderr)
sys.exit(1 if errors else 0)
