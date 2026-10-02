"""Small HTML evidence reader, including rowspan/colspan and section context."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


def clean_text(text: str) -> str:
    return " ".join(re.sub(r"\[\s*\d+\s*\]", "", text).split())


@dataclass
class Cell:
    text: str = ""
    rowspan: int = 1
    colspan: int = 1
    header: bool = False
    links: list[str] = field(default_factory=list)


@dataclass
class Table:
    section: str
    rows: list[list[Cell]] = field(default_factory=list)

    def grid(self) -> list[list[Cell]]:
        """Expand spans without losing the original source cell contents."""
        occupied: dict[tuple[int, int], Cell] = {}
        for y, row in enumerate(self.rows):
            x = 0
            for cell in row:
                while (y, x) in occupied:
                    x += 1
                for dy in range(cell.rowspan):
                    for dx in range(cell.colspan):
                        occupied[y + dy, x + dx] = cell
                x += cell.colspan
        width = max((x + 1 for _, x in occupied), default=0)
        return [
            [occupied.get((y, x), Cell()) for x in range(width)]
            for y in range(len(self.rows))
        ]


class Document(HTMLParser):
    """Keep text, tables and list items; scripts/styles are excluded."""

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self.items: list[tuple[str, str]] = []
        self.ordered_items: list[tuple[str, str]] = []
        self.fragments: list[str] = []
        self.headings: dict[int, str] = {}
        self._heading: tuple[int, list[str]] | None = None
        self._tables: list[Table] = []
        self._cells: list[Cell | None] = []
        self._items: list[tuple[str, list[str]]] = []
        self._list_numbers: list[int | None] = []
        self._item_numbers: list[int | None] = []
        self._skip = 0
        self.feed(html)

    @property
    def section(self) -> str:
        return " / ".join(self.headings[k] for k in sorted(self.headings))

    @property
    def text(self) -> str:
        return clean_text(" ".join(self.fragments))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("h2", "h3", "h4", "h5", "h6"):
            self._heading = (int(tag[1]), [])
        if tag == "table":
            table = Table(self.section)
            self.tables.append(table)
            self._tables.append(table)
            self._cells.append(None)
        elif tag == "tr" and self._tables:
            self._tables[-1].rows.append([])
        elif tag in ("td", "th") and self._tables:
            cell = Cell(
                rowspan=min(1000, max(1, int(attributes.get("rowspan") or 1))),
                colspan=min(100, max(1, int(attributes.get("colspan") or 1))),
                header=tag == "th",
            )
            if not self._tables[-1].rows:
                self._tables[-1].rows.append([])
            self._tables[-1].rows[-1].append(cell)
            self._cells[-1] = cell
        elif tag in ("ol", "ul"):
            self._list_numbers.append(
                int(attributes.get("start") or 1)
                if tag == "ol" and attributes.get("type", "1") == "1"
                else None
            )
        elif tag == "li":
            self._items.append((self.section, []))
            number = self._list_numbers[-1] if self._list_numbers else None
            if number is not None:
                number = int(attributes.get("value") or number)
                self._list_numbers[-1] = number + 1
            self._item_numbers.append(number)
        if tag in ("br", "p", "li", "tr", "td", "th", "div"):
            self.handle_data("\n")
        if tag == "a" and self._cells and self._cells[-1] is not None:
            cell = self._cells[-1]
            assert cell is not None
            if href := attributes.get("href"):
                cell.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if tag.startswith("h") and self._heading and tag == f"h{self._heading[0]}":
            level, fragments = self._heading
            self.headings = {k: v for k, v in self.headings.items() if k < level}
            self.headings[level] = clean_text("".join(fragments)).replace("[edit]", "")
            self._heading = None
        if tag == "table" and self._tables:
            self._tables.pop()
            self._cells.pop()
        if tag in ("td", "th") and self._cells:
            self._cells[-1] = None
        if tag == "li" and self._items:
            section, fragments = self._items.pop()
            text = clean_text("".join(fragments))
            self.items.append((section, text))
            number = self._item_numbers.pop()
            if number is not None:
                self.ordered_items.append((section, f"{number} {text}"))
        if tag in ("ol", "ul") and self._list_numbers:
            self._list_numbers.pop()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.fragments.append(data)
        if self._heading:
            self._heading[1].append(data)
        if self._cells and self._cells[-1] is not None:
            cell = self._cells[-1]
            assert cell is not None
            cell.text += data
        if self._items:
            self._items[-1][1].append(data)
