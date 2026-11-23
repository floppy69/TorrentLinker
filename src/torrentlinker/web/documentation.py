"""Render bundled Markdown without executing embedded HTML or loading remote images."""

from urllib.parse import quote, urlsplit

from markdown_it import MarkdownIt

from torrentlinker import documentation as docs


def render(name: str, *, standalone: bool = False, root_path: str = "") -> str:
    path = docs.document_path(name)
    if path.suffix != ".md":
        raise ValueError("Not a guide.")
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(path.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            slug = docs.heading_anchor(tokens[index + 1].content)
            number = seen.get(slug, 0)
            seen[slug] = number + 1
            token.attrSet("id", slug + ("-" + str(number) if number else ""))
        for child in token.children or []:
            if child.type not in {"link_open", "image"}:
                continue
            attribute = "src" if child.type == "image" else "href"
            target = str(child.attrGet(attribute) or "")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc:
                if child.type == "image" or parsed.scheme not in {"https", "http"}:
                    child.attrSet(attribute, "")
                else:
                    child.attrSet("target", "_blank")
                    child.attrSet("rel", "noopener noreferrer")
                continue
            relative = docs.link_path(name, target)
            try:
                resolved = docs.document_path(relative)
            except (ValueError, OSError):
                if child.type == "image":
                    child.attrSet("src", "")
                    continue
                child.attrSet(attribute, docs.ONLINE + quote(relative, safe="/"))
                child.attrSet("target", "_blank")
                child.attrSet("rel", "noopener noreferrer")
                continue
            if child.type == "image":
                child.attrSet("data-guide-image", relative)
                child.attrSet(
                    "src",
                    (
                        root_path.rstrip("/") + "/api/documentation/file/"
                        if standalone
                        else "api/documentation/file/"
                    )
                    + quote(relative, safe="/"),
                )
            elif resolved.suffix == ".md":
                child.attrSet(
                    "href",
                    (
                        root_path.rstrip("/") + "/documentation/" + quote(relative, safe="/")
                        if standalone
                        else ""
                    )
                    + "#"
                    + parsed.fragment,
                )
                child.attrSet("data-guide", relative)
    return parser.renderer.render(tokens, parser.options, {})
