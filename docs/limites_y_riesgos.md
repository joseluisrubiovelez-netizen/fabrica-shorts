# Límites del plan gratuito y riesgos

Informe honesto a fecha 2026-11-22. Las cifras marcadas como **medido** salen de las pruebas reales en tu portátil. Las marcadas como **estimado** son cálculos a partir de la documentación y no se han comprobado en producción.

## 1. ¿Cuántos vídeos al día son viables?

**3 al día es viable y holgado; 6 es el techo práctico.** El cuello de botella no es la generación, sino la publicación (cuota de YouTube) y tu revisión en modo `review`.

| Recurso | Límite gratuito | Consumo por vídeo | Máx. vídeos/día | Tipo |
|---|---|---|---|---|
| Gemini (guiones) | ~20 peticiones/día en Flash y ~500 en Flash-Lite (no publicado oficialmente) | 1 petición = 5 guiones | >100 | estimado |
| Groq (respaldo) | ~1.000 peticiones/día según el modelo | 1 petición = 5 guiones | >1.000 | estimado |
| Cloudflare FLUX | 10.000 neuronas/día | ~4-6 imágenes ≈ 300-350 neuronas | ~30 | estimado |
| Pexels / Pixabay | Pixabay: 100 peticiones/min, con caché obligatoria de 24 h | 0-2 búsquedas | sin límite práctico | doc. |
| YouTube Data API | 10.000 unidades/día; el coste de `videos.insert` es ambiguo en la doc (1.600, 100 o 1 unidad en un cubo de 100 subidas) | 1 subida | **6** en el peor caso | doc. |
| Instagram | Límite propio por cuenta (consultable en `/content_publishing_limit`) | 1 publicación | ≥ 25 | estimado |
| TikTok | ~15 publicaciones/día por creador; sin auditoría, solo privado | 1 publicación | 15 (manual: lo que subas) | doc. |
| GitHub Actions | Ilimitado en repositorio público | ~3-5 min de runner | sin límite práctico | doc. |

## 2. Tiempo de generación por vídeo

Medido en tu portátil (i5-1340P, 16 GB, sin GPU), vídeos de 30-35 s:

| Etapa | Media | Rango |
|---|---|---|
| Voz (Piper) | 3 s | 1-7 s |
| Subtítulos (Whisper `small`, incluye carga del modelo) | 29 s | 12-58 s |
| Visuales (procedurales en la prueba; con FLUX/stock añade descarga ≈ 5-20 s, estimado) | 6 s | 3-10 s |
| Música, SFX y mezcla | 6 s | 5-8 s |
| Montaje y codificación | 51 s | 34-84 s |
| QA | 24 s | 18-42 s |
| **Total por vídeo (medido, 10 vídeos)** | **119 s** | **82-169 s** |

Resultado de la prueba: 13 vídeos intentados, **10 superaron el QA**. Uno se descartó por un gancho demasiado largo (3,7 s) tras 2 regeneraciones; el guion semilla se corrigió. Otro se descartó por ser un guion histórico generado antes de la verificación por fuentes, y otro se interrumpió a propósito.
Ningún recurso quedó sin fuente o licencia registrada. Con 3 vídeos al día, la generación ocupa unos 6 minutos de CPU diarios.

En GitHub Actions (runner Linux de 4 vCPU) se espera un tiempo similar o menor, porque desaparece el retraso de ~5 s que añade Windows al lanzar cada proceso de FFmpeg. **No lo he medido todavía**: lo verás en el primer `Run workflow`.

## 3. Qué calidad se pierde frente a herramientas de pago

| Parte | Gratis (este sistema) | De pago típico | Pérdida |
|---|---|---|---|
| Voz | Piper `davefx`: clara y peninsular, pero con prosodia plana; no susurra ni dramatiza | ElevenLabs, voces con emoción | **Alta.** Es lo que más se nota en terror. |
| Imágenes | FLUX.1 [schnell] a 4-8 pasos, cuadrada y recortada a vertical | FLUX Pro, Midjourney: vertical nativo y más detalle | Media: algo menos de nitidez y control |
| Movimiento | Ken Burns, fundidos, grano y clips de stock | Vídeo IA (Runway, Kling, Veo) | Media-alta: no hay "planos" animados reales |
| Música | Pistas Pixabay que añades a mano o drones generados por código | Bibliotecas premium con stems | Baja-media |
| Guiones | Gemini/Groq gratis + validación | Modelos frontera de pago | Baja; la revisión en `review` compensa |
| Subtítulos | Whisper local alineado con el guion exacto | Herramientas comerciales | Ninguna relevante |
| Respaldo sin claves | Fondos procedurales (siluetas y niebla) | — | Solo para pruebas: **no publiques vídeos con fondos procedurales** |

Alternativas gratuitas para mejorar la voz:
1. Probar otras voces de Piper. Algunas exigen atribución, que el sistema puede añadir a la descripción.
2. Entrenar o ajustar una voz Piper propia con tu grabación. Requiere tiempo y, para hacerlo cómodo, GPU (Colab gratuito).

