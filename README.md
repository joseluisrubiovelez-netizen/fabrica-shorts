# Fábrica de Shorts de misterio (coste 0 €)

Genera y publica de forma automática vídeos verticales (YouTube Shorts, TikTok, Instagram Reels) de **misterio y terror suave en castellano de España**, con voz en off IA, subtítulos palabra a palabra y 2-3 publicaciones al día. Todo funciona con herramientas gratuitas o de código abierto (ver [docs/herramientas.md](docs/herramientas.md)).

- Configuración inicial: [SETUP.md](SETUP.md)
- Límites del plan gratuito y riesgos: [docs/limites_y_riesgos.md](docs/limites_y_riesgos.md)

## Cómo funciona

```
config.yaml ─┐
             ▼
 1. Ideación + guion (Gemini → Groq → semillas) ── SQLite (historial, sin repetir temas)
    · serie histórica: tema curado → texto de Wikipedia → guion SOLO con esos hechos →
      verificación afirmación a afirmación (si algo no está respaldado, se descarta)
 2. Voz: Piper TTS local (es_ES-davefx, dataset CC0)
 3. Subtítulos: faster-whisper local + alineación con el texto exacto del guion
 4. Visuales por escena: FLUX (Cloudflare) / clips Pexels-Pixabay / fondo procedural
 5. Música + SFX (biblioteca con licencia o síntesis propia) con ducking bajo la voz
 6. Montaje 1080x1920 H.264+AAC: Ken Burns, fundidos, grano, gancho, subtítulos
 7. QA automático (hasta 2 regeneraciones) ── si falla: descartar y avisar
 8. Cola → aprobación (review) → hueco horario (Europe/Madrid) → APIs oficiales
 9. Analítica semanal (YouTube Analytics, TikTok, Instagram Insights) → informe .md
```

## Órdenes

| Orden | Qué hace |
|---|---|
| `make setup` / `.\make.ps1 setup` | Instala todo y descarga la voz |
| `make run` | Un ciclo: aprobaciones, publicación de huecos vencidos y relleno de cola |
| `make test` | Tests de QA, cola, programador, guiones y publicación |
| `make dry-run` | Genera un vídeo sin publicar |
| `python -m fabrica --modo dry-run generar --n 10` | Genera 10 vídeos de prueba |
| `python -m fabrica estado` | Estado de la cola |
| `python -m fabrica aprobar 12` / `descartar 12` | También por Telegram: `/aprobar 12` |
| `python -m fabrica publicar 12` | Publica ya un vídeo concreto |
| `python -m fabrica informe` | Informe de analítica ahora |
| `python -m fabrica verificar` | Qué claves faltan |

## Modos

- `dry-run`: genera y valida sin publicar nada.
- `review` (por defecto, recomendado las 2 primeras semanas): cada vídeo te llega por Telegram y solo se publica lo que apruebas.
- `auto`: publica sin intervención y solo avisa de errores.

Se elige en `config.yaml` (`modo`), con la variable `FABRICA_MODO` o con `--modo`.

## Reglas del canal y cómo se cumplen

| Regla | Implementación |
|---|---|
| Etiqueta IA nativa | YouTube `status.containsSyntheticMedia=true` · TikTok `post_info.is_aigc=true` · Instagram `is_ai_generated=true`. En las subidas manuales, el aviso de Telegram recuerda activar la etiqueta. |
| Sin personas reales ni copyright | Prompt del guion + lista de bloqueo en la validación + negativos en los prompts de imagen + filtro de clips con personas (etiquetas y URL) |
| Licencias | Cada recurso (voz, imagen, clip, música, SFX) se guarda en la tabla `assets` con fuente y licencia; el QA **falla** si falta alguna. Los créditos se añaden a la descripción. |
| Ficción vs. historia | Etiqueta "FICCIÓN" en pantalla y "Relato de ficción" en la descripción; las series históricas exigen fuentes verificables (URLs) y `es_ficcion=false` |
| Variedad | 8 estructuras × 6 tipos de gancho rotados según su uso reciente, deduplicación de temas y ganchos (Jaccard), movimientos de cámara aleatorios, música distinta por vídeo, 3 series con estilo visual propio |
| Solo APIs oficiales | YouTube Data API v3, TikTok Content Posting API, Instagram API. Sin scraping ni navegador. |
| Sin violencia gráfica, sexo ni público infantil | Lista de bloqueo + prompt + `selfDeclaredMadeForKids=false` |
| Sin secretos en el código | `.env` / GitHub Secrets; los tokens que rotan se guardan cifrados (Fernet) |

## Estructura

```
fabrica/         código (config, db, guiones, voz, imagenes, audio, subtitulos, render, qa,
                 pipeline, scheduler, analytics, notify, publicar/)
seeds/           guiones semilla escritos a mano (respaldo sin LLM)
assets/          música y SFX propios con licencias.yaml
tests/           pytest
docs/            herramientas.md, limites_y_riesgos.md
.github/         workflow horario de GitHub Actions
```

## Añadir o cambiar una serie

Edita `series` en `config.yaml`: premisa, `estilo_visual` (se añade a cada prompt de imagen para que la serie sea coherente), paleta de color, etiqueta y peso. Los pesos deben sumar 1.
