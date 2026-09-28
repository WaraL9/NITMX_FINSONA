"""Sandbox certificate authority for e-Tax invoice signatures (E2-13).

Real e-Tax invoices are signed with certificates from Thai CAs, whose keys we don't have.
The sandbox therefore runs its own CA ("Finsona Sandbox e-Tax CA"), issues each synthetic
seller a signing certificate carrying its tax ID, and signs the sample invoices with XAdES.
The CA certificate is trusted only in sandbox mode (app/parsers/etax_signature.py); the CA
key lives next to it under data/generated (gitignored) and is used only to issue sample certs.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml.xades import XAdESSigner

CA_NAME = "Finsona Sandbox e-Tax CA"
_VALID_FROM = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _usage(*, sign: bool, ca: bool) -> x509.KeyUsage:
    return x509.KeyUsage(digital_signature=sign, content_commitment=sign, key_encipherment=False,
                         data_encipherment=False, key_agreement=False, key_cert_sign=ca, crl_sign=ca,
                         encipher_only=False, decipher_only=False)


def ensure_ca(folder: Path) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    """Load the sandbox CA, creating it on first use (ca.pem is what verifiers trust)."""
    cert_path, key_path = folder / "ca.pem", folder / "ca.key.pem"
    if cert_path.exists() and key_path.exists():
        return (x509.load_pem_x509_certificate(cert_path.read_bytes()),
                serialization.load_pem_private_key(key_path.read_bytes(), password=None))
    folder.mkdir(parents=True, exist_ok=True)
    key = _key()
    subject = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "TH"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Finsona AI (sandbox)"),
                         x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME)])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(_VALID_FROM)
            .not_valid_after(_VALID_FROM + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(_usage(sign=False, ca=True), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, key


def issue(ca: x509.Certificate, ca_key: rsa.RSAPrivateKey, tax_id: str, company: str,
          issuer_name: str | None = None) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    """A seller's signing certificate; the tax ID goes in organizationIdentifier (NTRTH-…)."""
    key = _key()
    subject = x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "TH"),
                         x509.NameAttribute(NameOID.ORGANIZATION_NAME, company),
                         x509.NameAttribute(NameOID.ORGANIZATION_IDENTIFIER, f"NTRTH-{tax_id}"),
                         x509.NameAttribute(NameOID.COMMON_NAME, f"e-Tax signing {tax_id}")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(ca.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(_VALID_FROM)
            .not_valid_after(_VALID_FROM + dt.timedelta(days=1825))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(_usage(sign=True, ca=False), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    return cert, key


def sign(xml: bytes, cert: x509.Certificate, key: rsa.RSAPrivateKey) -> bytes:
    """Enveloped XAdES-BES signature, as the ETDA profile uses."""
    root = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
    signed = XAdESSigner().sign(root, key=key, cert=[cert])
    return etree.tostring(signed, xml_declaration=True, encoding="UTF-8")
