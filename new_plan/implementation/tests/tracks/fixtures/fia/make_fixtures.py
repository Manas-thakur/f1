"""Generate the SYNTHETIC Power Unit Information fixture PDFs used by the tests.

These are not FIA documents. Every number is invented so the parser can be
checked against known text without any external rights or network access. The
writer emits a minimal, deterministic PDF (Helvetica, one page, one content
stream) that ``pypdf`` extracts line by line.

Run from ``new_plan/implementation``::

    .venv/Scripts/python.exe tests/tracks/fixtures/fia/make_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

TABULAR_LINES = (
    "SYNTHETIC FIXTURE - NOT AN FIA DOCUMENT - TEST DATA ONLY",
    "ROUND No. R99",
    "VENUE Synthetic Loop",
    "CENTRELINE 2.400 km",
    "FORMAT Standard",
    "Document 3",
    "Date 01 January 2026",
    "Maximum Recharge per lap",
    "Overtake not active Overtake active",
    "8.0 MJ 8.5 MJ 6.0 MJ 8.5 MJ 8.5 MJ 1000 m 100 kW/s",
    "Detection Line Activation Line",
    "1200 m 1350 m",
    "L5 L6",
    "Detection Gap 1.0 s",
    "Main Overtaking Zones",
    "T1-T2",
    "T5-T6",
    "300-500",
    "1400-1700",
    "240km/h",
    "240km/h",
    "Race laps 57",
    "Base - Standard vCar (km/h) MGUK DC Power (kW)",
    "220 350",
    "260 300",
    "300 250",
    "340 200",
    "Base - Overtake vCar (km/h) MGUK DC Power (kW)",
    "220 350",
    "300 350",
    "340 300",
)

CHART_LAYOUT_LINES = (
    "SYNTHETIC FIXTURE - NOT AN FIA DOCUMENT - TEST DATA ONLY",
    "ROUND No. R98",
    "VENUE Synthetic Street",
    "CENTRELINE 3.300 km",
    "FORMAT Standard",
    "DATE 05-07 June",
    "Overtake not active Overtake active",
    "8.5 MJ 9.0 MJ 9.0 MJ 9.0 MJ 9.0 MJ 1388 m 100 kW/s",
    "- - [Exit T19] [2980-3200] [350kW] [Exit T19] [3070-3400]",
    "Detection Line",
    "Activation Line",
    "2805 m (TBC) 2950 m",
    "L19 L20/SC1",
    "- - - 1.0 s",
    "0",
    "50",
    "100",
    "220 240 260 280 300 320 340 360",
    "MGUK DC Power (kW)",
    "vCar (km/h)",
    "Rev 1 - Standard",
    "Rev 1 - Overtake",
)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_minimal_pdf(lines: tuple[str, ...]) -> bytes:
    """A one-page PDF whose text layer is exactly ``lines`` in order."""
    body = ["BT", "/F1 9 Tf", "11 TL", "36 800 Td"]
    for line in lines:
        body.append(f"({_escape(line)}) Tj T*")
    body.append("ET")
    stream = "\n".join(body).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> "
        b"/Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


FIXTURES = {
    "synthetic_pui_tabular.pdf": TABULAR_LINES,
    "synthetic_pui_chart_layout.pdf": CHART_LAYOUT_LINES,
}


def write_all(directory: Path = HERE) -> list[Path]:
    written = []
    for name, lines in FIXTURES.items():
        path = directory / name
        path.write_bytes(build_minimal_pdf(lines))
        written.append(path)
    return written


if __name__ == "__main__":
    for path in write_all():
        print(path)
