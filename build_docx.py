#!/usr/bin/env python3
"""由 Design.md 生成「第一组--多体讨论工作流设计.docx」。

用法：python3 build_docx.py
依赖：pandoc；graphviz（仅在需要重新生成 figures/*.png 时）。
样式取自 archive/ 里扩展前的 docx，并给所有表格补上与之前一致的灰色边框。
"""
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "Design.md"
OUT = ROOT / "第一组--多体讨论工作流设计.docx"
REF = ROOT / "archive" / "第一组--多体讨论工作流设计-扩展前.docx"

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
    return document_xml


def main() -> None:
    for fig in sorted((ROOT / "figures").glob("*.dot")):
        png = fig.with_suffix(".png")
        if not png.exists() or png.stat().st_mtime < fig.stat().st_mtime:
            subprocess.run(["dot", "-Tpng", str(fig), "-o", str(png)], check=True)

    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.docx"
        cmd = ["pandoc", str(SRC), "-o", str(raw), "--resource-path", str(ROOT)]
        if REF.exists():
            cmd += ["--reference-doc", str(REF)]
        subprocess.run(cmd, check=True, cwd=ROOT)

        with zipfile.ZipFile(raw) as zin, zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    data = add_table_borders(data.decode("utf-8")).encode("utf-8")
                zout.writestr(item, data)
    print(f"已生成 {OUT}")


if __name__ == "__main__":
    main()
