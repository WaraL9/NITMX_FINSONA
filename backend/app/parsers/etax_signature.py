"""XAdES signature check for ETDA e-Tax invoice XML (E2-13).

A real e-Tax invoice is signed by the seller (or a certified service provider) with a
certificate from a Thai CA. Four outcomes:

  verified          the signature is valid and the signer's certificate chains to a CA the bank
                    trusts (PEM files in settings.etax_trust_dir; the sandbox CA as well in
                    sandbox mode)
  valid_untrusted   the document is exactly as signed, but the signer's CA is not trusted here
  invalid           the document was changed after signing (or the signature is malformed) —
                    the upload is refused
  absent            unsigned: SME-provided evidence, flagged

Validity is checked at the current time; a signer certificate that has since expired
therefore reads as valid_untrusted rather than verified.
"""

from __future__ import annotations

import base64
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import InvalidInput, InvalidSignature
from signxml.exceptions import InvalidCertificate, InvalidDigest
from signxml.xades import XAdESVerifier

from app.config import settings

DSIG = "http://www.w3.org/2000/09/xmldsig#"


@dataclass
class SignatureCheck:
    status: str  # verified | valid_untrusted | invalid | absent
    signer: str | None = None
    signer_tax_id: str | None = None
    issuer: str | None = None
    detail: str | None = None


def trust_dirs() -> list[Path]:
    dirs = [settings.etax_trust_dir]
    if settings.connector_mode == "sandbox":
        dirs.append(settings.data_dir / "generated" / "sandbox_ca")
    return dirs


_bundle_cache: dict[str, str] = {}


def _trust_bundle() -> str | None:
    """All trusted CA certificates in one PEM file (signxml wants a path)."""
    pems = sorted(p for d in trust_dirs() if d.is_dir() for p in d.glob("*.pem") if not p.name.endswith(".key.pem"))
    if not pems:
        return None
    blob = b"".join(p.read_bytes().strip() + b"\n" for p in pems)
    digest = hashlib.sha256(blob).hexdigest()
    if digest not in _bundle_cache:
        path = Path(tempfile.gettempdir()) / f"finsona-etax-trust-{digest[:16]}.pem"
        path.write_bytes(blob)
        _bundle_cache[digest] = str(path)
    return _bundle_cache[digest]


def _name(n: x509.Name, oid) -> str | None:
    attrs = n.get_attributes_for_oid(oid)
    return str(attrs[0].value) if attrs else None


def _tax_id(cert: x509.Certificate) -> str | None:
    """Thai signing certificates carry the tax ID as organizationIdentifier (NTRTH-…) or serialNumber."""
    for oid in (NameOID.ORGANIZATION_IDENTIFIER, NameOID.SERIAL_NUMBER):
        v = _name(cert.subject, oid)
        digits = "".join(ch for ch in (v or "") if ch.isdigit())
        if len(digits) >= 13:
            return digits[:13]
    return None


def check(data: bytes) -> SignatureCheck:
    try:
        root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as e:
        return SignatureCheck("invalid", detail=f"unreadable XML: {e}")
    sig = root.find(f".//{{{DSIG}}}Signature")
    if sig is None:
        return SignatureCheck("absent")
    der = sig.find(f".//{{{DSIG}}}X509Certificate")
    if der is None or not (der.text or "").strip():
        return SignatureCheck("invalid", detail="signature carries no signer certificate")
    try:
        cert = x509.load_der_x509_certificate(base64.b64decode("".join(der.text.split())))
    except ValueError as e:
        return SignatureCheck("invalid", detail=f"bad signer certificate: {e}")
    who = SignatureCheck("absent", signer=_name(cert.subject, NameOID.COMMON_NAME), signer_tax_id=_tax_id(cert),
                         issuer=_name(cert.issuer, NameOID.COMMON_NAME))

    bundle = _trust_bundle()
    if bundle:
        try:
            XAdESVerifier().verify(data, ca_pem_file=bundle)
            who.status = "verified"
            return who
        except InvalidCertificate:
            pass  # the chain is not trusted here; still check the document is intact below
        except (InvalidDigest, InvalidSignature, InvalidInput) as e:
            who.status, who.detail = "invalid", str(e)
            return who
    try:
        XAdESVerifier().verify(data, x509_cert=cert)
        who.status = "valid_untrusted"
    except (InvalidDigest, InvalidSignature, InvalidInput, InvalidCertificate) as e:
        who.status, who.detail = "invalid", str(e)
    return who
