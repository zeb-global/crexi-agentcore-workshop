"""Generates the T-12 operating statement and offering memorandum PDFs at
deploy time, so no binary files live in git and NOI is embedded as
extractable text -- it exists nowhere else in the system.

Hand-rolled, dependency-free PDF writer (no reportlab/Pillow/Docker). The
seed Lambda uses CodeZip, and this repo's whole point is that nobody needs
a container or a build step to deploy it -- a text-extraction library
would need a compiled wheel we can't guarantee across every participant's
CPU architecture without a Docker bundling step we've deliberately avoided.
Standard PDF Type1 base-14 fonts (Helvetica, Helvetica-Bold) need no
embedding, so this produces a small, valid, text-searchable PDF with
nothing more than the stdlib.
"""
from __future__ import annotations


def _escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


class _SimplePdf:
    """One-page, two-font (Helvetica / Helvetica-Bold) PDF builder."""

    PAGE_WIDTH = 612  # US Letter, points
    PAGE_HEIGHT = 792

    def __init__(self) -> None:
        self._ops: list[str] = []

    def text(self, x: float, y: float, s: str, *, bold: bool = False, size: int = 10) -> None:
        font = "/F2" if bold else "/F1"
        self._ops.append(f"BT {font} {size} Tf {x:.2f} {y:.2f} Td ({_escape(s)}) Tj ET")

    def line(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self._ops.append(f"{x0:.2f} {y0:.2f} m {x1:.2f} {y1:.2f} l S")

    def render(self) -> bytes:
        content = "\n".join(self._ops).encode("latin-1")
        objects: list[bytes] = []

        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
        objects.append(
            b"<< /Type /Page /Parent 2 0 R "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> "
            + f"/MediaBox [0 0 {self.PAGE_WIDTH} {self.PAGE_HEIGHT}] ".encode("ascii")
            + b"/Contents 6 0 R >>"
        )
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
        objects.append(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"\nendstream"
        )

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode("ascii") + body + b"\nendobj\n"

        xref_offset = len(out)
        n = len(objects) + 1
        out += f"xref\n0 {n}\n".encode("ascii")
        out += b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += f"{off:010d} 00000 n \n".encode("ascii")
        out += (
            f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
        return bytes(out)


def _t12_lines(noi: int) -> list[tuple[str, int, bool]]:
    gross_potential_rent = round(noi / 0.62)  # ~62% NOI margin, plausible for MF
    vacancy_loss = round(gross_potential_rent * 0.06)
    other_income = round(gross_potential_rent * 0.04)
    effective_gross_income = gross_potential_rent - vacancy_loss + other_income
    operating_expenses = effective_gross_income - noi
    return [
        ("Gross Potential Rent", gross_potential_rent, False),
        ("Less: Vacancy Loss", -vacancy_loss, False),
        ("Plus: Other Income (laundry, parking, fees)", other_income, False),
        ("Effective Gross Income", effective_gross_income, True),
        ("Less: Total Operating Expenses", -operating_expenses, False),
        ("Net Operating Income (NOI)", noi, True),
    ]


def build_t12(name: str, listing_id: str, asking_price: int, noi: int) -> bytes:
    pdf = _SimplePdf()
    y = 720
    pdf.text(72, y, f"{name} -- Trailing 12-Month Operating Statement", bold=True, size=15)
    y -= 22
    pdf.text(72, y, f"Listing ID: {listing_id}    Period: Trailing 12 months ending 2025-Q4", size=9)
    y -= 26
    pdf.text(72, y, "Line Item", bold=True, size=10)
    pdf.text(360, y, "Amount (USD)", bold=True, size=10)
    y -= 4
    pdf.line(72, y, 540, y)
    y -= 20

    for label, amount, bold in _t12_lines(noi):
        pdf.text(72, y, label, bold=bold, size=10)
        pdf.text(420, y, f"${amount:,.0f}", bold=bold, size=10)
        y -= 20

    y -= 14
    pdf.text(
        72, y,
        "Prepared for underwriting review. Net Operating Income above is the",
        size=8,
    )
    y -= 12
    pdf.text(72, y, "figure used in all cap-rate and debt-coverage calculations for this listing.", size=8)
    return pdf.render()


def build_om(name: str, listing_id: str, units: int, asking_price: int, year_renovated: int) -> bytes:
    pdf = _SimplePdf()
    y = 720
    pdf.text(72, y, f"{name} -- Offering Memorandum", bold=True, size=15)
    y -= 28
    for label, value in [
        ("Listing ID", listing_id),
        ("Units", str(units)),
        ("Asking Price", f"${asking_price:,.0f}"),
        ("Year Renovated", str(year_renovated)),
        ("Market", "Columbus, OH"),
        ("Asset Type", "Multifamily"),
    ]:
        pdf.text(72, y, f"{label}:", size=10)
        pdf.text(216, y, value, size=10)
        y -= 20

    y -= 16
    pdf.text(72, y, "For underwriting on operating performance, see the T-12 operating statement.", size=8)
    return pdf.render()
