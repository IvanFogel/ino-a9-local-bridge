"""Cryptographic helpers for the legacy PPRPC wire format.

Secrets are always supplied by the caller.  This module contains algorithms
only; it intentionally has no vendor prefix or device credential constants.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


AES_BLOCK_SIZE = 16


def aes_cbc_encrypt_padded(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """Encrypt with AES-CBC and PKCS#7 padding."""
    _validate(key, iv)
    padder = PKCS7(AES_BLOCK_SIZE * 8).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def aes_cbc_decrypt_padded(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt AES-CBC and validate/remove PKCS#7 padding."""
    _validate(key, iv)
    if not ciphertext or len(ciphertext) % AES_BLOCK_SIZE:
        raise ValueError("padded AES-CBC ciphertext must be non-empty and block-aligned")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(AES_BLOCK_SIZE * 8).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def aes_cbc_encrypt_unpadded(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """Encrypt block-aligned bytes with AES-CBC and no padding."""
    _validate(key, iv)
    if len(plaintext) % AES_BLOCK_SIZE:
        raise ValueError("unpadded AES-CBC plaintext must be block-aligned")
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def aes_cbc_decrypt_unpadded(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt block-aligned bytes with AES-CBC and no padding."""
    _validate(key, iv)
    if len(ciphertext) % AES_BLOCK_SIZE:
        raise ValueError("unpadded AES-CBC ciphertext must be block-aligned")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def _validate(key: bytes, iv: bytes) -> None:
    if len(key) not in (16, 24, 32):
        raise ValueError("AES key must contain 16, 24, or 32 bytes")
    if len(iv) != AES_BLOCK_SIZE:
        raise ValueError("AES-CBC IV must contain 16 bytes")
