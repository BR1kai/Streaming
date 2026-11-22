"""Cifra la guía con una clave. Uso: GUIDE_PASSWORD=... python3 build_gate.py <carpeta_fuente> <carpeta_salida>
La fuente tiene index.html y escaletas/*.pdf. La salida tiene index.html (pantalla de acceso con la guía cifrada) y escaletas/*.pdf.enc"""
import os, sys, json, base64, glob, shutil
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
src, out = sys.argv[1], sys.argv[2]
pw = os.environ['GUIDE_PASSWORD']
assert len(pw) >= 10 or os.environ.get('GUIDE_ALLOW_SHORT') == '1', 'La clave debe tener al menos 10 caracteres'
here = os.path.dirname(os.path.abspath(__file__))
salt = os.urandom(16)
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(pw.encode('utf-8'))
aes = AESGCM(key)
def seal(data):
    iv = os.urandom(12)
    return iv, aes.encrypt(iv, data, None)
html = open(os.path.join(src, 'index.html'), 'rb').read()
iv, ct = seal(html)
payload = json.dumps({'s': base64.b64encode(salt).decode(), 'i': base64.b64encode(iv).decode(), 'c': base64.b64encode(ct).decode()})
tpl = open(os.path.join(here, 'gate.html'), encoding='utf-8').read()
assert tpl.count('__PAYLOAD__') == 1
if os.path.isdir(out): shutil.rmtree(out)
os.makedirs(os.path.join(out, 'escaletas'))
open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(tpl.replace('__PAYLOAD__', payload))
open(os.path.join(out, '.nojekyll'), 'w').close()
for p in sorted(glob.glob(os.path.join(src, 'escaletas', '*.pdf'))):
    i, c = seal(open(p, 'rb').read())
    open(os.path.join(out, 'escaletas', os.path.basename(p) + '.enc'), 'wb').write(i + c)
print('ok', len(os.listdir(os.path.join(out, 'escaletas'))), 'pdf cifrados')
