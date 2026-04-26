import base64
import io
import os
import re
import shutil
import unicodedata
from datetime import date, datetime

from PIL import Image
from pydantic import BaseModel, Field

try:
    from pypdf import PdfReader

    PDF_TEXT_AVAILABLE = True
except ImportError:
    PDF_TEXT_AVAILABLE = False

try:
    import pytesseract

    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    import fitz

    PDF_OCR_AVAILABLE = True
except ImportError:
    PDF_OCR_AVAILABLE = False


class DocumentResult(BaseModel):
    document_type: str
    is_valid: bool
    issues: list[str]
    warnings: list[str] = Field(default_factory=list)
    extracted_info: dict = Field(default_factory=dict)


def _configure_tesseract() -> None:
    if not OCR_AVAILABLE:
        return

    binary = shutil.which("tesseract")
    if binary:
        pytesseract.pytesseract.tesseract_cmd = binary
        return

    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            tessdata_dir = os.path.join(os.path.dirname(candidate), "tessdata")
            if os.path.isdir(tessdata_dir) and "TESSDATA_PREFIX" not in os.environ:
                os.environ["TESSDATA_PREFIX"] = tessdata_dir
            return


_configure_tesseract()


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return normalized.lower()


def _contains_any(text: str, keywords: list[str]) -> bool:
    haystack = _normalize_text(text)
    return any(_normalize_text(keyword) in haystack for keyword in keywords)


def _filename_stem(filename: str) -> str:
    return (filename or "").rsplit(".", 1)[0]


def _coerce_named_file(value, default_filename: str) -> tuple[str, bytes] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        filename = value.get("filename") or value.get("name") or default_filename
        content = value.get("content") or value.get("content_base64") or value.get("bytes")
        if content is None:
            return None
        content_bytes = _coerce_raw_bytes(content)
        return (str(filename), content_bytes) if content_bytes else None

    content_bytes = _coerce_raw_bytes(value)
    if not content_bytes:
        return None
    return (default_filename, content_bytes)


def _extract_dates(text: str) -> list[date]:
    patterns = [
        (r"\b\d{2}/\d{2}/\d{4}\b", "%d/%m/%Y"),
        (r"\b\d{2}-\d{2}-\d{4}\b", "%d-%m-%Y"),
        (r"\b\d{2}\.\d{2}\.\d{4}\b", "%d.%m.%Y"),
        (r"\b\d{4}/\d{2}/\d{2}\b", "%Y/%m/%d"),
        (r"\b\d{4}-\d{2}-\d{2}\b", "%Y-%m-%d"),
    ]
    found: list[date] = []
    seen: set[date] = set()
    for pattern, fmt in patterns:
        for match in re.finditer(pattern, text or ""):
            try:
                parsed = datetime.strptime(match.group(0), fmt).date()
            except ValueError:
                continue
            if parsed not in seen:
                seen.add(parsed)
                found.append(parsed)
    return found


def _ocr_bytes(content: bytes) -> str:
    if not OCR_AVAILABLE:
        return ""
    try:
        img = Image.open(io.BytesIO(content))
        return pytesseract.image_to_string(img, lang="ara+fra")
    except Exception:
        return ""


def _coerce_raw_bytes(value) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return base64.b64decode(stripped, validate=True)
        except Exception:
            return stripped.encode("utf-8")
    return None


def _looks_like_pdf(content: bytes, filename: str) -> bool:
    return (filename or "").lower().endswith(".pdf") or content[:4] == b"%PDF"


def _extract_pdf_text(content: bytes) -> str:
    if not PDF_TEXT_AVAILABLE:
        return ""
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception:
        return ""

    chunks: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            chunks.append(page_text)
    return "\n".join(chunks)


def _ocr_pdf_bytes(content: bytes) -> str:
    if not OCR_AVAILABLE or not PDF_OCR_AVAILABLE:
        return ""

    chunks: list[str] = []
    try:
        with fitz.open(stream=content, filetype="pdf") as pdf:
            for page in pdf:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))
                page_text = pytesseract.image_to_string(image, lang="ara+fra")
                if page_text.strip():
                    chunks.append(page_text)
    except Exception:
        return ""

    return "\n".join(chunks)


