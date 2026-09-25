"""Package the complete question-organized source with the official template."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from final_code.problem1.solver import ROOT


def write_program_bundle(output_path: Path) -> None:
    source = ROOT / "final_code"
    paths = sorted(
        path for path in source.rglob("*")
        if path.is_file() and path.suffix in {".py", ".md", ".txt"}
    )
    paths.append(ROOT / "docs" / "结果提交模板.xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", ZIP_DEFLATED) as archive:
        for path in paths:
            archive.write(path, path.relative_to(ROOT).as_posix())
