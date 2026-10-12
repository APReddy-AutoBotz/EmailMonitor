"""Deterministic authored PDFs, not parser expected-output lookup tables.

Only PDF standard-font references are used; no third-party font program, source
paper, renderer, OCR engine or external image is embedded. RC4 is solely an
insecure synthetic encrypted-refusal fixture, never a product encryption choice.
"""

from collections.abc import Sequence
from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

Line = tuple[float, float, float, str]


def document(
    pages: Sequence[Sequence[Line]], *, encrypted: bool = False, image_only: bool = False
) -> bytes:
    writer = PdfWriter()
    writer.add_metadata(
        {"/Title": "Authored contact-research fixture", "/Author": "Synthetic fixture"}
    )
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Courier"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    font_ref = writer._add_object(font)
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        resources = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        page[NameObject("/Resources")] = resources
        commands: list[bytes] = []
        for x, y, size, value in lines:
            encoded = value.encode("cp1252")
            escaped = b"".join(
                bytes((byte,))
                if 32 <= byte < 127 and byte not in (40, 41, 92)
                else f"\\{byte:03o}".encode("ascii")
                for byte in encoded
            )
            commands.append(
                f"BT /F1 {size:g} Tf 1 0 0 1 {x:g} {y:g} Tm (".encode("ascii")
                + escaped
                + b") Tj ET\n"
            )
        if image_only:
            image = DecodedStreamObject()
            image.set_data(b"\xff\xff\xff")
            image.update(
                {
                    NameObject("/Type"): NameObject("/XObject"),
                    NameObject("/Subtype"): NameObject("/Image"),
                    NameObject("/Width"): NumberObject(1),
                    NameObject("/Height"): NumberObject(1),
                    NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                    NameObject("/BitsPerComponent"): NumberObject(8),
                }
            )
            resources[NameObject("/XObject")] = DictionaryObject(
                {NameObject("/Im1"): writer._add_object(image)}
            )
            commands.append(b"q 200 0 0 200 50 300 cm /Im1 Do Q\n")
        content = DecodedStreamObject()
        content.set_data(b"".join(commands))
        page[NameObject("/Contents")] = writer._add_object(content)
    if encrypted:
        writer.encrypt("synthetic-refusal-password", algorithm="RC4-128")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def authored() -> dict[str, bytes]:
    return {
        "article-a.pdf": document(
            [
                [
                    (50, 745, 16, "Title: Synthetic article A"),
                    (50, 715, 11, "Authors: Mira Rao"),
                    (162, 721, 7, "1"),
                    (172, 715, 11, "; Alex Chen"),
                    (249, 721, 7, "2"),
                    (50, 680, 9, "Journal: Synthetic Research Journal"),
                    (50, 650, 10, "Left column: harmless scientific text."),
                    (320, 650, 10, "Right column: no author contact here."),
                    (50, 30, 8, "Support: help@example.org"),
                ],
                [
                    (50, 720, 10, "Continued research text."),
                    (50, 110, 8, "Correspondence [2]: Alex Chen; alex.chen@example.org"),
                    (50, 70, 8, "References"),
                    (50, 58, 8, "Cited author: cited@example.org"),
                ],
            ]
        ),
        "article-b.pdf": document(
            [
                [
                    (50, 745, 16, "Title: Synthetic article B"),
                    (50, 715, 11, "Authors: Ravi Das [1]; Noor Ibrahim [2]"),
                    (50, 690, 9, "Journal: Synthetic Research Journal"),
                    (50, 650, 10, "Left-column body."),
                    (320, 650, 10, "Right-column body."),
                    (50, 140, 8, "Correspondence [1]: Ravi Das;"),
                    (50, 128, 8, "ravi.das@example.org"),
                    (320, 140, 8, "Correspondence [2]: Noor Ibrahim;"),
                    (320, 128, 8, "noor.ibrahim@example.org"),
                    (50, 30, 8, "Support: help@example.org"),
                ]
            ]
        ),
        "wrapped.pdf": document(
            [
                [
                    (50, 745, 16, "Title: Encoded name and wrapped address"),
                    (50, 715, 11, "Authors: Eva Müller [1]; Sam Doe [2]"),
                    (50, 150, 8, "Correspondence [1]: Eva Müller;"),
                    (50, 138, 8, "eva.mueller@"),
                    (50, 126, 8, "example.org"),
                ]
            ]
        ),
        "ambiguous.pdf": document(
            [
                [
                    (50, 745, 16, "Title: Ambiguous names"),
                    (50, 715, 11, "Authors: Alex Chen [1]; Alex Chen [2]"),
                    (50, 150, 8, "Correspondence: Alex Chen; shared@example.org"),
                ]
            ]
        ),
        "no-contact.pdf": document(
            [
                [
                    (50, 745, 16, "Title: No correspondence declared"),
                    (50, 715, 11, "Authors: Leena Shah [1]"),
                    (50, 650, 10, "Research without a declared author address."),
                    (50, 70, 8, "References"),
                    (50, 58, 8, "Cited: cited@example.org"),
                    (50, 30, 8, "Support: help@example.org"),
                ]
            ]
        ),
        "scanned.pdf": document([[]], image_only=True),
        "encrypted.pdf": document(
            [[(50, 715, 11, "Authors: Synthetic Person [1]")]], encrypted=True
        ),
        "page-cap.pdf": document(
            [[(50, 715, 11, "Authors: Leena Shah [1]")]]
            + [[(50, 650, 10, "Continuation with no correspondence.")]] * 4
        ),
        "corrupt.pdf": b"%PDF-1.7\nsynthetic broken object\n%%EOF\n",
    }


if __name__ == "__main__":
    import hashlib
    import json

    root = Path(__file__).resolve().parents[3] / "fixtures/pdf"
    root.mkdir(parents=True, exist_ok=True)
    for name, payload in authored().items():
        (root / name).write_bytes(payload)
    print(
        json.dumps({name: hashlib.sha256(value).hexdigest() for name, value in authored().items()})
    )