def _extract_document_text(content: bytes, filename: str) -> str:
    if _looks_like_pdf(content, filename):
        chunks = [_extract_pdf_text(content), _ocr_pdf_bytes(content)]
    else:
        chunks = [_ocr_bytes(content)]
    return "\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())


def extract_document_text(content: bytes, filename: str) -> str:
    return _extract_document_text(content, filename)


def detect_document_languages(text: str) -> list[str]:
    source = text or ""
    has_arabic = any("\u0600" <= ch <= "\u06FF" for ch in source)
    normalized = _normalize_text(source)
    has_french = any(
        keyword in normalized
        for keyword in [
            "cin",
            "carte",
            "identite",
            "fiche",
            "paie",
            "salaire",
            "adresse",
            "facture",
            "compromis",
            "vente",
        ]
    )

    if has_arabic and has_french:
        return ["mixed", "ar", "fr"]
    if has_arabic:
        return ["ar"]
    if has_french:
        return ["fr"]
    return ["unknown"]


def _extract_tunisian_cin_numbers(text: str) -> list[str]:
    candidates = re.findall(r"(?:\d[\s\-]*){8,10}", text or "")
    normalized_numbers: list[str] = []
    for candidate in candidates:
        digits = re.sub(r"\D", "", candidate)
        if len(digits) == 8 and digits not in normalized_numbers:
            normalized_numbers.append(digits)
    return normalized_numbers


def _extract_month_year_tokens(text: str) -> list[tuple[int, int]]:
    tokens: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    source = text or ""

    for match in re.finditer(r"\b(0?[1-9]|1[0-2])[/\-.](20\d{2})\b", source):
        month = int(match.group(1))
        year = int(match.group(2))
        if (month, year) not in seen:
            seen.add((month, year))
            tokens.append((month, year))

    for match in re.finditer(r"\b(20\d{2})[/\-.](0?[1-9]|1[0-2])\b", source):
        year = int(match.group(1))
        month = int(match.group(2))
        if (month, year) not in seen:
            seen.add((month, year))
            tokens.append((month, year))

    for parsed_date in _extract_dates(source):
        token = (parsed_date.month, parsed_date.year)
        if token not in seen:
            seen.add(token)
            tokens.append(token)

    normalized = _normalize_text(source)
    month_names = {
        "janvier": 1,
        "january": 1,
        "jan": 1,
        "fevrier": 2,
        "february": 2,
        "feb": 2,
        "mars": 3,
        "march": 3,
        "avril": 4,
        "april": 4,
        "avr": 4,
        "apr": 4,
        "mai": 5,
        "may": 5,
        "juin": 6,
        "june": 6,
        "juillet": 7,
        "july": 7,
        "jul": 7,
        "aout": 8,
        "august": 8,
        "aug": 8,
        "septembre": 9,
        "september": 9,
        "sep": 9,
        "sept": 9,
        "octobre": 10,
        "october": 10,
        "oct": 10,
        "novembre": 11,
        "november": 11,
        "nov": 11,
        "decembre": 12,
        "december": 12,
        "dec": 12,
    }
    for label, month in month_names.items():
        for match in re.finditer(rf"\b{re.escape(label)}\s+(20\d{{2}})\b", normalized):
            year = int(match.group(1))
            if (month, year) not in seen:
                seen.add((month, year))
                tokens.append((month, year))

    return tokens


def _looks_like_cin_document(text: str, filename: str) -> bool:
    combined = f"{text}\n{_filename_stem(filename)}"
    keywords = [
        "cin",
        "carte identite",
        "carte nationale",
        "identite nationale",
        "national identity",
        "identity card",
        "بطاقة",
        "تعريف",
    ]
    return _contains_any(combined, keywords) or bool(_extract_tunisian_cin_numbers(text))


