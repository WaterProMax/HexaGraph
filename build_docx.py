#!/usr/bin/env python3
"""由 Design.md 生成「第一组--多体讨论工作流设计.docx」。

用法：python3 build_docx.py [源.md 输出.docx]
依赖：pandoc；graphviz（仅在需要重新生成 figures/*.png 时）。
样式取自 archive/ 里扩展前的 docx（不存在时用作业一的 docx），并给所有表格补上与之前一致的灰色边框。
"""
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "Design.md"
OUT = ROOT / "第一组--多体讨论工作流设计.docx"
REF = ROOT / "archive" / "第一组--多体讨论工作流设计-扩展前.docx"
if not REF.exists():
    REF = OUT
if len(sys.argv) == 3:
    SRC, OUT = ROOT / sys.argv[1], ROOT / sys.argv[2]

BORDERS = (
    "<w:tblBorders>"
    + "".join(
        f'<w:{side} w:val="single" w:color="8A94A6" w:sz="4" w:space="0"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    + "</w:tblBorders>"
)
CELL_MAR = (
    "<w:tblCellMar>"
    '<w:top w:w="40" w:type="dxa"/><w:left w:w="108" w:type="dxa"/>'
    '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="108" w:type="dxa"/>'
    "</w:tblCellMar>"
)


def add_table_borders(document_xml: str) -> str:
    # 在 tblLayout 之前插入边框，在 tblLook 之前插入单元格边距（符合 OOXML 子元素顺序）
    document_xml = re.sub(r"(<w:tblLayout\b)", BORDERS + r"\1", document_xml)
    document_xml = re.sub(r"(<w:tblLook\b)", CELL_MAR + r"\1", document_xml)
    document_xml = re.sub(r'<w:tblLayout w:type="autofit"/>', '<w:tblLayout w:type="fixed"/>', document_xml)
    return document_xml


def apply_line_breaks(document_xml: str) -> str:
    """把正文里的 ⟪BR⟫ 换成 Word 硬换行。管道表放不进 HTML 换行。"""
    marker = "⟪BR⟫"

    def split_run(match: re.Match[str]) -> str:
        text = match.group(1)
        if marker not in text:
            return match.group(0)
        parts = text.split(marker)
        chunks = []
        for i, part in enumerate(parts):
            if part:
                chunks.append(f'<w:t xml:space="preserve">{part}</w:t>')
            if i < len(parts) - 1:
                chunks.append("<w:br/>")
        return "".join(chunks)

    return re.sub(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", split_run, document_xml)


def keep_rows_together(document_xml: str) -> str:
    """行不跨页拆开，表头在续页重复。避免半行字留在下一页页首。"""

    def fix_table(match: re.Match[str]) -> str:
        tbl = match.group(0)
        seen = {"n": 0}

        def fix_tr(tr_match: re.Match[str]) -> str:
            tr = tr_match.group(0)
            header = seen["n"] == 0
            seen["n"] += 1
            extra = "<w:cantSplit/>" + ("<w:tblHeader/>" if header else "")
            if re.search(r"<w:trPr\b", tr):
                return re.sub(r"<w:trPr\b[^>]*>", lambda m: m.group(0) + extra, tr, count=1)
            return re.sub(r"<w:tr\b[^>]*>", lambda m: m.group(0) + "<w:trPr>" + extra + "</w:trPr>", tr, count=1)

        return re.sub(r"<w:tr\b.*?</w:tr>", fix_tr, tbl, flags=re.S)

    return re.sub(r"<w:tbl\b.*?</w:tbl>", fix_table, document_xml, flags=re.S)


def main() -> None:
    for fig in sorted((ROOT / "figures").glob("*.dot")):
        png = fig.with_suffix(".png")
        if not png.exists() or png.stat().st_mtime < fig.stat().st_mtime:
            subprocess.run(["dot", "-Tpng", str(fig), "-o", str(png)], check=True)

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.docx"
        # columns 调小后，管道表一律按分隔线的长短分配列宽
        cmd = ["pandoc", str(SRC), "-o", str(raw), "--columns=20", "--resource-path", str(ROOT)]
        if REF.exists():
            cmd += ["--reference-doc", str(REF)]
        subprocess.run(cmd, check=True, cwd=ROOT)

        with zipfile.ZipFile(raw) as zin, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    xml = add_table_borders(data.decode("utf-8"))
                    xml = apply_line_breaks(xml)
                    xml = keep_rows_together(xml)
                    data = xml.encode("utf-8")
                zout.writestr(item, data)
    print(f"已生成 {OUT}")


if __name__ == "__main__":
    main()
