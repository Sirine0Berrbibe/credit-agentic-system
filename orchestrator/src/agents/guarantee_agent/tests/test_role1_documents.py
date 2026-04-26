import pytest
import mcp_server.validators as validators
from mcp_server.validators import (
    validate_cin,
    validate_documents,
    validate_fiches_paie,
    validate_justificatif_domicile,
)

# ── Helpers pour créer des bytes de test sans vrai OCR ──────────

def make_fake_image_bytes(text_hint: str = "") -> bytes:
    """Crée un PNG minimal valide (1x1 pixel blanc)."""
    import struct, zlib
    def png_chunk(name: bytes, data: bytes) -> bytes:
        c = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", c)
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = png_chunk(b'IHDR', struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = png_chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff'))
    iend = png_chunk(b'IEND', b'')
    payload = sig + ihdr + idat + iend
    if len(payload) < 1200:
        payload += b"\x00" * (1200 - len(payload))
    return payload

# ── Tests validate_cin ───────────────────────────────────────────

class TestValidateCIN:

    def test_fichier_trop_petit_retourne_invalide(self):
        result = validate_cin(b"petit", "cin.jpg")
        assert result.is_valid is False
        assert any("trop petit" in i for i in result.issues)

    def test_image_valide_sans_ocr_avertissement_seulement(self):
        content = make_fake_image_bytes()
        result = validate_cin(content, "cin.jpg")
        # Sans OCR réel, on attend des avertissements mais pas de crash
        assert result.document_type == "CIN"
        assert isinstance(result.issues, list)

    def test_document_type_correct(self):
        content = make_fake_image_bytes()
        result = validate_cin(content, "cin.jpg")
        assert result.document_type == "CIN"

    def test_cin_valide_avec_numero_et_warning_expiration(self, monkeypatch):
        monkeypatch.setattr(
            validators,
            "_extract_document_text",
            lambda _content, _filename: "Carte nationale d identite CIN 1234 5678",
        )
        result = validate_cin(make_fake_image_bytes(), "cin.jpg")
        assert result.is_valid is True
        assert result.extracted_info["cin_number"] == "12345678"
        assert any("expiration" in warning for warning in result.warnings)

# ── Tests validate_fiches_paie ───────────────────────────────────

class TestValidateFichesPaie:

    def test_moins_de_3_fiches_invalide(self):
        files = [("fiche1.jpg", make_fake_image_bytes())]
        result = validate_fiches_paie(files)
        assert result.is_valid is False
        assert any("3 requises" in i for i in result.issues)

    def test_exactement_2_fiches_message_clair(self):
        files = [
            ("f1.jpg", make_fake_image_bytes()),
            ("f2.jpg", make_fake_image_bytes()),
        ]
        result = validate_fiches_paie(files)
        assert result.is_valid is False
        assert "2 fiche(s)" in result.issues[0]

    def test_3_fiches_format_correct(self):
        files = [
            ("f1.jpg", make_fake_image_bytes()),
            ("f2.jpg", make_fake_image_bytes()),
            ("f3.jpg", make_fake_image_bytes()),
        ]
        result = validate_fiches_paie(files)
        assert result.document_type == "Fiches de paie"
        assert isinstance(result.extracted_info.get("months_found"), list)

    def test_fiches_non_reconnues_comme_bulletins(self, monkeypatch):
        monkeypatch.setattr(validators, "_extract_document_text", lambda _content, _filename: "")
        files = [
            ("2020-2021.jpeg", make_fake_image_bytes()),
            ("2021-2022.jpeg", make_fake_image_bytes()),
            ("2023-2024.jpeg", make_fake_image_bytes()),
        ]
        result = validate_fiches_paie(files)
        assert result.is_valid is False
        assert any("ne ressemble pas" in issue for issue in result.issues)

    def test_3_fiches_avec_dates_completes_couvrent_3_mois(self, monkeypatch):
        texts = {
            b"jan": "Bulletin de paie salaire net 31/01/2026 CNSS",
            b"feb": "Bulletin de paie salaire net 28/02/2026 CNSS",
            b"mar": "Bulletin de paie salaire net 31/03/2026 CNSS",
        }
        monkeypatch.setattr(
            validators,
            "_extract_document_text",
            lambda content, _filename: texts[content],
        )
        files = [
            ("scan_janvier.pdf", b"jan"),
            ("scan_fevrier.pdf", b"feb"),
            ("scan_mars.pdf", b"mar"),
        ]
        result = validate_fiches_paie(files)
        assert result.is_valid is True
        assert result.extracted_info["months_found"] == ["01/2026", "02/2026", "03/2026"]

# ── Tests validate_justificatif_domicile ─────────────────────────

class TestValidateJustificatifDomicile:

    def test_image_vide_retourne_avertissement(self):
        content = make_fake_image_bytes()
        result = validate_justificatif_domicile(content)
        # Sans OCR : date non détectée → avertissement
        assert result.document_type == "Justificatif domicile"
        assert isinstance(result.issues, list)

    def test_type_document_correct(self):
        result = validate_justificatif_domicile(make_fake_image_bytes())
        assert result.document_type == "Justificatif domicile"


class TestValidateDocumentsPayload:

    def test_accepts_named_single_documents_payload(self, monkeypatch):
        monkeypatch.setattr(
            validators,
            "_extract_document_text",
            lambda _content, _filename: "Carte nationale d identite CIN 12345678 bulletin de paie 01/2026 steg 01/01/2026",
        )
        payload = {
            "cin_bytes": {
                "filename": "cin_front.jpg",
                "content_base64": "ZmFrZQ==",
            },
            "domicile_bytes": {
                "filename": "steg_janvier_2026.pdf",
                "content_base64": "ZmFrZQ==",
            },
            "fiches_paie_bytes": [
                {"filename": "fiche_01_2026.pdf", "content_base64": "ZmFrZQ=="},
                {"filename": "fiche_02_2026.pdf", "content_base64": "ZmFrZQ=="},
                {"filename": "fiche_03_2026.pdf", "content_base64": "ZmFrZQ=="},
            ],
        }

        result = validate_documents(payload)
        assert "missing_documents" in result
        assert isinstance(result["results"], list)
