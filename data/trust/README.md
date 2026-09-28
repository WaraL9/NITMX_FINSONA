# Trusted CAs for e-Tax invoice signatures

Put the PEM certificates (`*.pem`) of the certificate authorities the bank trusts for
ETDA e-Tax invoice signing here — typically the roots/intermediates of the Thai CAs
licensed for e-Tax (issuers of the sellers' or service providers' signing certificates).

An uploaded e-Tax XML whose signature chains to one of these is **verified**; a valid
signature from any other CA is **valid_untrusted** (the document is intact, the signer is
not vouched for); a broken signature is refused. See `backend/app/parsers/etax_signature.py`.

This folder ships empty on purpose — no certificates are bundled that we could not
verify ourselves. In sandbox mode the generated "Finsona Sandbox e-Tax CA"
(`data/generated/sandbox_ca/ca.pem`) is trusted as well, so the sample invoices verify.
The path is configurable with `FINSONA_ETAX_TRUST_DIR`.
