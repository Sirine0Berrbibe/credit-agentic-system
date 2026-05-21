import base64
import io
import logging
import os
import re
import shutil
import unicodedata
from datetime import date, datetime

logger = logging.getLogger(__name__)

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
    candidates = [
        binary,
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
        img = img.convert("RGB")
    except Exception as exc:
        logger.warning("Cannot open image for OCR (%d bytes): %s", len(content), exc)
        return ""
    for lang in ("ara+fra", "fra", "eng"):
        try:
            text = pytesseract.image_to_string(img, lang=lang)
            if text.strip():
                return text
        except Exception as exc:
            logger.warning("OCR lang=%s failed: %s", lang, exc)
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
    except Exception as exc:
        logger.warning("PDF OCR failed (%d bytes): %s", len(content), exc)
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


# ─────────────────────────────────────────────────────────────────────────────
# Structured field extractors (French + Arabic)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_cin_birth_date(text: str) -> "date | None":
    """
    Extract birth date from CIN OCR text (French and Arabic).
    Handles OCR noise: spaces around separators, newlines between label and date.
    """
    # Date pattern: allows spaces around separators (OCR artefact on real cards)
    _D = r"\d{1,2}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{4}"
    _D4 = r"\d{4}\s*[/.\-]\s*\d{1,2}\s*[/.\-]\s*\d{1,2}"

    labeled_patterns = [
        # French labels — label may be separated from date by newline
        rf"n[eé][e]?\s+le\s*:?\s*({_D})",
        rf"date\s+de\s+naissance\s*[:\s]*\n?\s*({_D})",
        rf"naissance\s*:?\s*\n?\s*({_D})",
        # Arabic labels — the date is often on the next line on real CINs
        rf"تاريخ\s*الميلاد\s*:?\s*\n?\s*({_D})",
        rf"تاريخ\s*الميلاد\s*:?\s*\n?\s*({_D4})",
        rf"الميلاد\s*:?\s*\n?\s*({_D})",
        rf"تاريخ\s*الولادة\s*:?\s*\n?\s*({_D})",
        rf"تاريخ\s*الميلاد\s*/\s*Date\s+de\s+naissance\s*[:\s]*\n?\s*({_D})",
    ]
    date_formats_dmy = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]
    date_formats_ymd = ["%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"]

    def _try_parse(raw: str) -> "date | None":
        clean = re.sub(r"\s+", "", raw)  # remove OCR-inserted spaces
        today = date.today()
        for fmt in date_formats_dmy + date_formats_ymd + ["%m/%d/%Y"]:
            try:
                parsed = datetime.strptime(clean, fmt).date()
                if 1930 <= parsed.year <= today.year and parsed <= today:
                    return parsed
            except ValueError:
                continue
        return None

    for pattern in labeled_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result = _try_parse(m.group(1))
            if result:
                return result

    # Fallback: any date in the text that is a plausible birth date (age 18–90)
    today = date.today()
    min_year = today.year - 90
    max_year = today.year - 18
    for m in re.finditer(rf"({_D})", text):
        result = _try_parse(m.group(1))
        if result and min_year <= result.year <= max_year:
            return result
    for m in re.finditer(rf"({_D4})", text):
        result = _try_parse(m.group(1))
        if result and min_year <= result.year <= max_year:
            return result
    return None


def _extract_cin_gender(text: str) -> "str | None":
    """Extract gender M/F from CIN text (French + Arabic)."""
    normalized = _normalize_text(text)
    # French
    if re.search(r"\bmasculin\b", normalized):
        return "M"
    if re.search(r"\bfeminin\b|\bfeminine\b", normalized):
        return "F"
    if re.search(r"(?:sexe|genre)\s*:?\s*m\b", normalized):
        return "M"
    if re.search(r"(?:sexe|genre)\s*:?\s*f\b", normalized):
        return "F"
    # Arabic: ذكر = male, أنثى / انثى = female
    if "ذكر" in text:
        return "M"
    if "أنثى" in text or "انثى" in text:
        return "F"
    return None


