"""Build the fuel presentation as a standalone offline HTML file."""
from pathlib import Path


def build() -> Path:
    folder = Path(__file__).resolve().parent
    html = (folder / "index.html").read_text(encoding="utf-8")
    css = (folder / "presentation.css").read_text(encoding="utf-8-sig")
    script = (folder / "presentation.js").read_text(encoding="utf-8-sig")
    html = html.replace('<link rel="stylesheet" href="presentation.css">', f"<style>\n{css}\n</style>")
    html = html.replace('<script defer src="presentation.js"></script>', "")
    html = html.replace("</body>", f"<script>\n{script}\n</script>\n</body>")
    output = folder / "YOQILGI_AI_TAQDIMOT.html"
    output.write_text(html, encoding="utf-8")
    return output


if __name__ == "__main__":
    print(build())
