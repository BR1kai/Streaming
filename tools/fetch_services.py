"""Descarga de Planning Center Services (solo lectura) y cifrado con la clave de la guía.

Uso:  python3 tools/fetch_services.py services.json.enc          (datos reales, en GitHub Actions)
      python3 tools/fetch_services.py services.json.enc --demo   (datos de ejemplo)

Variables de entorno:
  PCO_APP_ID, PCO_SECRET   token personal de Planning Center (secrets de GitHub)
  GUIDE_PASSWORD           clave de la guía (secret de GitHub). Mínimo 10 caracteres.
  PCO_SERVICE_TYPE         (opcional) texto que debe contener «carpeta › tipo de servicio». Por defecto "Domingo"
  PCO_SERVICE_TYPE_ID      (opcional) ids de tipos de servicio separados por comas
  PCO_PLANS                (opcional) cuántos planes futuros por tipo de servicio. Por defecto 4
  PCO_ONLY_SUNDAYS         (opcional) "1" (por defecto) para quedarse solo con los domingos
"""
import os, sys, json, base64, time, datetime, urllib.request, urllib.parse, urllib.error

API = 'https://api.planningcenteronline.com/services/v2'
DIAG = []


def credentials():
    """App ID y Secret. Acepta PCO_APP_ID + PCO_SECRET, o un único valor «appid:secret»."""
    app, sec = os.environ.get('PCO_APP_ID', '').strip(), os.environ.get('PCO_SECRET', '').strip()
    if ':' in sec:  # el secret ya trae «appid:secret»: manda lo que lleva dentro
        app, sec = [x.strip() for x in sec.split(':', 1)]
    print('credenciales: app id de %d caracteres, secret de %d caracteres' % (len(app), len(sec)))
    if not app or not sec:
        raise SystemExit('Faltan las credenciales de Planning Center (PCO_APP_ID y PCO_SECRET, o el secret SERVICES con «appid:secret»).')
    return app + ':' + sec


def api(path, params=None):
    url = path if path.startswith('http') else API + path
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    tok = base64.b64encode(credentials().encode()).decode()
    req = urllib.request.Request(url, headers={'Authorization': 'Basic ' + tok, 'User-Agent': 'streaming-guia'})
    for _ in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit('Planning Center ha rechazado las credenciales (401): revisa que el App ID y el Secret sean los del mismo token.')
            if e.code == 429:
                time.sleep(int(e.headers.get('Retry-After', '20')) + 1)
                continue
            raise
    raise RuntimeError('Demasiadas peticiones a Planning Center')


def paged(path, params=None):
    """Devuelve (datos, incluidos) de todas las páginas."""
    p = dict(params or {})
    p.setdefault('per_page', 100)
    data, inc = [], []
    url = path
    while url:
        d = api(url, p if url == path else None)
        data += d.get('data', [])
        inc += d.get('included', [])
        url = (d.get('links') or {}).get('next')
    return data, inc


def first_ok(paths, params=None):
    """Prueba varias rutas posibles y usa la primera que responda."""
    last = None
    for p in paths:
        try:
            return paged(p, params)
        except Exception as e:  # noqa
            last = e
    DIAG.append('sin respuesta: %s (%s)' % (paths[0], last))
    return [], []


def idx(included):
    return {(i['type'], i['id']): i for i in included}


def rel(obj, name):
    d = ((obj.get('relationships') or {}).get(name) or {}).get('data')
    return d if isinstance(d, dict) else None


def date_of(s):
    return (s or '')[:10]


def overlaps(day, b):
    a, z = date_of(b.get('starts_at')), date_of(b.get('ends_at')) or date_of(b.get('starts_at'))
    return bool(a) and a <= day <= z


