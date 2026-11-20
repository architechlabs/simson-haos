"""One-time SIP credential envelope.

Simson never returns a phone password in clear text. The caller sends a fresh
P-256 public key and receives the password sealed to it (ECDH, HKDF-SHA256,
AES-256-GCM). Only this process can open it, and the key is discarded after use.
This module has no Home Assistant imports so it can be tested on its own.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ALGORITHM = "P256-HKDF-SHA256-AES256GCM"
_INFO = b"simson/sip-credential/one-time/v1"


class CredentialError(Exception):
    """The envelope is malformed or does not belong to this request."""


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise CredentialError("Invalid encrypted credential.")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as error:
        raise CredentialError("Invalid encrypted credential.") from error


def credential_context(tenant_id: str, site_id: str, endpoint_id: str) -> str:
    return f"simson:sip-credential:v1:{tenant_id}:{site_id}:{endpoint_id}"


@dataclass
class OneTimeKey:
    """A throwaway key pair. Use once, then drop it."""

    _private: ec.EllipticCurvePrivateKey

    @classmethod
    def generate(cls) -> "OneTimeKey":
        return cls(ec.generate_private_key(ec.SECP256R1()))

    @classmethod
    def from_private_value(cls, encoded: str) -> "OneTimeKey":
        value = int.from_bytes(_b64decode(encoded), "big")
        return cls(ec.derive_private_key(value, ec.SECP256R1()))

    @property
    def public_key(self) -> str:
        """Uncompressed point, base64url without padding, as the API expects."""
        raw = self._private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def open(self, result: dict, expected_context: str) -> str:
        """Return the password, or raise CredentialError if anything is off."""
        envelope = (result or {}).get("credential_envelope")
        revision = (result or {}).get("revision")
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
            or not isinstance(envelope, dict)
            or envelope.get("algorithm") != ALGORITHM
            or envelope.get("associated_data") != f"{expected_context}:{revision}"
        ):
            raise CredentialError("The encrypted credential does not match this phone.")
        associated = envelope["associated_data"].encode()
        try:
            peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _b64decode(envelope["ephemeral_public_key"]))
            shared = self._private.exchange(ec.ECDH(), peer)
            digest = hashes.Hash(hashes.SHA256())
            digest.update(associated)
            key = HKDF(algorithm=hashes.SHA256(), length=32, salt=digest.finalize(), info=_INFO).derive(shared)
            clear = AESGCM(key).decrypt(_b64decode(envelope["nonce"]), _b64decode(envelope["ciphertext"]), associated)
            return clear.decode("utf-8")
        except (ValueError, KeyError, UnicodeDecodeError) as error:
            raise CredentialError("The encrypted credential could not be opened.") from error
        except Exception as error:  # cryptography raises InvalidTag and friends
            raise CredentialError("The encrypted credential could not be opened.") from error
