# Verificación de herramientas gratuitas

Fecha de comprobación: **2026-11-22**. Las capas gratuitas cambian: revisa esta tabla cada 2-3 meses.
Estado: ✅ confirmado en documentación oficial · ⚠️ confirmado solo en fuentes secundarias o con matices · ❌ descartado.

## Equipo local detectado

| Recurso | Valor | Consecuencia |
|---|---|---|
| GPU | Intel Iris Xe (integrada, sin CUDA) | Stable Diffusion/FLUX local solo en CPU/OpenVINO: lento y de menor calidad |
| CPU | i5-1340P (12 núcleos / 16 hilos) | Piper, Whisper (small/base) y FFmpeg van bien |
| RAM | 15,7 GB | Un LLM local de 7-8B vía Ollama cabe, pero lento y flojo en castellano |
| Disco libre | ~373 GB | Sin problema |
| Python 3.12, FFmpeg 9.0.2, Git | Instalados | Falta `make` (se usará `make.ps1` o GNU Make vía winget) |

## Tabla de herramientas

| Función | Herramienta | Límite gratuito | Licencia / uso comercial | Estado | Fuente |
|---|---|---|---|---|---|
| Guiones | Gemini API (Flash / Flash-Lite), capa gratuita | Google no publica los números: se ven en AI Studio. Informes recientes: ~20 peticiones/día en Flash y ~500/día en Flash-Lite. Se reinicia a medianoche (hora del Pacífico) | Uso comercial permitido. En la capa gratuita Google puede usar los datos para mejorar sus productos | ⚠️ | [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [informe](https://www.scriptbyai.com/gemini-api-free-tier-limits/) |
| Guiones (respaldo) | Groq API, capa gratuita | Por modelo (p. ej. ~1K peticiones/día en gpt-oss-120b). Sin tarjeta según su foro | Modelos abiertos (Apache 2.0 / Llama) | ⚠️ | [rate limits](https://console.groq.com/docs/rate-limits), [foro](https://community.groq.com/t/is-there-a-free-tier-and-what-are-its-limits/790) |
| Guiones (local) | Ollama + modelo de 7-8B | Ilimitado, pero lento en CPU (~1-3 min por guion) | Depende del modelo (Qwen/Gemma permiten uso comercial) | ⚠️ calidad | — |
| Voz | Piper TTS, voz `es_ES-davefx-medium` | Local e ilimitado | Código: GPL-3.0 (piper1-gpl; uso como herramienta, el audio es tuyo). Dataset de la voz: **CC0** | ✅ | [MODEL_CARD davefx](https://huggingface.co/rhasspy/piper-voices/raw/main/es/es_ES/davefx/medium/MODEL_CARD) |
| Voz (principal) | Gemini API TTS `gemini-3.8-flash-tts`, plan gratuito | 3 peticiones/min y 10/día por proyecto de Google (AI Studio, 18-11-2026). La fábrica hace 1 petición por vídeo y se limita a `max_peticiones_dia` (6) | Google no reclama la propiedad del audio. En el plan gratuito puede usar los datos y revisarlos personas: no metas datos personales en los guiones | ⚠️ cupo pequeño | [speech generation](https://aistudio.google.com/docs/speech-generation) |
| Voz (alternativa) | Piper `sharvard` / `mls_10246` | Local | Dataset CC BY 3.0 / CC BY 4.0: **exige atribución** | ✅ | model cards |
| Voz | edge-tts | — | **API no oficial** de Microsoft: puede romperse o incumplir sus condiciones | ❌ por defecto | — |
| Imágenes | Cloudflare Workers AI, `flux-1-schnell` | 10.000 neuronas/día gratis (~170 imágenes de 1024² a 4 pasos, cálculo propio). Máx. 8 pasos. No figura entre los modelos restringidos al plan de pago (cambio de 28-07-2026) | Pesos FLUX.1 [schnell] Apache 2.0. La página enlaza los ToS de BFL | ⚠️ falta confirmar que el plan gratuito no pida tarjeta | [pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/), [modelo](https://developers.cloudflare.com/workers-ai/models/flux-1-schnell/), [changelog](https://developers.cloudflare.com/changelog/post/2026-07-28-models-require-workers-paid/) |
| Imágenes | Pollinations.ai | Anónimo: ~1 petición cada 15 s, posible marca de agua | Uso comercial **no claro**; una fuente dice que la capa gratuita es no comercial | ❌ para producción | [APIDOCS](https://github.com/pollinations/pollinations/blob/master/APIDOCS.md), [ayautomate](https://www.ayautomate.com/free-models/pollinations) |
| Imágenes (local) | SD-Turbo / SDXS con OpenVINO en CPU | Ilimitado, ~10-40 s/imagen a 512 px | Varía según el modelo | ⚠️ calidad baja | — |
| Clips/fotos | Pexels API | Gratis con clave, pero **a 22-11-2026 la emisión de claves nuevas está pausada**: no se usa por ahora (el código la salta sin clave). Prohíbe minería masiva y reventa aislada | Licencia Pexels: comercial sin atribución | ⚠️ pausada | [términos](https://help.pexels.com/hc/de-de/articles/900005880463) |
| Clips/fotos/música/SFX | Pixabay API | 100 peticiones/60 s, caché obligatoria de 24 h, sin descargas masivas. La API solo sirve imágenes y vídeo; la música se descarga a mano | Content License: comercial, sin atribución. Los ToS (20-10-2026) matizan productos comerciales | ⚠️ | [API docs](https://pixabay.com/api/docs/), [FAQ](https://pixabay.com/service/faq/) |
| Música/SFX | Freesound (filtro CC0) | Gratis con clave | Solo se usa CC0 | ⚠️ pendiente | — |
| Subtítulos | faster-whisper (local) | Ilimitado | MIT | ✅ | — |
| Montaje | FFmpeg + Python | Ilimitado | LGPL/GPL (uso como herramienta) | ✅ | — |
| Cola/BD | SQLite | — | Dominio público | ✅ | — |
| Ejecución | GitHub Actions | **Repos públicos: minutos ilimitados** en runners estándar. Repos privados: 2.000 min/mes (algunas fuentes dicen ahora 12 $/mes de crédito) | — | ✅ / ⚠️ | [billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions) |
| Ejecución | Programador de tareas de Windows (local) | Ilimitado; el PC debe estar encendido | — | ✅ | — |
| Publicación | YouTube Data API v3 | 10.000 unidades/día por defecto. El coste de `videos.insert` cambió (las fuentes dan 1.600, 100 o 1 unidad en un cubo de subidas de 100/día): se comprobará en la consola. **Los proyectos sin verificar creados después del 28-07-2020 suben en privado** hasta pasar la auditoría | Gratis | ✅ | [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert), [auditoría](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits) |
| Publicación | TikTok Content Posting API | Sin auditar: solo `SELF_ONLY` (privado), cuenta privada, máx. 5 usuarios/24 h. ~15 publicaciones/día por creador. Auditoría: días a 2 semanas | Gratis | ✅ | [direct post](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post), [guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines) |
| Publicación | Instagram Graph API (Reels) | Límite consultable en `/content_publishing_limit`. En modo desarrollo funciona con tu propia cuenta (rol Instagram Tester) **sin revisión de app** | Gratis | ⚠️ secundaria | [content publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing/) |
| Avisos | Bot de Telegram (Bot API) | Gratis; envío de vídeos de hasta 50 MB | — | ✅ | — |
| Montaje (aceleración) | OpenCV (`opencv-python-headless` 5.1) | Local | Apache 2.0 | ✅ | pip metadata |
| Zonas horarias | `tzdata` | Local | Apache 2.0 | ✅ | — |
| Modelo Whisper | `Systran/faster-whisper-small` | Local (se descarga de Hugging Face la primera vez) | MIT | ✅ | — |
| Fuentes tipográficas | Arial Bold (Windows) / DejaVu Sans Bold (Linux) | — | DejaVu: licencia libre. Para no depender de fuentes del sistema, coloca una OFL (p. ej. Anton) en `fonts/` | ⚠️ | — |

| Fuentes históricas | API de Wikipedia (MediaWiki Action API, `es.wikipedia.org/w/api.php`) | Gratis; se identifica con User-Agent y guarda caché de 30 días | Textos CC BY-SA: solo se usan como fuente de hechos (el guion se redacta de nuevo y se enlaza la fuente) | ✅ | — |

## Decisiones tomadas tras la verificación

- **Guiones**: Gemini (capa gratuita) → Groq → semillas escritas a mano. Se piden 5 guiones por petición para gastar menos cuota. En la prueba del 22-11-2026 Gemini respondió `503 high demand`: el respaldo funcionó.
- **Voz**: Gemini TTS (voz `Charon`, estilo de narrador de misterio con acento peninsular) con una sola petición por vídeo, cortada por silencios, como en granja-de-reels. Los reintentos de QA reutilizan el audio (`data/videos/<id>/voz_gemini_bruto.wav`). Un 429 marca el día como agotado y la fábrica sigue con Piper `es_ES-davefx-medium` (dataset CC0, sin atribución obligatoria). Prueba del 22-11-2026: 39,2 s y cortes exactos en los 6 segmentos. Se descartan por defecto `sharvard` y `mls_*`, que exigen atribución, y `edge-tts`, que es una API no oficial.
- **Imágenes**: Cloudflare FLUX.1 [schnell] es la principal. Pollinations se descarta por falta de claridad en el uso comercial. Tu equipo no tiene GPU dedicada (Iris Xe), así que no se usa Stable Diffusion local.
- **Instagram**: se usa la *API de Instagram con inicio de sesión de Instagram*, que no necesita página de Facebook. En modo desarrollo publica en tu propia cuenta con rol de tester, sin revisión de app.
- **Ejecución**: GitHub Actions en un repositorio **público** (minutos ilimitados). El estado se guarda en la rama `estado` y los vídeos en cola en una release.
- **Etiquetado IA nativo** (comprobado en documentación/changelogs): YouTube `status.containsSyntheticMedia`, TikTok `post_info.is_aigc` y Instagram `is_ai_generated`, este último en el changelog de 2026 de la Instagram Platform.
