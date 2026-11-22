"""Recupera el index.html original de la guía a partir de la página publicada.
Uso: GUIDE_PASSWORD=... python3 tools/decrypt_guide.py index.html guia-original.html"""
import os, re, sys, json, base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
page = open(sys.argv[1], encoding='utf-8').read()
m = re.search(r'\{"s": ?"[^"]+", ?"i": ?"[^"]+", ?"c": ?"[^"]+"\}', page)
P = json.loads(m.group(0))
b = lambda k: base64.b64decode(P[k])
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b('s'), iterations=600000).derive(os.environ['GUIDE_PASSWORD'].encode())
open(sys.argv[2], 'wb').write(AESGCM(key).decrypt(b('i'), b('c'), None))
print('ok')
