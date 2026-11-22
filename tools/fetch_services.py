"""Descarga de Planning Center Services (solo lectura) y cifrado con la clave de la guía.

Uso:  python3 tools/fetch_services.py services.json.enc          (datos reales, en GitHub Actions)
      python3 tools/fetch_services.py services.json.enc --demo   (datos de ejemplo)

Variables de entorno:
  PCO_APP_ID, PCO_SECRET   token personal de Planning Center (secrets de GitHub)
  GUIDE_PASSWORD           clave de la guía (secret de GitHub). Mínimo 10 caracteres.
  PCO_SERVICE_TYPE         (opcional) texto que debe contener el nombre del tipo de servicio, p. ej. "Domingo"
  PCO_FOCUS                (opcional) posiciones/equipos de los que listar disponibilidad, separados por comas.
                           Por defecto: "bienvenida"
  PCO_PLANS                (opcional) cuántos planes futuros por tipo de servicio. Por defecto 4
  PCO_ONLY_SUNDAYS         (opcional) "1" (por defecto) para quedarse solo con los domingos
"""
import os, sys, json, base64, time, datetime, urllib.request, urllib.parse, urllib.error

API = 'https://api.planningcenteronline.com/services/v2'
DIAG = []


def credentials():
    """App ID y Secret. Acepta PCO_APP_ID + PCO_SECRET, o un único valor «appid:secret»."""
    app, sec = os.environ.get('PCO_APP_ID', '').strip(), os.environ.get('PCO_SECRET', '').strip()
    if not app and ':' in sec:
        app, sec = sec.split(':', 1)
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
    stf = os.environ.get('PCO_SERVICE_TYPE', '').strip().lower()
    focus = [x.strip().lower() for x in (os.environ.get('PCO_FOCUS') or 'bienvenida').split(',') if x.strip()]
    nplans = int(os.environ.get('PCO_PLANS') or 4)
    sundays = (os.environ.get('PCO_ONLY_SUNDAYS') or '1') != '0'

    types, _ = paged('/service_types')
    types = [t for t in types if stf in (t['attributes'].get('name') or '').lower()]
    if not types:
        raise SystemExit('No hay ningún tipo de servicio que coincida con "%s"' % stf)

    plans_out, focus_acc = [], {f: {} for f in focus}
    for st in types:
        stid, stname = st['id'], st['attributes'].get('name')
        plans, _ = paged('/service_types/%s/plans' % stid, {'filter': 'future', 'order': 'sort_date', 'per_page': 25})
        plans = [p for p in plans if date_of(p['attributes'].get('sort_date'))]
        if sundays:
            plans = [p for p in plans if datetime.date.fromisoformat(date_of(p['attributes']['sort_date'])).weekday() == 6]
        plans = plans[:nplans]

        # personas que pueden hacer cada posición de interés
        cands = {f: {} for f in focus}
        teams, _ = paged('/service_types/%s/teams' % stid)
        for t in teams:
            tname = (t['attributes'].get('name') or '')
            asg, inc = first_ok(['/service_types/%s/teams/%s/person_team_position_assignments' % (stid, t['id']),
                                 '/teams/%s/person_team_position_assignments' % t['id']],
                                {'include': 'person,team_position'})
            ix = idx(inc)
            for a in asg:
                pr, pos = rel(a, 'person'), rel(a, 'team_position')
                pn = ix.get(('Person', pr['id']), {}).get('attributes', {}) if pr else {}
                posn = ix.get(('TeamPosition', pos['id']), {}).get('attributes', {}).get('name', '') if pos else ''
                who = pn.get('full_name') or ' '.join(x for x in [pn.get('first_name'), pn.get('last_name')] if x)
                if not pr or not who:
                    continue
                for f in focus:
                    if f in posn.lower() or f in tname.lower():
                        cands[f][pr['id']] = who

        # bloqueos de fechas, una vez por persona
        blk = {}
        for f in focus:
            for pid in cands[f]:
                if pid in blk:
                    continue
                b, _ = first_ok(['/people/%s/blockout_dates' % pid, '/people/%s/blockouts' % pid], {'filter': 'future'})
                blk[pid] = [x['attributes'] for x in b]

        for p in plans:
            day = date_of(p['attributes']['sort_date'])
            tm, inc = paged('/service_types/%s/plans/%s/team_members' % (stid, p['id']), {'include': 'team'})
            ix = idx(inc)
            by_team, status_of = {}, {}
            for m in tm:
                a = m['attributes']
                tr = rel(m, 'team')
                tn = ix.get(('Team', tr['id']), {}).get('attributes', {}).get('name', '') if tr else ''
                by_team.setdefault(tn or 'Sin equipo', []).append(
                    {'position': a.get('team_position_name') or '', 'name': a.get('name') or '', 'status': a.get('status') or ''})
                pr = rel(m, 'person')
                if pr:
                    status_of.setdefault(pr['id'], []).append((a.get('team_position_name') or '', a.get('status') or ''))
            title = p['attributes'].get('title') or p['attributes'].get('dates') or stname
            plans_out.append({'date': day, 'title': title, 'service_type': stname,
                              'teams': [{'team': k, 'members': v} for k, v in by_team.items()]})
            for f in focus:
                people = []
                for pid, who in sorted(cands[f].items(), key=lambda kv: kv[1].lower()):
                    asg = [s for s in status_of.get(pid, []) if f in s[0].lower()] or []
                    if asg:
                        state, reason = {'C': 'confirmado', 'U': 'pendiente', 'D': 'rechazado'}.get(asg[0][1], 'asignado'), ''
                    else:
                        bl = [b for b in blk.get(pid, []) if overlaps(day, b)]
                        state, reason = ('bloqueado', (bl[0].get('reason') or '')) if bl else ('libre', '')
                        if pid in status_of:
                            state = 'en otra posición' if not bl else state
                    people.append({'name': who, 'state': state, 'reason': reason})
                focus_acc[f].setdefault(day, []).extend(people)

    focus_out = [{'label': f, 'days': [{'date': d, 'people': focus_acc[f][d]} for d in sorted(focus_acc[f])]} for f in focus]
    return {'demo': False, 'plans': plans_out, 'focus': focus_out, 'notes': DIAG}


