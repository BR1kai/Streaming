# Herramientas (no contienen nada secreto)

- `build_gate.py`: cifra la guía y los PDF. `GUIDE_PASSWORD=... python3 tools/build_gate.py <carpeta_fuente> <carpeta_salida>`
- `decrypt_guide.py`: recupera el index.html original de la guía a partir de la página publicada.
- `fetch_services.py`: lo ejecuta GitHub Actions cada día para bajar los datos de Services y cifrarlos.

Secrets del repositorio: `PCO_APP_ID`, `PCO_SECRET`, `GUIDE_PASSWORD`.
Variables opcionales: `PCO_SERVICE_TYPE` (por defecto «Domingo»), `PCO_SERVICE_TYPE_ID`.