def _looks_like_payslip(text: str, filename: str) -> bool:
    combined = f"{text}\n{_filename_stem(filename)}"
    keywords = [
        "fiche de paie",
        "fiches de paie",
        "bulletin de paie",
        "bulletin salaire",
        "payslip",
        "salary slip",
        "net a payer",
        "salaire brut",
        "salaire net",
        "cnss",
        "retenue",
        "paie",
        "salaire",
        "bulletin",
        "brut",
        "net",
    ]
    if _contains_any(combined, keywords):
        return True

    normalized_filename = _normalize_text(_filename_stem(filename))
    filename_hints = ["fiche", "bulletin", "paie", "salaire", "payslip"]
    return sum(1 for hint in filename_hints if hint in normalized_filename) >= 2


def validate_cin(content: bytes, filename: str) -> DocumentResult:
    issues: list[str] = []
    warnings: list[str] = []
    info: dict = {}

    if len(content) < 1000:
        issues.append("Fichier CIN trop petit - probablement corrompu")
        return DocumentResult(document_type="CIN", is_valid=False, issues=issues)

    text = _extract_document_text(content, filename)
    if not _looks_like_cin_document(text, filename):
        issues.append("Le document fourni ne ressemble pas a une CIN legale tunisienne")
        return DocumentResult(
            document_type="CIN",
            is_valid=False,
            issues=issues,
            warnings=warnings,
            extracted_info=info,
        )

    dates = _extract_dates(text)
    today = date.today()
    future_dates = [item for item in dates if item > date(2000, 1, 1)]
    if future_dates:
        expiry = max(future_dates)
        info["expiry_date"] = str(expiry)
        if expiry < today:
            issues.append(f"CIN expiree depuis le {expiry.strftime('%d/%m/%Y')}")
    else:
        warnings.append("Date d'expiration non detectee - verification manuelle requise")

    cin_numbers = _extract_tunisian_cin_numbers(text)
    if cin_numbers:
        info["cin_number"] = cin_numbers[0]
    else:
        issues.append("Numero CIN (8 chiffres) non detecte")

    return DocumentResult(
        document_type="CIN",
        is_valid=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        extracted_info=info,
    )


def validate_fiches_paie(files: list[tuple[str, bytes]]) -> DocumentResult:
    issues: list[str] = []
    warnings: list[str] = []
    info = {"months_found": [], "type_confidence": "low"}

    if len(files) < 3:
        issues.append(f"{len(files)} fiche(s) fournie(s) - 3 requises (3 derniers mois)")

    today = date.today()
    months_found: set[str] = set()
    payslip_like_count = 0

    for filename, content in files:
        text = _extract_document_text(content, filename)
        if _looks_like_payslip(text, filename):
            payslip_like_count += 1

        month_tokens = _extract_month_year_tokens(f"{text}\n{_filename_stem(filename)}")
        for month, year in month_tokens:
            try:
                month_date = date(year, month, 1)
            except ValueError:
                continue
            delta_months = (today.year - month_date.year) * 12 + (today.month - month_date.month)
            if 0 <= delta_months <= 5:
                months_found.add(f"{month:02d}/{year}")

        if not month_tokens:
            warnings.append(f"Periode de paie non detectee dans {filename}")

    info["months_found"] = sorted(months_found)
    info["type_confidence"] = (
        "high"
        if files and payslip_like_count == len(files)
        else "medium"
        if payslip_like_count >= max(1, len(files) - 1)
        else "low"
    )

    if files and payslip_like_count < len(files):
        issues.append("Au moins un fichier ne ressemble pas a une fiche de paie")

    if len(months_found) < 3 and len(files) >= 3:
        issues.append("Les 3 fiches ne couvrent pas 3 mois distincts recents")

    return DocumentResult(
        document_type="Fiches de paie",
        is_valid=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        extracted_info=info,
    )


