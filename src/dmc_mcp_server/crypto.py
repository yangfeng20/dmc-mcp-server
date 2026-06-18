from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

DMC_RSA_PUBKEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAhhmB0yzILcGZ1/oPTBr/
Mp6z2KTRQfRMeOWXoODbX/zBI1yhFvXn9RQZULTZFLbK7juTlMiOvztHraTmnSeI
787ZAfaxhFzj5B65G/D4S+r8kuUQW9WlcdBuNVWzjmaJjtcJUNtqQMT/bWyeynZk
fDmJ/YHYZKXnGPUNgMVJsXMrJ0KvnlmlSH3X9ki2hgIXud++y3f5Oa+GxhkHD1wK
fGgWNMKxtKotPjTM3hdQmBhDUnt4XUreVX36BgfhFCpzJSMsDQGQ2LYsknEP8AVR
SERCA6o2PZ/qqu+lhM1JIwYjlLgjYzWSIQYXGusMR7QTw/KAntLSiq19kifdt44T
+QIDAQAB
-----END PUBLIC KEY-----"""


def encrypt_password(plain_password: str) -> str:
    rsa_key = RSA.import_key(DMC_RSA_PUBKEY_PEM)
    cipher = PKCS1_v1_5.new(rsa_key)
    encrypted_bytes = cipher.encrypt(plain_password.encode("utf-8"))
    return encrypted_bytes.hex()