def demo():
    base = datetime.date.today()
    base += datetime.timedelta(days=(6 - base.weekday()) % 7 or 7)
    d1, d2 = base.isoformat(), (base + datetime.timedelta(days=7)).isoformat()
    def plan(d):
        return {'date': d, 'title': 'Domingo (ejemplo)', 'service_type': 'Domingo', 'teams': [
            {'team': 'Streaming', 'members': [
                {'position': 'vMix', 'name': 'Persona de ejemplo 1', 'status': 'C'},
                {'position': 'Cámara 1', 'name': 'Persona de ejemplo 2', 'status': 'C'},
                {'position': 'Cámara 2', 'name': 'Persona de ejemplo 3', 'status': 'U'}]},
            {'team': 'Bienvenida', 'members': [
                {'position': 'Sala de bienvenida', 'name': 'Persona de ejemplo 4', 'status': 'U'}]}]}
    pe = lambda n, s, r='': {'name': n, 'state': s, 'reason': r}
    return {'demo': True, 'plans': [plan(d1), plan(d2)], 'focus': [{'label': 'bienvenida', 'days': [
        {'date': d1, 'people': [pe('Persona de ejemplo 4', 'pendiente'), pe('Persona de ejemplo 5', 'libre'), pe('Persona de ejemplo 6', 'bloqueado', 'Viaje')]},
        {'date': d2, 'people': [pe('Persona de ejemplo 4', 'libre'), pe('Persona de ejemplo 5', 'bloqueado', 'Trabajo'), pe('Persona de ejemplo 6', 'libre')]}]}], 'notes': []}


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
    if len(pw) < 10:  # clave corta: no se publican los motivos de los bloqueos (pueden ser privados)
        for f in data.get('focus', []):
            for d in f['days']:
                for pe in d['people']:
                    pe['reason'] = ''
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
