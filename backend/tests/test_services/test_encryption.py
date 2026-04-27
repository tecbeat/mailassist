"""Tests for envelope encryption (test area 1).

Covers: encrypt -> decrypt roundtrip, key rotation, invalid key handling.
"""

from unittest.mock import patch

import pytest

from app.core.security import EnvelopeEncryption, MalformedEnvelopeError, init_encryption, get_encryption


class TestEnvelopeEncryption:
    """Test the two-layer KEK/DEK encryption service."""

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypting then decrypting returns the original plaintext."""
        enc = EnvelopeEncryption(secret_key="a" * 32)
        plaintext = "my-secret-api-key-12345"

        ciphertext = enc.encrypt(plaintext)
        result = enc.decrypt(ciphertext)

        assert result == plaintext

    def test_encrypt_returns_bytes(self):
        """Encrypted output is bytes, not str."""
        enc = EnvelopeEncryption(secret_key="a" * 32)
        ciphertext = enc.encrypt("test")
        assert isinstance(ciphertext, bytes)

    def test_different_encryptions_differ(self):
        """Two encryptions of the same plaintext produce different ciphertext (unique DEK)."""
        enc = EnvelopeEncryption(secret_key="b" * 32)
        c1 = enc.encrypt("same-data")
        c2 = enc.encrypt("same-data")
        assert c1 != c2

    def test_decrypt_with_wrong_key_fails(self):
        """Decryption with a different KEK raises an error."""
        enc1 = EnvelopeEncryption(secret_key="a" * 32)
        enc2 = EnvelopeEncryption(secret_key="z" * 32)

        ciphertext = enc1.encrypt("secret")
        with pytest.raises(Exception):
            enc2.decrypt(ciphertext)

    def test_key_rotation(self):
        """Old key can decrypt data encrypted under it when provided as rotation key."""
        old_key = "old-key-" + "x" * 24
        new_key = "new-key-" + "y" * 24

        # Encrypt with old key
        enc_old = EnvelopeEncryption(secret_key=old_key)
        ciphertext = enc_old.encrypt("rotate-me")

        # New encryption with old key for rotation
        enc_new = EnvelopeEncryption(secret_key=new_key, old_secret_key=old_key)
        result = enc_new.decrypt(ciphertext)
        assert result == "rotate-me"

    def test_empty_string_roundtrip(self):
        """Empty strings encrypt and decrypt correctly."""
        enc = EnvelopeEncryption(secret_key="c" * 32)
        ciphertext = enc.encrypt("")
        assert enc.decrypt(ciphertext) == ""

    def test_unicode_roundtrip(self):
        """Unicode content survives encryption roundtrip."""
        enc = EnvelopeEncryption(secret_key="d" * 32)
        plaintext = "Umlaute: Hallo Welt!"
        ciphertext = enc.encrypt(plaintext)
        assert enc.decrypt(ciphertext) == plaintext

    def test_long_plaintext(self):
        """Large payloads encrypt/decrypt correctly."""
        enc = EnvelopeEncryption(secret_key="e" * 32)
        plaintext = "x" * 100_000
        ciphertext = enc.encrypt(plaintext)
        assert enc.decrypt(ciphertext) == plaintext

    def test_invalid_ciphertext_raises(self):
        """Garbled ciphertext raises an error on decrypt."""
        enc = EnvelopeEncryption(secret_key="f" * 32)
        with pytest.raises(Exception):
            enc.decrypt(b"not-valid-ciphertext-at-all")

    def test_decrypt_missing_encrypted_dek_raises(self):
        """Envelope missing encrypted_dek raises MalformedEnvelopeError."""
        enc = EnvelopeEncryption(secret_key="g" * 32)
        blob = b'{"version": 1, "encrypted_data": "dGVzdA=="}'
        with pytest.raises(MalformedEnvelopeError, match="encrypted_dek"):
            enc.decrypt(blob)

    def test_decrypt_missing_encrypted_data_raises(self):
        """Envelope missing encrypted_data raises MalformedEnvelopeError."""
        enc = EnvelopeEncryption(secret_key="g" * 32)
        blob = b'{"version": 1, "encrypted_dek": "dGVzdA=="}'
        with pytest.raises(MalformedEnvelopeError, match="encrypted_data"):
            enc.decrypt(blob)

    def test_decrypt_not_a_dict_raises(self):
        """Envelope that is a JSON array raises MalformedEnvelopeError."""
        enc = EnvelopeEncryption(secret_key="g" * 32)
        with pytest.raises(MalformedEnvelopeError, match="JSON object"):
            enc.decrypt(b'[1, 2, 3]')

    def test_decrypt_non_string_key_raises(self):
        """Envelope with non-string encrypted_dek raises MalformedEnvelopeError."""
        enc = EnvelopeEncryption(secret_key="g" * 32)
        blob = b'{"version": 1, "encrypted_dek": 123, "encrypted_data": "dGVzdA=="}'
        with pytest.raises(MalformedEnvelopeError, match="must be a string"):
            enc.decrypt(blob)

    def test_decrypt_unsupported_version_raises(self):
        """Envelope with wrong version raises MalformedEnvelopeError."""
        enc = EnvelopeEncryption(secret_key="g" * 32)
        blob = b'{"version": 99, "encrypted_dek": "dGVzdA==", "encrypted_data": "dGVzdA=="}'
        with pytest.raises(MalformedEnvelopeError, match="Unsupported envelope version"):
            enc.decrypt(blob)

    def test_rotate_missing_keys_raises(self):
        """rotate_envelope with missing keys raises MalformedEnvelopeError."""
        enc = EnvelopeEncryption(secret_key="g" * 32)
        blob = b'{"version": 1}'
        with pytest.raises(MalformedEnvelopeError, match="missing required keys"):
            enc.rotate_envelope(blob)