def _extract_cin_fullname(text: str) -> "tuple[str | None, str | None]":
    """
    Returns (last_name, first_name) extracted from CIN OCR text.
    Supports French labels (Nom / Prénom) and Arabic (اللقب / الاسم).
    """
    last_name: "str | None" = None
    first_name: "str | None" = None

    # French: "Nom :" then capital letters
    m = re.search(
        r"(?:^|\b)nom\s*:?\s*([A-ZÉÈÊËÀÂÙÛÎÏÔŒÆ][A-ZÉÈÊËÀÂÙÛÎÏÔŒÆ\s\-]{1,40})",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if m:
        last_name = m.group(1).strip().rstrip()[:40]

    m = re.search(
        r"(?:^|\b)pr[eé]nom\s*:?\s*([A-ZÉÈÊËÀÂÙÛÎÏÔŒÆa-z][A-ZÉÈÊËÀÂÙÛÎÏÔŒÆa-zéèêëàâùûîïôœæ\s\-]{1,40})",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if m:
        first_name = m.group(1).strip()[:40]

    # Arabic: اللقب / الاسم العائلي = last name, الاسم = first name
    if not last_name:
        m = re.search(r"(?:اللقب|الاسم\s*العائلي)\s*:?\s*([؀-ۿ\s]{2,30})", text)
        if m:
            last_name = m.group(1).strip()[:40]
    if not first_name:
        m = re.search(r"(?:الاسم\s*الأول|الاسم)\s*:?\s*([؀-ۿ\s]{2,30})", text)
        if m:
            first_name = m.group(1).strip()[:40]

    return last_name, first_name


def _extract_payslip_salary(text: str) -> dict:
    """
    Extract net salary, gross salary, employer name and employee name
    from payslip OCR text (French + Arabic).
    Returns a dict with float or None values.
    """
    result: dict = {
        "net_salary": None,
        "gross_salary": None,
        "employer_name": None,
        "employee_name": None,
        "cnss_number": None,
    }

    def _parse_amount(raw: str) -> "float | None":
        """Clean and convert an amount string to float."""
        cleaned = re.sub(r"[^\d.,]", "", raw)
        # Handle comma as decimal separator (French format: 1 234,56)
        if "," in cleaned and "." in cleaned:
            cleaned = cleaned.replace(",", "")
        elif "," in cleaned and cleaned.count(",") == 1 and len(cleaned.split(",")[-1]) <= 3:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
        try:
            val = float(cleaned)
            # Sanity: salary between 100 DT and 100 000 DT
            return val if 100 <= val <= 100_000 else None
        except ValueError:
            return None

    # Net salary — French
    for pattern in [
        r"net\s+[àa]\s+payer\s*:?\s*([\d\s.,]+)",
        r"salaire\s+net\s*:?\s*([\d\s.,]+)",
        r"net\s+imposable\s*:?\s*([\d\s.,]+)",
        r"total\s+net\s*:?\s*([\d\s.,]+)",
        r"montant\s+net\s*:?\s*([\d\s.,]+)",
        r"net\s+pay(?:able)?\s*:?\s*([\d\s.,]+)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = _parse_amount(m.group(1))
            if val:
                result["net_salary"] = val
                break

    # Net salary — Arabic
    if result["net_salary"] is None:
        for pattern in [
            r"(?:الأجر|الراتب)\s*الصافي\s*:?\s*([\d\s.,]+)",
            r"صافي\s*(?:الأجر|الراتب|الدفع)?\s*:?\s*([\d\s.,]+)",
            r"المبلغ\s*الصافي\s*:?\s*([\d\s.,]+)",
        ]:
            m = re.search(pattern, text)
            if m:
                val = _parse_amount(m.group(1))
                if val:
                    result["net_salary"] = val
                    break

    # Gross salary — French
    for pattern in [
        r"salaire\s+brut\s*:?\s*([\d\s.,]+)",
        r"brut\s+imposable\s*:?\s*([\d\s.,]+)",
        r"montant\s+brut\s*:?\s*([\d\s.,]+)",
        r"salaire\s+de\s+base\s*:?\s*([\d\s.,]+)",
        r"traitement\s+de\s+base\s*:?\s*([\d\s.,]+)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = _parse_amount(m.group(1))
            if val:
                result["gross_salary"] = val
                break

    # Gross salary — Arabic
    if result["gross_salary"] is None:
        for pattern in [
            r"(?:الأجر|الراتب)\s*الإجمالي\s*:?\s*([\d\s.,]+)",
            r"إجمالي\s*(?:الأجر|الراتب)?\s*:?\s*([\d\s.,]+)",
        ]:
            m = re.search(pattern, text)
            if m:
                val = _parse_amount(m.group(1))
                if val:
                    result["gross_salary"] = val
                    break

    # Employer name — French
    for pattern in [
        r"(?:employeur|soci[eé]t[eé]|[eé]tablissement|entreprise|organisme)\s*:?\s*(.{3,60}?)(?:\n|$)",
        r"(?:raison\s+sociale)\s*:?\s*(.{3,60}?)(?:\n|$)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m:
            name = m.group(1).strip().rstrip(".,;:")[:60]
            if len(name) > 2:
                result["employer_name"] = name
                break

    # Employer name — Arabic
    if not result["employer_name"]:
        m = re.search(
            r"(?:صاحب\s*العمل|المؤسسة|الشركة|المنشأة)\s*:?\s*([؀-ۿ\s\w]{3,50})",
            text,
        )
        if m:
            result["employer_name"] = m.group(1).strip()[:60]

    # Employee name
    for pattern in [
        r"(?:salari[eé]|employ[eé]|agent|nom\s+et\s+pr[eé]nom|matricule\s+salari[eé])\s*:?\s*([A-ZÉÈÊËÀÂ][A-Za-zÉÈÊËÀÂéèêëàâ\s\-]{2,50})",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            result["employee_name"] = m.group(1).strip()[:50]
            break

    # CNSS number
    m = re.search(r"(?:cnss|n°\s*cnss|immatriculation\s+cnss)\s*:?\s*(\d[\d\s]{5,14})", text, re.IGNORECASE)
    if m:
        result["cnss_number"] = re.sub(r"\s", "", m.group(1))

    return result


def _extract_payslip_employment_date(text: str) -> "date | None":
    """Extract employment start date from payslip (date d'entrée / date d'embauche)."""
    patterns = [
        r"date\s+d['\s]entr[eé]e?\s*:?\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})",
        r"date\s+d['\s]embauche\s*:?\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})",
        r"date\s+de\s+recrutement\s*:?\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})",
        r"tit?ularisation?\s*:?\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})",
        # Arabic: تاريخ الإلتحاق / تاريخ التوظيف
        r"تاريخ\s*(?:الإلتحاق|التوظيف|الالتحاق)\s*:?\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4})",
    ]
    date_formats = ["%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]
    today = date.today()
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1)
            for fmt in date_formats:
                try:
                    parsed = datetime.strptime(raw, fmt).date()
                    if 1970 <= parsed.year <= today.year and parsed <= today:
                        return parsed
                except ValueError:
                    continue
    return None


def _extract_tunisian_cin_numbers(text: str) -> list[str]:
    # Match exactly 8 digits, possibly separated by spaces/hyphens but NOT newlines,
    # and not adjacent to more digits (avoids matching phone numbers or date fragments).
    candidates = re.findall(r"(?<!\d)((?:\d[ \t\-]?){8})(?![ \t\-]?\d)", text or "")
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


def _looks_like_cin_document(text: str) -> bool:
    """
    Retourne True si le texte OCR contient des indicateurs d'une CIN tunisienne.
    Permissif pour compenser les artefacts OCR des vraies cartes.
    """
    if not (text or "").strip():
        return False

    normalized = _normalize_text(text)
    has_arabic = any("؀" <= ch <= "ۿ" for ch in text)

    # Titre officiel français (CARTE NATIONALE D'IDENTITE)
    if _contains_any(normalized, [
        "carte nationale",
        "identite nationale",
        "national identity",
        "identity card",
        "carte d identite",
        "cni",
    ]):
        return True

    # République tunisienne — présente sur tous documents officiels tunisiens
    if _contains_any(normalized, ["republique tunisienne", "tunisie"]):
        # + au moins un indicateur supplémentaire
        if has_arabic or bool(_extract_tunisian_cin_numbers(text)):
            return True

    # Marqueurs arabes CIN — l'un ou l'autre suffit (OCR peut manquer un mot)
    arabic_cin_markers = ["بطاقة", "تعريف", "الوطنية", "هوية", "تاريخ الميلاد", "تاريخ الانتهاء"]
    if sum(1 for m in arabic_cin_markers if m in text) >= 1:
        # + numéro 8 chiffres OU date plausible
        has_cin_num = bool(_extract_tunisian_cin_numbers(text))
        has_date = bool(re.search(r"\b\d{2}[/.\- ]\d{2}[/.\- ]\d{4}\b", text))
        if has_cin_num or has_date:
            return True

    # Numéro CIN seul + texte arabe (combinaison forte)
    if has_arabic and bool(_extract_tunisian_cin_numbers(text)):
        return True

    # "cin" explicitement dans le texte OCR + arabe
    if "cin" in normalized and has_arabic:
        return True

    return False


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


def validate_cin(files: list[tuple[str, bytes]]) -> DocumentResult:
    """
    Valide la CIN tunisienne.

    Args:
        files: Liste de fichiers CIN.
               files[0] = recto (obligatoire) — contient la photo, le nom, le numéro CIN.
               files[1] = verso (optionnel) — contient l'adresse et la date d'expiration.

    La date d'expiration se trouvant sur le verso, un avertissement (non bloquant)
    est émis si le verso n'est pas fourni.
    """
    issues: list[str] = []
    warnings: list[str] = []
    info: dict = {}

    if not files:
        issues.append("Aucun fichier CIN fourni")
        return DocumentResult(document_type="CIN", is_valid=False, issues=issues)

    recto_filename, recto_content = files[0]
    verso_filename, verso_content = files[1] if len(files) > 1 else (None, None)

    # ── Contrôle de taille (corruption) ─────────────────────────────────────
    if len(recto_content) < 1000:
        issues.append(
            "Fichier CIN recto trop petit — probablement corrompu ou tronqué "
            f"({len(recto_content)} octets)"
        )
        return DocumentResult(document_type="CIN", is_valid=False, issues=issues)

    # ── Extraction OCR ───────────────────────────────────────────────────────
    recto_text = _extract_document_text(recto_content, recto_filename)
    verso_text = _extract_document_text(verso_content, verso_filename) if verso_content else ""

    # ── Vérification que c'est réellement une CIN ───────────────────────────
    if not recto_text.strip() and not verso_text.strip():
        issues.append(
            "Impossible d'extraire le texte du document — "
            "vérifiez la qualité de l'image (résolution ≥ 150 DPI) "
            "et que Tesseract OCR est installé"
        )
        return DocumentResult(document_type="CIN", is_valid=False, issues=issues)

    all_text = f"{recto_text}\n{verso_text}".strip()
    if not _looks_like_cin_document(all_text):
        issues.append(
            "Ce document ne semble pas être une CIN tunisienne — "
            "veuillez soumettre votre Carte Nationale d'Identité (recto, "
            "et verso pour la date d'expiration)"
        )
        return DocumentResult(
            document_type="CIN",
            is_valid=False,
            issues=issues,
            warnings=warnings,
            extracted_info=info,
        )

    # ── Numéro CIN (recto) ───────────────────────────────────────────────────
    cin_numbers = _extract_tunisian_cin_numbers(recto_text or all_text)
    if cin_numbers:
        info["cin_number"] = cin_numbers[0]
    else:
        issues.append(
            "Numéro CIN (8 chiffres) non détecté sur le recto — "
            "qualité d'image insuffisante ou document partiellement occulté"
        )

    # ── Date de naissance ────────────────────────────────────────────────────
    today = date.today()
    birth_date = _extract_cin_birth_date(all_text)
    if birth_date:
        info["birth_date"] = str(birth_date)
        age_years = (today - birth_date).days / 365.25
        info["age_years"] = round(age_years, 1)
        # DAYS_BIRTH: negative integer as expected by the ML model
        info["days_birth"] = -(today - birth_date).days
    else:
        warnings.append(
            "Date de naissance non détectée (cherché: 'né le', 'date de naissance', "
            "'تاريخ الميلاد') — extraction LLM requise"
        )

    # ── Nom et prénom ────────────────────────────────────────────────────────
    last_name, first_name = _extract_cin_fullname(all_text)
    if last_name:
        info["last_name"] = last_name
    if first_name:
        info["first_name"] = first_name
    if last_name and first_name:
        info["full_name"] = f"{first_name} {last_name}"

    # ── Genre ────────────────────────────────────────────────────────────────
    gender = _extract_cin_gender(all_text)
    if gender:
        info["gender"] = gender
        info["code_gender"] = gender  # ML model feature name

    # ── Date d'expiration (verso) ────────────────────────────────────────────
    # La date d'expiration est imprimée sur le VERSO de la CIN tunisienne.
    expiry_source = verso_text if verso_text else all_text
    future_dates = [
        d for d in _extract_dates(expiry_source)
        if d > date(2020, 1, 1)  # CIN tunisienne: validité 10 ans, donc >= 2020
    ]

    if future_dates:
        expiry = max(future_dates)
        info["expiry_date"] = str(expiry)
        if expiry < today:
            issues.append(f"CIN expirée depuis le {expiry.strftime('%d/%m/%Y')}")
    elif verso_content:
        warnings.append(
            "Date d'expiration non détectée sur le verso — vérification manuelle requise"
        )
    else:
        warnings.append(
            "Verso CIN non fourni — la date d'expiration ne peut pas être vérifiée. "
            "Joignez le verso pour une validation complète."
        )

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
    info: dict = {"months_found": [], "type_confidence": "low"}

    if len(files) < 3:
        issues.append(f"{len(files)} fiche(s) fournie(s) - 3 requises (3 derniers mois)")

    today = date.today()
    months_found: set[str] = set()
    payslip_like_count = 0

    # Aggregate salary/employer across all payslips; take the most recent reliable value
    all_net_salaries: list[float] = []
    all_gross_salaries: list[float] = []
    all_employer_names: list[str] = []
    all_employee_names: list[str] = []
    all_cnss_numbers: list[str] = []
    employment_start_dates: list[date] = []

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

        # Structured extraction
        salary_info = _extract_payslip_salary(text)
        if salary_info["net_salary"] is not None:
            all_net_salaries.append(salary_info["net_salary"])
        if salary_info["gross_salary"] is not None:
            all_gross_salaries.append(salary_info["gross_salary"])
        if salary_info["employer_name"]:
            all_employer_names.append(salary_info["employer_name"])
        if salary_info["employee_name"]:
            all_employee_names.append(salary_info["employee_name"])
        if salary_info["cnss_number"]:
            all_cnss_numbers.append(salary_info["cnss_number"])

        emp_date = _extract_payslip_employment_date(text)
        if emp_date:
            employment_start_dates.append(emp_date)

    info["months_found"] = sorted(months_found)
    info["type_confidence"] = (
        "high"
        if files and payslip_like_count == len(files)
        else "medium"
        if payslip_like_count >= max(1, len(files) - 1)
        else "low"
    )

    # Salary: use the median to avoid OCR outliers
    if all_net_salaries:
        sorted_net = sorted(all_net_salaries)
        median_net = sorted_net[len(sorted_net) // 2]
        info["monthly_net_salary"] = median_net
        info["annual_income"] = round(median_net * 12, 2)  # AMT_INCOME_TOTAL equivalent

        # Detect inconsistency across payslips (>15% variance = suspicious)
        if len(all_net_salaries) > 1:
            salary_range = max(all_net_salaries) - min(all_net_salaries)
            if salary_range / median_net > 0.15:
                warnings.append(
                    f"Salaires variables entre fiches: min={min(all_net_salaries):.0f} "
                    f"max={max(all_net_salaries):.0f} DT — vérification requise"
                )
    else:
        warnings.append(
            "Salaire net non détecté (cherché: 'net à payer', 'salaire net', "
            "'صافي الراتب') — extraction LLM requise"
        )

    if all_gross_salaries:
        sorted_gross = sorted(all_gross_salaries)
        info["monthly_gross_salary"] = sorted_gross[len(sorted_gross) // 2]

    # Employer: take the most frequent name
    if all_employer_names:
        info["employer_name"] = max(set(all_employer_names), key=all_employer_names.count)

    if all_employee_names:
        info["employee_name"] = all_employee_names[0]

    if all_cnss_numbers:
        info["cnss_number"] = all_cnss_numbers[0]

    # Employment start date → DAYS_EMPLOYED
    if employment_start_dates:
        emp_start = min(employment_start_dates)  # earliest date = actual start
        info["employment_start_date"] = str(emp_start)
        info["days_employed"] = -(today - emp_start).days  # negative for ML model
        info["employment_years"] = round((today - emp_start).days / 365.25, 1)

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
        # Wrap a single dict/tuple/bytes into a list so the loop below works uniformly
        if isinstance(value, (dict, bytes, bytearray, str)):
            value = [value]
        elif isinstance(value, tuple) and len(value) == 2:
            value = [value]
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
        ("cin_bytes", "CIN", validate_cin),
        ("fiches_paie_bytes", "Fiches de paie", validate_fiches_paie),
        ("domicile_bytes", "Justificatif domicile", lambda named: validate_justificatif_domicile(named[1], named[0])),
    ]

    results = []
    missing_documents = []

    for key, label, validator in required_documents:
        normalized = (
            coerce_file_pairs(data.get(key))
            if key in ("cin_bytes", "fiches_paie_bytes")
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
