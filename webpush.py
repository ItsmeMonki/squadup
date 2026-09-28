#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webpush.py — отправка Web Push уведомлений (RFC 8291 + VAPID, RFC 8292)
на чистом `cryptography`, без внешних push-библиотек.

Как это работает:
  1. Клиент (service worker) подписывается на push и присылает endpoint + ключи p256dh/auth.
  2. Мы генерируем пару ключей VAPID (P-256), подписываем ими JWT (ES256).
  3. Шифруем payload по схеме aes128gcm и POST-им его на endpoint.
  4. Push-сервис браузера (FCM/Mozilla/Apple) доставляет уведомление,
     даже если приложение закрыто — его принимает service worker.

Если библиотека cryptography не установлена, модуль помечает себя как недоступный,
и приложение просто не показывает кнопку включения уведомлений.
"""

import base64
import json
import os
import struct
import time
import urllib.error
import urllib.request

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover
    CRYPTO_AVAILABLE = False

# Сколько живёт подписанный JWT в секунду (JWT максимально допускает 24 часа)
VAPID_JWT_TTL = 12 * 3600
# Размер записи в aes128gcm (RFC 8188), для сообщений до 4 КБ хватает одного блока
RECORD_SIZE = 4096
# Уведомление живёт сутки, если устройство офлайн
DEFAULT_TTL = 86400


# ---------------------------------------------------------------------------
# base64url
# ---------------------------------------------------------------------------

def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ---------------------------------------------------------------------------
# Ключи VAPID
# ---------------------------------------------------------------------------

def generate_vapid_keys():
    """Возвращает (public_key, private_key) в base64url (сырые байты P-256)."""
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("Требуется библиотека cryptography")
    private = ec.generate_private_key(ec.SECP256R1())
    raw_private = private.private_numbers().private_value.to_bytes(32, "big")
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return b64url_encode(raw_public), b64url_encode(raw_private)


def _load_private_key(private_b64: str):
    raw = b64url_decode(private_b64)
    value = int.from_bytes(raw, "big")
    return ec.derive_private_key(value, ec.SECP256R1())


def _public_from_private(private_b64: str) -> str:
    private = _load_private_key(private_b64)
    raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return b64url_encode(raw)


# ---------------------------------------------------------------------------
# VAPID JWT (ES256)
# ---------------------------------------------------------------------------

def vapid_headers(endpoint: str, public_key: str, private_key: str, subject: str = "mailto:admin@squadup.app"):
    if not CRYPTO_AVAILABLE:
        raise RuntimeError("Требуется библиотека cryptography")
    from urllib.parse import urlparse
    audience = "{0.scheme}://{0.netloc}".format(urlparse(endpoint))

    header = {"typ": "JWT", "alg": "ES256"}
    claims = {
        "aud": audience,
        "exp": int(time.time()) + VAPID_JWT_TTL,
        "sub": subject,
    }
    signing_input = (b64url_encode(json.dumps(header, separators=(",", ":")).encode())
                     + "." + b64url_encode(json.dumps(claims, separators=(",", ":")).encode()))
    private = _load_private_key(private_key)
    der_sig = private.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = asym_utils.decode_dss_signature(der_sig)
    # JWT для ES256 требует «сырую» подпись r||s по 32 байта (не DER)
    raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = signing_input + "." + b64url_encode(raw_sig)
    return {"Authorization": f"vapid t={token}, k={public_key}", "Crypto-Key": f"p256ecdsa={public_key}"}


# ---------------------------------------------------------------------------
# Шифрование payload (aes128gcm, RFC 8188 + RFC 8291)
# ---------------------------------------------------------------------------

def encrypt_payload(payload: bytes, p256dh_b64: str, auth_b64: str) -> bytes:
    """Возвращает готовое тело запроса: заголовок + зашифрованные данные."""
    client_public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), b64url_decode(p256dh_b64))
    auth_secret = b64url_decode(auth_b64)

    server_private = ec.generate_private_key(ec.SECP256R1())
    server_public = server_private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    client_public_raw = client_public.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    shared_secret = server_private.exchange(ec.ECDH(), client_public)

    # key_info = "WebPush: info" || 0x00 || ua_public || as_public
    ikm = HKDF(
        algorithm=hashes.SHA256(), length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + client_public_raw + server_public,
    ).derive(shared_secret)

    salt = os.urandom(16)
    cek = HKDF(
        algorithm=hashes.SHA256(), length=16,
        salt=salt, info=b"Content-Encoding: aes128gcm\x00",
    ).derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12,
        salt=salt, info=b"Content-Encoding: nonce\x00",
    ).derive(ikm)

    # 0x02 — маркер последней записи (padding delimiter)
    record = payload + b"\x02"
    ciphertext = AESGCM(cek).encrypt(nonce, record, None)

    header = salt + struct.pack(">I", RECORD_SIZE) + bytes([len(server_public)]) + server_public
    return header + ciphertext


def decrypt_payload(body: bytes, private_key, ua_public_raw: bytes, auth_secret: bytes) -> bytes:
    """Только для тестов: расшифровывает то, что мы зашифровали (роль клиента)."""
    salt = body[:16]
    rs = struct.unpack(">I", body[16:20])[0]
    key_len = body[20]
    server_public_raw = body[21:21 + key_len]
    ciphertext = body[21 + key_len:]
    assert rs == RECORD_SIZE

    server_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), server_public_raw)
    shared_secret = private_key.exchange(ec.ECDH(), server_public)

    ikm = HKDF(
        algorithm=hashes.SHA256(), length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public_raw + server_public_raw,
    ).derive(shared_secret)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt,
               info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt,
                 info=b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    return plain.rstrip(b"\x00").rstrip(b"\x02")


# ---------------------------------------------------------------------------
# Отправка
# ---------------------------------------------------------------------------

def send_web_push(subscription: dict, payload: dict, public_key: str, private_key: str,
                  subject: str = "mailto:admin@squadup.app", ttl: int = DEFAULT_TTL):
    """
    subscription: {"endpoint": ..., "p256dh": ..., "auth": ...}
    Возвращает (ok: bool, status: int | None, error: str).
    Статусы 404/410 означают, что подписку нужно удалить.
    """
    if not CRYPTO_AVAILABLE:
        return False, None, "cryptography не установлена"
    endpoint = subscription.get("endpoint") or ""
    if not endpoint.startswith("https://"):
        return False, None, "некорректный endpoint"

    body = encrypt_payload(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           subscription["p256dh"], subscription["auth"])
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Encoding": "aes128gcm",
        "TTL": str(ttl),
        "Urgency": "normal",
    }
    headers.update(vapid_headers(endpoint, public_key, private_key, subject))

    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300, resp.status, ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        return False, exc.code, detail or str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, None, str(exc)
