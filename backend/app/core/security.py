"""Envelope encryption service (two-layer KEK/DEK).

Implements the key hierarchy described in Section 13.2 of the requirements:
- Master Key (KEK) derived from APP_SECRET_KEY
- Each credential gets a unique random Data Encryption Key (DEK)
- DEK is encrypted by KEK, data is encrypted by DEK
- Key rotation only re-encrypts DEK wrappers, not actual data
"""

import base64
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = structlog.get_logger()

_REQUIRED_ENVELOPE_KEYS = {"version", "encrypted_dek", "encrypted_data"}


class MalformedEnvelopeError(ValueError):
    """Raised when an envelope blob is missing required keys or has invalid structure."""


def _validate_envelope(envelope: object) -> dict[str, Any]:
    """Validate that the parsed envelope has the required structure.

    Raises MalformedEnvelopeError if the envelope is not a dict or is missing
    required keys.
    """
    if not isinstance(envelope, dict):
        raise MalformedEnvelopeError(f"Envelope must be a JSON object, got {type(envelope).__name__}")
    missing = _REQUIRED_ENVELOPE_KEYS - envelope.keys()
    if missing:
        raise MalformedEnvelopeError(f"Envelope missing required keys: {', '.join(sorted(missing))}")
    for key in ("encrypted_dek", "encrypted_data"):
        if not isinstance(envelope[key], str):
            raise MalformedEnvelopeError(f"Envelope key '{key}' must be a string, got {type(envelope[key]).__name__}")
    return envelope


def _derive_kek(secret_key: str) -> bytes:
    """Derive a Fernet-compatible KEK from the APP_SECRET_KEY.

    Uses PBKDF2 with a fixed salt to produce a deterministic key from the secret.
    The salt is fixed intentionally -- the entropy comes from the secret key itself.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"mailassist-kek-v1",
        iterations=600_000,
    )
    key = kdf.derive(secret_key.encode())
    return base64.urlsafe_b64encode(key)


class EnvelopeEncryption:
    """Two-layer envelope encryption for credential storage.

    Args:
        secret_key: The current APP_SECRET_KEY.
        old_secret_key: Previous APP_SECRET_KEY for key rotation (optional).
    """

    def __init__(self, secret_key: str, old_secret_key: str | None = None):
        self._kek = _derive_kek(secret_key)
        self._kek_fernet = Fernet(self._kek)
        self._kek_id = datetime.now(UTC).strftime("%Y-%m-%d")

        self._old_kek_fernet: Fernet | None = None
        if old_secret_key:
            old_kek = _derive_kek(old_secret_key)
            self._old_kek_fernet = Fernet(old_kek)

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt plaintext using envelope encryption.

        Returns a JSON blob containing the encrypted DEK and encrypted data.
        """
        # Generate a random DEK for this credential
        dek = Fernet.generate_key()
        dek_fernet = Fernet(dek)

        # Encrypt the data with the DEK
        encrypted_data = dek_fernet.encrypt(plaintext.encode())

        # Encrypt the DEK with the KEK
        encrypted_dek = self._kek_fernet.encrypt(dek)

        envelope = {
            "version": 1,
            "kek_id": self._kek_id,
            "encrypted_dek": base64.b64encode(encrypted_dek).decode(),
            "encrypted_data": base64.b64encode(encrypted_data).decode(),
        }
        logger.info("credential_encrypted", kek_id=self._kek_id)
        return json.dumps(envelope).encode()

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt an envelope-encrypted credential.

        Tries the current KEK first, then falls back to the old KEK for rotation.
        """
        envelope = _validate_envelope(json.loads(ciphertext))
        if envelope.get("version") != 1:
            raise MalformedEnvelopeError(f"Unsupported envelope version: {envelope.get('version')}")

        encrypted_dek = base64.b64decode(envelope["encrypted_dek"])
        encrypted_data = base64.b64decode(envelope["encrypted_data"])

        # Try current KEK first
        dek, used_old = self._try_decrypt_dek(encrypted_dek)

        # Decrypt data with the DEK
        dek_fernet = Fernet(dek)
        plaintext = dek_fernet.decrypt(encrypted_data)
        logger.info(
            "credential_decrypted",
            kek_id=envelope.get("kek_id"),
            used_old_key=used_old,
        )
        return plaintext.decode()

    def _try_decrypt_dek(self, encrypted_dek: bytes) -> tuple[bytes, bool]:
        """Attempt to decrypt the DEK with current KEK, then old KEK.

        Returns (dek_bytes, used_old_key).
        """
        try:
            return self._kek_fernet.decrypt(encrypted_dek), False
        except InvalidToken:
            if self._old_kek_fernet is not None:
                try:
                    return self._old_kek_fernet.decrypt(encrypted_dek), True
                except InvalidToken:
                    pass
            raise ValueError("Cannot decrypt credential: invalid key") from None

    def rotate_envelope(self, ciphertext: bytes) -> bytes:
        """Re-encrypt the DEK wrapper with the current KEK.

        The actual data is not re-encrypted -- only the DEK wrapper changes.
        This is used during key rotation.
        """
        envelope = _validate_envelope(json.loads(ciphertext))
        encrypted_dek = base64.b64decode(envelope["encrypted_dek"])

        # Decrypt DEK (may need old KEK)
        dek, used_old = self._try_decrypt_dek(encrypted_dek)

        # Re-encrypt DEK with current KEK
        new_encrypted_dek = self._kek_fernet.encrypt(dek)

        old_kek_id = envelope.get("kek_id")
        envelope["encrypted_dek"] = base64.b64encode(new_encrypted_dek).decode()
        envelope["kek_id"] = self._kek_id

        logger.info(
            "credential_rotated",
            old_kek_id=old_kek_id,
            new_kek_id=self._kek_id,
            used_old_key=used_old,
        )
        return json.dumps(envelope).encode()


# Module-level singleton, initialized during app startup
_encryption: EnvelopeEncryption | None = None


def init_encryption(secret_key: str, old_secret_key: str | None = None) -> None:
    """Initialize the global encryption service."""
    global _encryption
    _encryption = EnvelopeEncryption(secret_key, old_secret_key)


def get_encryption() -> EnvelopeEncryption:
    """Return the global encryption service instance."""
    if _encryption is None:
        raise RuntimeError("Encryption not initialized. Call init_encryption() first.")
    return _encryption


def decrypt_credentials(encrypted: bytes) -> dict[str, str]:
    """Decrypt an encrypted credentials blob to a username/password dict.

    Convenience wrapper around ``get_encryption().decrypt()`` that handles
    the JSON deserialization.  The plaintext is held only briefly in memory.

    Args:
        encrypted: Envelope-encrypted JSON blob (as stored in the DB).

    Returns:
        Dict with at least ``username`` and ``password`` keys.
    """
    result: dict[str, str] = json.loads(get_encryption().decrypt(encrypted))
    return result