def validate_justificatif_domicile(content: bytes, filename: str = "document.pdf") -> DocumentResult:
    issues: list[str] = []
    warnings: list[str] = []
    info: dict = {}
    today = date.today()

    text = _extract_document_text(content, filename)
    combined = f"{text}\n{_filename_stem(filename)}"
    if not _contains_any(
        combined,
        [
            "facture",
            "domicile",
            "electricite",
            "eau",
            "sonede",
            "steg",
            "adresse",
            "justificatif",
            "residence",
        ],
    ):
        issues.append("Le document fourni ne ressemble pas a un justificatif de domicile")
        return DocumentResult(
            document_type="Justificatif domicile",
            is_valid=False,
            issues=issues,
            warnings=warnings,
            extracted_info=info,
        )
    dates = _extract_dates(text)

    recent = [item for item in dates if 0 <= (today - item).days <= 90]
    old = [item for item in dates if (today - item).days > 90]

    if recent:
        document_date = max(recent)
        info["document_date"] = str(document_date)
        info["age_days"] = (today - document_date).days
    elif old:
        document_date = max(old)
        age = (today - document_date).days
        issues.append(
            f"Document date du {document_date.strftime('%d/%m/%Y')} ({age} jours) - maximum autorise : 90 jours"
        )
        info["document_date"] = str(document_date)
    else:
        warnings.append("Date du document non detectee - verification manuelle requise")

    return DocumentResult(
        document_type="Justificatif domicile",
        is_valid=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        extracted_info=info,
    )


def validate_compromis_vente(content: bytes, filename: str = "document.pdf") -> DocumentResult:
    issues: list[str] = []
    warnings: list[str] = []
    info: dict = {}
    text = _extract_document_text(content, filename)
    combined = f"{text}\n{_filename_stem(filename)}"

    if not _contains_any(
        combined,
        [
            "compromis",
            "vente",
            "promesse",
            "acte",
            "bien immobilier",
            "property",
            "deed",
        ],
    ):
        issues.append("Le document fourni ne ressemble pas a un compromis ou acte de vente")
        return DocumentResult(
            document_type="Compromis de vente",
            is_valid=False,
            issues=issues,
            warnings=warnings,
            extracted_info=info,
        )

    if not re.search(r"\d[\d\s]*(?:DT|TND|dinars?)", text or "", re.IGNORECASE):
        issues.append("Montant de vente non detecte dans le compromis")

    dates = _extract_dates(text)
    if not dates:
        warnings.append("Date du compromis non detectee - verification manuelle requise")
    else:
        compromis_date = max(dates)
        info["compromis_date"] = str(compromis_date)
        if (date.today() - compromis_date).days > 90:
            issues.append("Compromis de vente date de plus de 90 jours")

    return DocumentResult(
        document_type="Compromis de vente",
        is_valid=len(issues) == 0,
        issues=issues,
        warnings=warnings,
        extracted_info=info,
    )


def validate_documents(data: dict) -> dict:
    def coerce_file_pairs(value):
        if not value:
            return []
        pairs = []
        for index, item in enumerate(value):
            if isinstance(item, (tuple, list)) and len(item) == 2:
                filename, content = item
                content_bytes = _coerce_raw_bytes(content)
                if content_bytes:
                    pairs.append((str(filename), content_bytes))
            elif isinstance(item, dict):
                filename = item.get("filename") or item.get("name") or f"file_{index}.bin"
                content_bytes = _coerce_raw_bytes(
                    item.get("content") or item.get("content_base64") or item.get("bytes")
                )
                if content_bytes:
                    pairs.append((str(filename), content_bytes))
        return pairs

    required_documents = [
        ("cin_bytes", "CIN", lambda named: validate_cin(named[1], named[0])),
        ("fiches_paie_bytes", "Fiches de paie", validate_fiches_paie),
        ("domicile_bytes", "Justificatif domicile", lambda named: validate_justificatif_domicile(named[1], named[0])),
    ]

    results = []
    missing_documents = []

    for key, label, validator in required_documents:
        normalized = (
            coerce_file_pairs(data.get(key))
            if key == "fiches_paie_bytes"
            else _coerce_named_file(data.get(key), f"{key}.bin")
        )

        if not normalized:
            missing_documents.append(label)
            continue

        results.append(validator(normalized).model_dump())

    return {
        "results": results,
        "missing_documents": missing_documents,
        "documents_complete": len(missing_documents) == 0
        and all(result["is_valid"] for result in results),
    }
