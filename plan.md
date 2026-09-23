# Plan — trabajo pendiente

> Documento de trabajo. **No commiteado**, como el anterior.
> Rama: `release/v6.0.15`, sobre `main` con la v0.6.14 ya mergeada (PR #153).
> Estado: 877 tests (2 skipped), cobertura 60.00% con suelo en 57, ruff en verde
> sobre `src` y `tests`.
> Cifras medidas el 2026-08-07, no estimadas.

---

## 0. Hecho el 2026-09-08 (sin commitear, revisar y partir en commits)

Salió de una revisión general de la app. Todo con tests; la suite local pasa salvo los
5 tests de PDF, que fallan sólo porque en este Mac no hay `libpango` para WeasyPrint.

- **CSRF activado de verdad.** `WTF_CSRF_CHECK_DEFAULT=False` significaba "no comprobar
  nada salvo que la vista llame a `csrf.protect()`", y ninguna lo hacía. Ahora se comprueba
  todo; `/api/v1` (bearer) exento; `behaviors.js` añade `X-CSRFToken` a todo `fetch()`
  same-origin no seguro; 4 formularios UAR sin token arreglados; handler de `CSRFError`.
  Tests en `tests/test_csrf.py`.
- **Fuente "Database Query" de UAR.** Sólo admin; una sentencia SELECT/WITH, sin
  comentarios; denylist de identificadores (hashes, tokens, catálogos); conexión de sólo
  lectura (PRAGMA en SQLite, `postgresql_readonly` en PG, comprobado contra el contenedor);
  tope de filas; columnas con pinta de secreto fuera del resultado. Módulo nuevo
  `src/services/readonly_sql.py`, tests en `tests/test_readonly_sql.py`.
- **Arranque rechaza `SECRET_KEY` placeholder** fuera de desarrollo (`src/config.py`).
  El chart de Helm **no ponía `SECRET_KEY`**: ahora la genera y la conserva entre upgrades
  (`templates/secret.yaml`), o la toma de `existingSecret` / `secretKey.existingSecret`.
- Trío barato: `textContent` en `search.js`, `basename`+`secure_filename` en el export de
  auditoría, `secrets` + `compare_digest` en el OTP de MFA.
- Handler global de `IntegrityError` (flash + redirect, 409 en JSON, rollback) y rollback
  antes de la página 500.
- **Bug de tests encontrado de paso:** `Talisman` era una instancia de módulo compartida
  por `init_app`; guarda `force_https` y la CSP en `self`, así que un segundo
  `create_app()` reescribía la política del primero. Ahora es una instancia por app.

**Segundo tramo (código y arquitectura), ya commiteado:**

- 91 rutas POST-only usan `@requires_permission(MODULE, access_level='WRITE')` en vez del
  guard de tres líneas. Quedan ~150 guards inline en rutas GET+POST: pasarlos al decorador
  bloquearía también el formulario, y eso es decisión de producto.
- `organizational_health()` (334 líneas) → `services/health_dashboard_service.py`, una
  función por bloque, 16 tests. **Bug encontrado:** contaba riesgo crítico con
  `residual >= 4` en ambos ejes (esquina roja de 5×5) ignorando matriz y apetito
  configurados; también en `my_dashboard`. Ahora `Risk.criticality_level`.
- `new_offboarding()` → `services/offboarding_service.py` (`build_offboarding_checklist`),
  con N+1 de assets y software arreglados de paso.
- `uar_findings_bulk_action()` → un handler por acción con dict de despacho. **Bug
  encontrado:** `create_incident` nunca funcionó (kwarg `source` inexistente, y luego
  `url_for('security.incident_detail')` sin blueprint `security`). Sin tests hasta hoy.

**Tercer tramo (ops), ya commiteado:**

- **La imagen publicada era la etapa `dev`** (última del Dockerfile, sin `target` en CD):
  pytest, faker y root en producción. Etapa `production` nombrada y última; `target` en CD.
- Contenedor como `opsdeck` (uid 1000) con `HEALTHCHECK`; securityContext en el chart
  (`fsGroup` 1000 para los PVC). La etapa `dev` sigue como root por los bind mounts.
- Contraseña de Postgres fuera de `values.yaml`: `DATABASE_URL` se compone en el pod desde
  el Secret de Bitnami (o `postgresql.auth.existingSecret`), también en el CronJob de backup.
  `db-service.yaml` eliminado (seleccionaba pods que el chart nunca creaba).
- Probes `httpGet /health`; `/health` exento del redirect a https (`talisman_view_options`).
- `.dockerignore`: fuera `data/`, `logs/`, `reset-*.sh`, `helm/`, workflows, docs.
- CD: `startsWith(release/)`, `needs: test` reutilizando `ci.yml` (`workflow_call`);
  CI con `concurrency` y Python 3.14 (la imagen es `python:3.14-slim`, CI probaba 3.11).

Pendiente de la misma revisión, por orden: SSRF en el endpoint configurable de finanzas;
verificación de restore del backup (no hay job que lo pruebe); lock de migraciones si algún
día `replicas` deja de ser 1; `my_dashboard()` (281 líneas) a un servicio como el de org-health; `uar_automation_form()`
(124 líneas de parseo manual); las ~20 lecturas de `os.environ` de `__init__.py` a `config.py`.

---

## 1. CSP — hecho, salvo `style-src`

`script-src` es ahora `'self'` más un nonce por petición. Un `<script>` inyectado no se
ejecuta.

| | |
|---|---|
| `unsafe-eval` | fuera (`a0fbcfc`) |
| 137 handlers `on*` | 0 (`f7e6131`, `f1e65fd`, `01de7e7`) |
| 91 bloques inline | con nonce (`683c0d0`) |
| `unsafe-inline` en `script-src` | fuera (`683c0d0`) |

**Lo único pendiente: comprobar en navegador.** No hay navegador headless en el entorno,
así que todo se verificó renderizando y leyendo el HTML de salida. Si algún bloque inline
quedó sin nonce en una página que no rendericé, el síntoma es que **esa página deja de
funcionar en silencio** — una violación de CSP es un error de consola, no un fallo de
servidor. `CSP_REPORT_ONLY=True` lo enseña sin bloquear. Merece una pasada por la consola
del navegador antes de release.

**`style-src` se queda con `unsafe-inline`, y probablemente para siempre.** Son 328
atributos `style=""`, y un nonce **no puede cubrir un atributo**, sólo un bloque `<style>`.
Sacarlos todos a hojas de estilo es mucho destrozo para una ganancia pequeña comparada con
lo ya conseguido. Mi recomendación es no tocarlo.

---

## 2. Cabos sueltos de lo ya hecho

- **4 endpoints JSON sin declarar**, a propósito: `brands.create_brand`,
  `brands.create_model`, `compliance.toggle_pir_lock`, `onboarding.toggle_item`. Los dos
  primeros son duales de verdad (formulario + AJAX) y declararlos contestaría 401 JSON a un
  POST de navegador. Los dos últimos son formulario con **un `jsonify` 403 suelto** del
  chequeo de escritura mientras todos sus caminos de éxito redirigen: esa incoherencia
  sigue ahí y es lo único accionable del grupo.
- **La carga real de un `Report` enterprise sigue sin verificar** (`69ac153`). El plugin no
  está en este entorno; necesita un despliegue con enterprise.
- **`test_import_software_basic` falló una vez** en una suite completa y no reproduce: ni en
  4 semillas fijas ni forzando los dos órdenes de `test_software_routes` + `test_cli_import`.
  Anotado, no arreglado. Si sale rojo en CI es esto, y es dependiente del orden.
- **7 FKs sin índice**, todas del plugin enterprise (`ai_*`, `enterprise_*`). Sus índices van
  con sus modelos, no aquí.
- **Filas de `body_html` anteriores al saneado** siguen con su HTML sucio en base. La
  visualización es segura (se sanea al renderizar); limpiar el almacenamiento pide una
  migración de datos.
- **Roadmaps, fase 8** (integraciones, ya modeladas y sin UI): objetos vinculados sobre
  `roadmap_initiative_link`, adjuntos (`'RoadmapInitiative': 'roadmaps'` ya está en
  `ENTITY_MODULES`), tags, y entrada en el motor de eventos (`ENTITY_CATALOG`).

---

## 3. Análisis estático

- **CI no lintea `scripts/`**, sólo `src` y `tests`. Quedan **5 hallazgos de ruff** entre
  `google-provision.py` y `jira-sync.py` (los 2 de `bcdr-export.py` ya están limpios).
  Añadir `scripts` al comando es una línea, pero primero hay que limpiar esos 5.
- **Ensanchar ruff.** Hoy está a `select = ["E9", "F"]` a propósito, porque un set amplio
  daba más de 6000 hallazgos. El propio `pyproject.toml` nombra el camino: `B` (bugbear),
  `SIM`, `C4`, `UP`, una familia por commit con su limpieza. Añadiría `C901` para
  complejidad ciclomática.
- **Sonar vs CodeQL.** No quitar Sonar todavía. Se solapan en seguridad y ahí gana CodeQL,
  pero en mantenibilidad no se solapan y **nadie más lo está mirando** con ruff tan
  estrecho. El bug de `load_from_report` lo confirma: es de fiabilidad, ruff no comprueba
  aridad de llamadas y la consulta equivalente de CodeQL (`py/call/wrong-arguments`) vive en
  la suite *quality*, que el *default setup* no ejecuta. **Comprobar en Settings → Code
  scanning** si está `security-and-quality` o sólo `security`; no pude (403 por scope).
- **La familia `pythonsecurity:S87xx`** parte de "un LLM ejecuta esto con argumentos
  hostiles". En scripts de operador eso es una suposición sobre el despliegue, no un
  defecto — pero de las dos que miré, una escondía un bug clásico de verdad (la contraseña
  con `@` redirigía la conexión). Revisar una a una, ni aplicar ni descartar en bloque.

---

## 4. Calidad y arquitectura

- **Módulos de rutas enormes**: `compliance.py` 2242 líneas, `main.py` 1939,
  `onboarding.py` 1152, `roadmaps.py` 901. El de roadmaps ya podría partirse en HTML + API
  aprovechando `src/utils/json_api.py`.
- **`main.py` como cajón de sastre**: login, MFA, OAuth, dashboard, búsqueda, API keys y
  rutas internas de CLI. Partirlo haría auditable de un vistazo el flujo de autenticación,
  que hoy no lo es.
- **Validación en las rutas, no en el dominio.** Los whitelists de status/priority son
  tuplas comprobadas en la capa HTTP, así que el seeder y el importador las esquivan.
  Subirlas a enums o `CHECK` en BD evita que las tres rutas divergan.

Los refactors de tamaño los haría oportunistamente al tocar esos ficheros por otra razón,
no como proyecto.

---

## 5. Matriz de riesgos configurable — hecha

Seis commits: `a483252` fontanería, `68c0087` tamaño, `5fba6f8` apetito, `1f79ff2`
pintado, `1445a61` arrastre de la escala, `e41fe1a` catálogos.

Los catálogos declaran la matriz para la que se escribieron, y el import **traduce** la
sugerencia en vez de copiarla: los extremos van a los extremos, así que el peor caso de un
catálogo sigue siendo el peor caso en cualquier matriz.

**Tamaño configurable por organización**, 3 a 8 por eje e independientes, así que 5×4 vale
igual que 6×6. **Por defecto 5×5**, lo que estaba fijo antes, de modo que una instalación
existente no ve ningún cambio hasta que alguien decida.

**Apetito de riesgo configurable**: dónde el verde pasa a ámbar y el ámbar a rojo, por
defecto 20/60/80 — exactamente donde estaban los umbrales fijos.

Las dos decisiones que importaban, y por qué se comportan al revés:

| | Qué es | Comportamiento |
|---|---|---|
| **Tamaño** | *Cómo se midió* un riesgo | Estampado en cada riesgo y congelado |
| **Apetito** | *Qué tolera* la organización hoy | Se lee en vivo, aplica a todo al instante |

Reinterpretar una evaluación pasada con una matriz adoptada después **falsifica** lo que
dijo quien la hizo. Endurecer el apetito para descubrir qué riesgos ya no son aceptables
es justo la razón de endurecerlo.

### Lo que quedó pendiente

- **Sin verificar en navegador.** Conviene mirar: el mapa de calor con matriz no cuadrada
  (que un 8×4 no se deforme), el PDF con 8×8 (64 celdas en 300px son 35px cada una, puede
  quedar apretado) y los sliders del formulario en una matriz pequeña.
- **El seeder escribe valores 1-5 a pelo.** Inocuo mientras el defecto sea 5×5, pero es la
  misma clase de suposición.
- **Las bandas siguen siendo cuatro fijas** (Low/Medium/High/Critical). Configurable es
  dónde caen, no cuántas hay. Suficiente, salvo que alguien pida cinco.

## 6. UX de Roadmaps (5, ninguna tocada)

1. **Dashboard de Roadmaps** — iniciativas en retraso, progreso por goal, qué vence este
   quarter. Encaja con `organizational_health.html` y My Dashboard.
2. **El Gantt sólo se maneja con ratón** — sin selección múltiple, sin mover un goal
   completo, sin flechas del teclado. Editar 20 iniciativas son 20 arrastres.
3. **Accesibilidad del Gantt** — las barras no son enfocables ni operables por teclado, no
   tienen ARIA, y en varios sitios el color es la única señal de estado. Es lo más flojo del
   módulo.
4. **Sin deshacer** — borrar un goal se lleva sus iniciativas sin retorno, y un arrastre
   puede reprogramar una cadena entera de golpe.
5. **Estados vacíos que mandan a otra pantalla** — crear un roadmap te deja en un Gantt que
   dice "no hay periodos, ve al formulario"; debería poder generarlos ahí mismo.

---

## 7. Orden que propongo

1. **Pasada por navegador**, que es lo único que bloquea algo ya mergeado o casi: consola
   sin errores de CSP en unas cuantas páginas, y el mapa de calor y los sliders con una
   matriz no cuadrada. Media hora y cierra los dos riesgos abiertos.
2. **UX del Gantt (2 y 3 juntas)** — teclado y accesibilidad son el mismo trabajo.
3. **Ensanchar ruff**, una familia por commit, en hueco.
4. **Roadmaps fase 8**, si se quiere cerrar el módulo.

Fuera de orden, cuando toque: limpiar los 5 hallazgos de `scripts/` y añadir ese directorio
al lint, y decidir lo de Sonar tras mirar la configuración de CodeQL.

**No haría** `style-src` sin `unsafe-inline` (328 atributos para poca ganancia) ni los
refactors de tamaño de `main.py`/`compliance.py` como proyecto propio — esos, al pasar por
ahí por otra razón.