def collect():
    stf = (os.environ.get('PCO_SERVICE_TYPE') or 'domingo').strip().lower()
    nplans = int(os.environ.get('PCO_PLANS') or 4)
    sundays = (os.environ.get('PCO_ONLY_SUNDAYS') or '1') != '0'

    types, _ = paged('/service_types')
    try:
        fl = {f['id']: f for f in paged('/folders')[0]}
    except Exception:  # noqa
        fl = {}

    def fpath(fid):
        out, seen = [], set()
        while fid and fid in fl and fid not in seen:
            seen.add(fid)
            out.append(fl[fid]['attributes'].get('name') or '')
            par = rel(fl[fid], 'parent')
            fid = par['id'] if par else None
        return list(reversed(out))
    for t in types:
        par = rel(t, 'parent')
        t['path'] = fpath(par['id'] if par else None) + [t['attributes'].get('name') or '']
        t['label'] = ' › '.join(t['path'])
    all_types = [{'id': t['id'], 'label': t['label']} for t in types]
    ids = [x.strip() for x in (os.environ.get('PCO_SERVICE_TYPE_ID') or '').split(',') if x.strip()]
    types = [t for t in types if (not ids or t['id'] in ids) and stf in t['label'].lower() and 'kids' not in t['label'].lower()]
    if not types:
        raise SystemExit('No hay ningún tipo de servicio que coincida con "%s" %s' % (stf, ids))

    plans_out = []
    for st in types:
        stid = st['id']
        first = st['path'][0].lower()
        campus = 'Barcelona' if first.startswith('barcelona') else st['path'][0]
        last = st['path'][-1].lower()
        slot = 'PM' if last.endswith('pm') else ('AM' if last.endswith('am') else '')
        plans, _ = paged('/service_types/%s/plans' % stid, {'filter': 'future', 'order': 'sort_date', 'per_page': 25})
        plans = [p for p in plans if date_of(p['attributes'].get('sort_date'))]
        if sundays:
            plans = [p for p in plans if datetime.date.fromisoformat(date_of(p['attributes']['sort_date'])).weekday() == 6]
        for p in plans[:nplans]:
            tm, inc = paged('/service_types/%s/plans/%s/team_members' % (stid, p['id']), {'include': 'team'})
            ix = idx(inc)
            by_team = {}
            for m in tm:
                a = m['attributes']
                tr = rel(m, 'team')
                tn = ix.get(('Team', tr['id']), {}).get('attributes', {}).get('name', '') if tr else ''
                by_team.setdefault(tn or 'Sin equipo', []).append(
                    {'position': a.get('team_position_name') or '', 'name': a.get('name') or '', 'status': a.get('status') or ''})
            plans_out.append({'date': date_of(p['attributes']['sort_date']), 'campus': campus, 'slot': slot,
                              'title': p['attributes'].get('title') or '', 'service_type': st['label'],
                              'teams': [{'team': k, 'members': v} for k, v in by_team.items()]})
    return {'demo': False, 'plans': plans_out, 'service_types': all_types, 'notes': DIAG}


def demo():
    base = datetime.date.today()
    base += datetime.timedelta(days=(6 - base.weekday()) % 7 or 7)
    plans = []
    for k in range(2):
        d = (base + datetime.timedelta(days=7 * k)).isoformat()
        for campus in ('Barcelona', 'Madrid'):
            for slot in ('AM', 'PM'):
                plans.append({'date': d, 'campus': campus, 'slot': slot, 'title': '', 'service_type': campus + ' › Domingo › Domingo ' + slot, 'teams': [
                    {'team': 'Televisión', 'members': [
                        {'position': 'Realizador', 'name': 'Persona de ejemplo 1', 'status': 'C'},
                        {'position': 'Cámara 1', 'name': 'Persona de ejemplo 2', 'status': 'U'},
                        {'position': 'Sala de Bienvenida', 'name': 'Persona de ejemplo 3', 'status': 'C'}]},
                    {'team': 'AV', 'members': [{'position': 'vMix', 'name': 'Persona de ejemplo 4', 'status': 'C'}]},
                    {'team': 'Sonido', 'members': [{'position': 'FOH', 'name': 'Persona de ejemplo 5', 'status': 'D'}]}]})
    return {'demo': True, 'plans': plans, 'service_types': [], 'notes': []}


def derive(pw, salt):
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000).derive(pw.encode('utf-8'))


def seal(obj, pw):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(derive(pw, salt)).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode('utf-8'), None)
    return salt + iv + ct


def unseal(raw, pw):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return json.loads(AESGCM(derive(pw, raw[:16])).decrypt(raw[16:28], raw[28:], None))


def main():
    out = sys.argv[1]
    pw = os.environ['GUIDE_PASSWORD']
    if len(pw) < 10 and os.environ.get('GUIDE_ALLOW_SHORT') != '1':  # el workflow lo activa a propósito
        raise SystemExit('La clave de la guía tiene menos de 10 caracteres: no se publican nombres con una clave tan corta. '
                         'Cambia el secret GUIDE_PASSWORD y la clave de la guía.')
    data = demo() if '--demo' in sys.argv else collect()
    data['generated'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    if os.path.exists(out):
        try:
            old = unseal(open(out, 'rb').read(), pw)
            if {k: v for k, v in old.items() if k != 'generated'} == {k: v for k, v in data.items() if k != 'generated'}:
                print('Sin cambios')
                return
        except Exception:  # noqa
            pass
    open(out, 'wb').write(seal(data, pw))
    print('Guardado', out, '-', len(data['plans']), 'planes')


if __name__ == '__main__':
    main()
