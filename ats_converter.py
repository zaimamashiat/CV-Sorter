"""Convert candidate CSV rows into clean, single-column ATS-friendly PDFs."""

import csv
import html
import io
import re
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


FIELD_MATCHERS = {
    "email": ["email address"],
    "nationality": ["bangladeshi national"],
    "name": ["full name"],
    "phone": ["phone number"],
    "age": ["age"],
    "dob": ["date of birth"],
    "address": ["present address"],
    "division": ["which division"],
    "gender": ["gender"],
    "interest": ["area of interest", "2"],
    "portfolio": ["portfolio link"],
    "job1_title": ["designation"],
    "job1_org": ["organization"],
    "job1_start": ["starting date"],
    "job1_end": ["ending date"],
    "job1_desc": ["description of your job"],
    "job2_title": ["designation", "2"],
    "job2_org": ["organization", "2"],
    "job2_start": ["starting date", "2"],
    "job2_end": ["ending date", "2"],
    "job2_desc": ["description of your job", "2"],
    "job3_title": ["designation", "3"],
    "job3_org": ["organization", "3"],
    "job3_start": ["starting date", "3"],
    "job3_end": ["ending date", "3"],
    "job3_desc": ["description of your job", "3"],
    "cert1_name": ["name of the certification or courses"],
    "cert1_duration": ["course duration"],
    "cert1_start": ["course starting date"],
    "cert2_name": ["name of the certification or courses", "2"],
    "cert2_duration": ["course duration", "2"],
    "cert2_start": ["course starting date", "2"],
    "cert3_name": ["name of the certification or courses", "3"],
    "cert3_duration": ["course duration", "3"],
    "cert3_start": ["course starting date", "3"],
    "digital_skills": ["digital skills"],
    "tech_skills": ["technical skills"],
    "lang_skills": ["language skills"],
    "soft_skills": ["soft skills"],
    "train1_name": ["training name"],
    "train1_org": ["training organization"],
    "train1_duration": ["training duration"],
    "train2_name": ["training name", "2"],
    "train2_org": ["training organization", "2"],
    "train2_duration": ["training duration", "2"],
    "train3_name": ["training name", "3"],
    "train3_org": ["training organization", "3"],
    "train3_duration": ["training duration", "3"],
    "bachelors_university": ["university name", "bachelor", "2"],
    "bachelors_subject": ["subject", "2"],
    "bachelors_major": ["major", "2"],
    "bachelors_year": ["year of bachelors", "2"],
    "bachelors_cgpa": ["cgpa", "2"],
    "masters_university": ["university name", "master"],
    "masters_subject": ["master", "subject"],
    "masters_major": ["master", "major"],
    "masters_year": ["year of master"],
    "masters_cgpa": ["cgpa", "3"],
}


def get_trailing_num(header: str):
    raw = str(header).replace("\n", " ").strip().lower()
    match = re.search(r"\b([2-9])\s*$", raw)
    return match.group(1) if match else None