`edge-tts` suena mejor, pero es una API **no oficial** de Microsoft: puede romperse o incumplir sus condiciones. Por eso no está activada.

## 4. Riesgos y mitigaciones

### Políticas de plataforma
| Riesgo | Mitigación |
|---|---|
| **Contenido repetitivo o "producido en masa"**: YouTube puede rechazar la monetización (política de contenido inauténtico) y TikTok e Instagram reducen el alcance del contenido poco original | 3 series con identidad propia, 8 estructuras × 6 ganchos rotados, deduplicación de temas y ganchos, visuales y música distintos por vídeo, guiones originales, **revisión humana** las 2 primeras semanas. Mantén la cadencia en 2-3 al día, no más. |
| Contenido IA sin etiquetar | Etiqueta nativa por API en las tres plataformas. En las subidas manuales, recordatorio en el aviso de Telegram. |
| **Desinformación en la serie histórica.** Comprobado en la prueba: Gemini inventó sucesos con apariencia de verdad (un incendio del teatro de Córdoba en 1842, "expediciones perdidas" en Belate, una cita de Las Huelgas) y citaba una URL real de Wikipedia que no los respalda | Rediseño: el tema sale de una lista curada (`seeds/temas_historicos.yaml`); el LLM recibe el texto del artículo (API oficial de Wikipedia) y solo puede usar esos hechos; un segundo paso del LLM verifica cada afirmación contra la fuente y **descarta** el guion si alguna no está respaldada; la fuente se fija por código, no la elige el LLM. Los guiones inventados se descartaron. Aun así, el verificador también es un LLM: **revisa los históricos en `review`**. Las semillas históricas se contrastaron a mano con Wikipedia y se corrigieron tres matices. |
| Proyecto de YouTube sin auditar: vídeos privados | Aviso automático y paso manual a público mientras llega la auditoría (SETUP §7). |
| TikTok sin auditar: solo privado | Modo `manual` por defecto. La auditoría puede rechazarse para herramientas de uso propio, así que el plan B manual puede ser permanente. |
| Token de YouTube caducado (app en "Testing") | SETUP pide publicar la app OAuth. Aviso `TokenCaducado` por Telegram con instrucciones. |
| Token de Instagram (60 días) | Renovación automática cada 30 días, guardada cifrada. |

### Monetización
- **YouTube Partner Program**: requiere 1.000 suscriptores y 10 M de vistas de Shorts en 90 días. Además pasa una revisión humana en la que el contenido IA muy plantillado suele rechazarse por "contenido repetitivo". La voz sintética plana aumenta ese riesgo.
- **TikTok**: el programa de recompensas para creadores exige vídeos de **más de 1 minuto**. Los Shorts de 20-45 s **no** cuentan. Si quieres monetizar en TikTok, habría que crear un formato largo aparte.
- **Instagram**: los programas de bonificación varían por país y por invitación; no cuentes con ellos.
- Conclusión: el canal puede crecer, pero la monetización directa es incierta. Lo más realista es construir audiencia primero.

### Licencias
| Recurso | Riesgo | Mitigación |
|---|---|---|
| Pixabay | Sus Términos de Servicio (20-10-2026) matizan el uso en productos comerciales | Solo se usa como fondo editorial, no se vende el recurso suelto; queda registrado en la BD con URL. |
| Pexels | Los clips pueden mostrar personas o marcas | Filtro de palabras de personas en URL y etiquetas; revisión humana. |
| FLUX.1 [schnell] | Pesos Apache 2.0; la página de Cloudflare enlaza a los Términos de Servicio de BFL | Revisa esos ToS si cambian; registro de modelo y prompt por imagen. |
| Voz Piper `davefx` | Dataset CC0; Piper es GPL-3.0 y solo se usa como herramienta | Sin atribución obligatoria. Queda registrado igualmente. |
| Música manual | Que alguien añada una pista sin licencia | El código **solo** usa pistas listadas en `licencias.yaml` con fuente y licencia; el QA falla si un recurso no tiene licencia. |
| Fuentes tipográficas | Arial es de Windows | En Actions se usa DejaVu (libre). Recomendado: añadir Anton o Bebas Neue (OFL) en `fonts/`. |

### Técnicos
| Riesgo | Mitigación |
|---|---|
| El cron de GitHub se retrasa en horas punta | Ejecución cada hora + tolerancia de 3 h por hueco; los huecos perdidos se registran. |
| GitHub desactiva los workflows programados de repos públicos tras **60 días sin actividad** | Cada ejecución hace commit en la rama `estado`. Confírmalo en el primer mes: si ves un aviso de desactivación, haz cualquier commit. |
| Repositorio público | El código, la BD (guiones, títulos) y la release de cola son visibles. Las claves están en Secrets y los tokens cifrados con Fernet. Si filtras `FABRICA_CLAVE_TOKENS`, rota todos los tokens. |
| Cambios en capas gratuitas o APIs (como el recorte de Gemini en 2026) | Cadena de proveedores con respaldo + semillas; `docs/herramientas.md` con fecha: revísalo cada 2-3 meses. |
| Gemini saturado (503) | Probado: pasa a Groq o a las semillas. |