def normalize_header(header: str) -> str:
    raw = str(header).replace("\n", " ").strip().lower()
    trailing_num = get_trailing_num(raw)
    matches = re.findall(r"\(([^)]*[a-zA-Z][^)]*)\)", raw)
    value = matches[-1] if matches else raw
    value = re.sub(r"\?{2,}", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if trailing_num and not value.endswith(trailing_num):
        value = f"{value} {trailing_num}"
    return value


def build_col_map(headers: Sequence[str]) -> Dict[str, str]:
    info = {
        header: {
            "clean": normalize_header(header),
            "trailing_num": get_trailing_num(header),
        }
        for header in headers
    }
    result: Dict[str, str] = {}
    for canonical, matchers in FIELD_MATCHERS.items():
        slot_match = re.search(r"(?:job|cert|train)(\d+)_", canonical)
        slot_num = slot_match.group(1) if slot_match else None
        explicit_num = next((str(m) for m in matchers if str(m).isdigit()), None)
        expected_num = slot_num or explicit_num
        text_matchers = [
            normalize_header(str(m)) for m in matchers if not str(m).isdigit()
        ]
        for header, header_info in info.items():
            clean = header_info["clean"]
            number = header_info["trailing_num"]
            if not all(
                fragment in clean.split() if len(fragment) <= 3 else fragment in clean
                for fragment in text_matchers
            ):
                continue
            if expected_num == "1" and number is not None:
                continue
            if expected_num and expected_num != "1" and number != expected_num:
                continue
            if not expected_num and number is not None:
                continue
            result[canonical] = header
            break
    return result


def clean_value(value) -> str:
    if value is None:
        return ""
    result = str(value).strip()
    parenthesized = re.findall(r"\(([^)]*[A-Za-z][^)]*)\)", result)
    if parenthesized:
        result = parenthesized[-1]
    else:
        result = re.sub(r"\?{2,}", "", result)
        result = re.sub(r"\([^A-Za-z0-9]*\)", "", result)
    return re.sub(r"\s+", " ", result).strip()


def value(row: Dict[str, str], columns: Dict[str, str], key: str) -> str:
    result = clean_value(row.get(columns.get(key, ""), ""))
    if key == "nationality":
        lowered = result.lower()
        if lowered in {"yes", "y", "true", "bangladeshi", "bangladesh"}:
            return "Bangladeshi"
        if lowered in {"no", "n", "false"}:
            return "Non-Bangladeshi"
    return result


def split_items(raw: str) -> List[str]:
    return [
        item.strip(" -\t")
        for item in re.split(r"[,;\n|]+", raw or "")
        if item.strip(" -\t")
    ]


def safe_filename(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    return cleaned or fallback


def fallback_summary(row: Dict[str, str], columns: Dict[str, str]) -> str:
    role = value(row, columns, "interest") or "technology and digital solutions"
    technical = ", ".join(split_items(value(row, columns, "tech_skills"))[:5])
    digital = ", ".join(split_items(value(row, columns, "digital_skills"))[:4])
    soft = ", ".join(split_items(value(row, columns, "soft_skills"))[:3])
    lines = [
        f"Results-driven professional with expertise in {role}, combining strong academic foundations with practical experience."
    ]
    skills = [item for item in (technical, digital) if item]
    if skills:
        lines.append(
            f"Technically proficient in {' and '.join(skills)}, with the ability to deliver across diverse project environments."
        )
    bachelor_subject = value(row, columns, "bachelors_subject")
    bachelor_university = value(row, columns, "bachelors_university")
    if bachelor_subject or bachelor_university:
        degree = "Bachelor's / Honours degree"
        if bachelor_subject:
            degree += f" in {bachelor_subject}"
        if bachelor_university:
            degree += f" from {bachelor_university}"
        lines.append(f"Holds a {degree}.")
    if soft:
        lines.append(f"Demonstrates strong {soft} skills and effective stakeholder collaboration.")
    lines.append(
        "Committed to measurable outcomes through continuous learning, attention to detail, and results-focused execution."
    )
    return " ".join(lines)


def _styles():
    base = getSampleStyleSheet()
    return {
        "name": ParagraphStyle(
            "CVName", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=18, leading=21, alignment=TA_CENTER, spaceAfter=3,
        ),
        "contact": ParagraphStyle(
            "Contact", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8.5, leading=11, alignment=TA_CENTER, spaceAfter=10,
        ),
        "section": ParagraphStyle(
            "Section", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=10, leading=12, spaceBefore=7, spaceAfter=2,
            textColor=colors.black,
        ),
        "body": ParagraphStyle(
            "Body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.2, leading=12.2, spaceAfter=4,
        ),
        "entry": ParagraphStyle(
            "Entry", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.2, leading=12, leftIndent=0, spaceAfter=2,
        ),
        "small": ParagraphStyle(
            "Small", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8.5, leading=11, textColor=colors.HexColor("#333333"),
            spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "Bullet", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9.2, leading=12, leftIndent=10, firstLineIndent=-7,
            bulletIndent=2, spaceAfter=2,
        ),
        "footer": ParagraphStyle(
            "Footer", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.5, alignment=TA_CENTER, textColor=colors.HexColor("#666666"),
        ),
    }


def _escaped(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br/>")


def _section(story: list, title: str, styles: dict):
    story.append(Paragraph(title.upper(), styles["section"]))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.black, spaceAfter=5))


def build_pdf(row: Dict[str, str], columns: Dict[str, str], index: int) -> Tuple[str, bytes]:
    styles = _styles()
    name = value(row, columns, "name") or f"Unknown {index}"
    output = io.BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"{name} - ATS CV",
        author=name,
        subject="ATS-friendly curriculum vitae",
    )
    story = [Paragraph(_escaped(name), styles["name"])]

    address_parts = [
        value(row, columns, "address"),
        value(row, columns, "division"),
    ]
    if any(address_parts):
        address_parts.append("Bangladesh")
    contact = [
        value(row, columns, "email"),
        value(row, columns, "phone"),
        ", ".join(part for part in address_parts if part),
    ]
    story.append(Paragraph(" | ".join(_escaped(item) for item in contact if item), styles["contact"]))

    _section(story, "Professional Summary", styles)
    story.append(Paragraph(_escaped(fallback_summary(row, columns)), styles["body"]))

    jobs = []
    for slot in "123":
        title = value(row, columns, f"job{slot}_title")
        organization = value(row, columns, f"job{slot}_org")
        start = value(row, columns, f"job{slot}_start")
        end = value(row, columns, f"job{slot}_end")
        description = value(row, columns, f"job{slot}_desc")
        if title or organization:
            jobs.append((title, organization, start, end, description))
    if jobs:
        _section(story, "Experience", styles)
        seen = set()
        for title, organization, start, end, description in jobs:
            key = (title.lower(), organization.lower(), start.lower(), end.lower())
            if key in seen:
                continue
            seen.add(key)
            dates = f"{start} - {end or 'Present'}" if start else end
            heading = f"<b>{_escaped(title or organization)}</b>"
            if dates:
                heading += f" | {_escaped(dates)}"
            block = [Paragraph(heading, styles["entry"])]
            if title and organization:
                block.append(Paragraph(f"<i>{_escaped(organization)}</i>", styles["small"]))
            story.append(KeepTogether(block))
            if description:
                story.append(Paragraph(_escaped(description), styles["body"]))

    education = [
        ("Bachelor's / Honours", "bachelors"),
        ("Master's", "masters"),
    ]
    education_blocks = []
    for label, prefix in education:
        university = value(row, columns, f"{prefix}_university")
        subject = value(row, columns, f"{prefix}_subject")
        major = value(row, columns, f"{prefix}_major")
        year = value(row, columns, f"{prefix}_year")
        cgpa = value(row, columns, f"{prefix}_cgpa")
        if any((university, subject, major, year, cgpa)):
            degree = label + (f" in {subject or major}" if subject or major else "")
            meta = " | ".join(
                item for item in (
                    university,
                    f"Year: {year}" if year else "",
                    f"CGPA: {cgpa}" if cgpa else "",
                ) if item
            )
            education_blocks.append((degree, meta))
    if education_blocks:
        _section(story, "Education", styles)
        for degree, meta in education_blocks:
            story.append(Paragraph(f"<b>{_escaped(degree)}</b>", styles["entry"]))
            if meta:
                story.append(Paragraph(_escaped(meta), styles["small"]))

    skill_groups = [
        ("Technical Skills", "tech_skills"),
        ("Digital Skills", "digital_skills"),
        ("Language Skills", "lang_skills"),
        ("Soft Skills", "soft_skills"),
    ]
    available_skills = [
        (label, split_items(value(row, columns, key)))
        for label, key in skill_groups
        if split_items(value(row, columns, key))
    ]
    if available_skills:
        _section(story, "Skills", styles)
        for label, items in available_skills:
            story.append(Paragraph(
                f"<b>{_escaped(label)}:</b> {_escaped('; '.join(items))}",
                styles["body"],
            ))

    certifications = []
    for slot in "123":
        name_value = value(row, columns, f"cert{slot}_name")
        start = value(row, columns, f"cert{slot}_start")
        duration = value(row, columns, f"cert{slot}_duration")
        if name_value and "name of the certification" not in name_value.lower():
            certifications.append((name_value, " | ".join(filter(None, (start, duration)))))
    if certifications:
        _section(story, "Certifications and Courses", styles)
        for item, meta in certifications:
            text = _escaped(item) + (f" ({_escaped(meta)})" if meta else "")
            story.append(Paragraph(text, styles["bullet"], bulletText="-"))

    training = []
    for slot in "123":
        training_name = value(row, columns, f"train{slot}_name")
        organization = value(row, columns, f"train{slot}_org")
        duration = value(row, columns, f"train{slot}_duration")
        if training_name and "training name" not in training_name.lower():
            training.append((training_name, " | ".join(filter(None, (organization, duration)))))
    if training:
        _section(story, "Training", styles)
        for item, meta in training:
            text = _escaped(item) + (f" ({_escaped(meta)})" if meta else "")
            story.append(Paragraph(text, styles["bullet"], bulletText="-"))

    additional = [
        ("Area of Interest", value(row, columns, "interest")),
        ("Gender", value(row, columns, "gender")),
        ("Date of Birth", value(row, columns, "dob")),
        ("Age", value(row, columns, "age")),
        ("Nationality", value(row, columns, "nationality")),
        ("Portfolio", value(row, columns, "portfolio")),
    ]
    additional = [(label, item) for label, item in additional if item]
    if additional:
        _section(story, "Additional Information", styles)
        for label, item in additional:
            story.append(Paragraph(
                f"<b>{_escaped(label)}:</b> {_escaped(item)}",
                styles["body"],
            ))

    def add_footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawCentredString(A4[0] / 2, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    return f"{safe_filename(name, f'candidate_{index}')}_ATS.pdf", output.getvalue()


def parse_csv_rows(content: bytes) -> Tuple[List[Dict[str, str]], Dict[str, str]]:
    decoded = None
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError("Unable to decode CSV file")
    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise ValueError("CSV has no headers")
    rows = list(reader)
    if not rows:
        raise ValueError("CSV has no candidate rows")
    return rows, build_col_map(reader.fieldnames)


def generate_ats_pdfs(content: bytes) -> List[Tuple[str, bytes]]:
    rows, columns = parse_csv_rows(content)
    generated: List[Tuple[str, bytes]] = []
    used_names = set()
    for index, row in enumerate(rows, start=1):
        filename, pdf_bytes = build_pdf(row, columns, index)
        base_name = filename[:-4]
        unique_name = filename
        suffix = 2
        while unique_name.lower() in used_names:
            unique_name = f"{base_name}_{suffix}.pdf"
            suffix += 1
        used_names.add(unique_name.lower())
        generated.append((unique_name, pdf_bytes))
    return generated


def generate_from_csv(csv_path: str, output_dir: str = "output_cv") -> List[Path]:
    """CLI-compatible wrapper based on the user's original script."""
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    generated = []
    for filename, pdf_bytes in generate_ats_pdfs(Path(csv_path).read_bytes()):
        output_path = destination / filename
        output_path.write_bytes(pdf_bytes)
        generated.append(output_path)
    return generated


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        raise SystemExit("Usage: python ats_converter.py candidates.csv")
    files = generate_from_csv(sys.argv[1])
    print(f"Generated {len(files)} ATS PDF(s)")
    for path in files:
        print(path)
