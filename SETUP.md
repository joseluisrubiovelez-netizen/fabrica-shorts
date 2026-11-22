# SETUP — lo que tienes que hacer tú (una sola vez)

Tiempo total: unas 2 horas de trabajo, más los días que tarden las aprobaciones.
Coste: 0 €. **Ningún paso pide tarjeta.** Si algún servicio te la pide, para y avísame: no la metas.

---

## 0. Antes de empezar: lo que tarda y qué hacer mientras tanto

| Plataforma | Qué hay que aprobar | Cuánto tarda | Mientras tanto |
|---|---|---|---|
| **YouTube** | Auditoría de la API ("Audit and Quota Extension Form") | De días a varias semanas | Los vídeos subidos por API quedan **privados**. El sistema te avisa por Telegram; los pasas a público en YouTube Studio con 2 clics. |
| **TikTok** | Revisión de la app y auditoría de Content Posting API | De días a 2 semanas, y **pueden rechazarla** si la app es solo para ti | Modo `manual`: el bot de Telegram te manda el vídeo y el texto, y lo subes desde el móvil en 10 segundos. Es el modo por defecto. |
| **Instagram** | Nada, si solo publicas en **tu** cuenta: el modo desarrollo con rol de tester basta | Inmediato | — |
| Cloudflare, Gemini, Groq, Pexels, Pixabay, Telegram | Nada | Minutos | — |

> Empieza por pedir la auditoría de YouTube y la revisión de TikTok el **primer día**, porque son lo que más tarda.

---

## 1. Instalar en tu PC (Windows)

1. **Python 3.12**: ya lo tienes. Si no, instálalo desde python.org y marca "Add to PATH".
2. **FFmpeg**: ya lo tienes (`winget install Gyan.FFmpeg`).
3. **Git**: ya lo tienes.
4. Abre PowerShell en la carpeta del proyecto y ejecuta:

```powershell
.\make.ps1 setup
```

Esto crea `.venv`, instala dependencias, descarga la voz (`es_ES-davefx-medium`, unos 63 MB, desde Hugging Face), copia `.env.example` a `.env` y comprueba la configuración.

Primera prueba, sin ninguna clave:

```powershell
.\make.ps1 dry-run
```

Debe aparecer un vídeo en `data/videos/00001/final.mp4`.

---

## 2. Telegram (avisos y aprobaciones) — 5 min

1. En Telegram, habla con **@BotFather** → `/newbot` → ponle nombre. Copia el token en `TELEGRAM_BOT_TOKEN`.
2. Escríbele cualquier cosa a tu bot.
3. Abre en el navegador `https://api.telegram.org/bot<TOKEN>/getUpdates` y copia `"chat":{"id": ...}` en `TELEGRAM_CHAT_ID`.

El bot solo obedece a ese chat. Comandos: `/aprobar 12`, `/descartar 12`, `/estado`.

## 3. Guiones: Gemini y Groq — 5 min

- **Gemini**: entra en https://aistudio.google.com → *Get API key* → `GEMINI_API_KEY`. Los límites reales de tu proyecto los ves en AI Studio, en *Rate limits*.
- **Groq** (respaldo): entra en https://console.groq.com → *API Keys* → `GROQ_API_KEY`.

Ten en cuenta que en la capa gratuita de Gemini Google puede usar los textos para mejorar sus productos. Aquí no hay datos personales, así que no es un problema.

## 4. Imágenes IA: Cloudflare Workers AI — 10 min

1. Regístrate en https://dash.cloudflare.com (plan Free, **sin tarjeta**).
2. Copia el **Account ID** (aparece en *Workers & Pages* → *Overview*) en `CLOUDFLARE_ACCOUNT_ID`.
3. Ve a *My Profile* → *API Tokens* → *Create Token* → plantilla **"Workers AI"** y copia el token en `CLOUDFLARE_API_TOKEN`.

Tienes 10.000 "neuronas" al día gratis, que dan aproximadamente 170 imágenes. Si se agotan, el sistema pasa a stock y, si tampoco hay, a fondos procedurales.

## 5. Stock: Pexels y Pixabay — 5 min

- https://www.pexels.com/api/ → *Your API key* → `PEXELS_API_KEY`
- https://pixabay.com/api/docs/ (con la sesión iniciada; la clave aparece en la página) → `PIXABAY_API_KEY`

## 6. Música (opcional, recomendado)

La API de Pixabay no da acceso a la música. Descarga a mano 10-20 pistas ambientales y oscuras de https://pixabay.com/music/ y guárdalas en `assets/musica/`. Después, **regístralas** en `assets/musica/licencias.yaml` (ahí tienes el formato). Las pistas que no estén registradas no se usan nunca. Sin pistas, el sistema genera música ambiental propia.

## 7. YouTube — 30 min + auditoría

1. Crea el canal (recomendado: canal de marca) con la cuenta de Google que vayas a usar.
2. Entra en https://console.cloud.google.com → **Nuevo proyecto**.
3. En *APIs y servicios* → *Biblioteca*, habilita **YouTube Data API v3** y **YouTube Analytics API**.
4. *Pantalla de consentimiento OAuth* (o *Google Auth Platform*):
   - Tipo **Externo**. Rellena nombre y correo.
   - Ámbitos: `youtube.upload`, `youtube.readonly` y `yt-analytics.readonly`.
   - Añádete como usuario de prueba.
   - **Importante:** después pulsa **"Publicar aplicación"** (*In production*). Si la dejas en *Testing*, el token caduca cada 7 días. Google te avisará de que la app "no está verificada"; para uso propio no pasa nada.
5. *Credenciales* → *Crear ID de cliente OAuth* → tipo **Aplicación de escritorio**. Copia el ID en `YOUTUBE_CLIENT_ID` y el secreto en `YOUTUBE_CLIENT_SECRET`.
6. Ejecuta lo siguiente, autoriza en el navegador con la cuenta del canal y copia el `YOUTUBE_REFRESH_TOKEN` que te muestra:

```powershell
.\.venv\Scripts\python.exe -m fabrica token-youtube
```

7. **Para que no queden privados**: rellena el formulario de auditoría en https://support.google.com/youtube/contact/yt_api_form ("YouTube API Services - Audit and Quota Extension"). Explica que es una herramienta interna para publicar en tu propio canal. Hasta que lo aprueben, los vídeos quedan privados y te llega un aviso para hacerlos públicos a mano.

El sistema marca cada vídeo como **contenido sintético** (`containsSyntheticMedia`) y **no dirigido a menores**.

## 8. TikTok — 30 min + revisión

1. Cuenta de TikTok del canal. Una cuenta **personal (normal)** sirve: la Content Posting API funciona con cuentas personales. Mientras la app no esté auditada, la API exige que la cuenta sea **privada**, así que en modo `manual`, el de por defecto, no hace falta tocar nada.
2. Entra en https://developers.tiktok.com → *Manage apps* → **Create app**.
3. Añade los productos **Login Kit** y **Content Posting API** (activa *Direct Post*).
4. Pide los ámbitos `user.info.basic`, `video.upload`, `video.publish` y `video.list`.
5. Redirect URI: necesita una URL `https` tuya. Sirve tu página de GitHub Pages, por ejemplo `https://TU_USUARIO.github.io/`. Guárdala en `TIKTOK_REDIRECT_URI`.
6. Copia la *Client key* y el *Client secret* en `.env` y ejecuta lo siguiente. Pega en la terminal la URL a la que te redirige tras autorizar y copia el `TIKTOK_REFRESH_TOKEN` que te muestra:

```powershell
.\.venv\Scripts\python.exe -m fabrica token-tiktok
```

7. Envía la app a revisión y solicita la **auditoría de Content Posting API**. Te pedirán URL de política de privacidad y términos (puedes publicarlas en GitHub Pages) y un vídeo de demostración.
8. Mientras no esté auditada, TikTok solo permite publicar en **privado** (`SELF_ONLY`) y con la cuenta en privado. Por eso viene `modo: manual` en `config.yaml`. Cuando te aprueben, cambia a `modo: api` y `privacidad: PUBLIC_TO_EVERYONE`.

Con la API, el sistema marca `is_aigc` (etiqueta "Generado por IA"). Si subes a mano, **activa tú** "Contenido generado por IA" en los ajustes de la publicación; el aviso de Telegram te lo recuerda.

## 9. Instagram — 20 min (sin revisión)

Uso la **API de Instagram con inicio de sesión de Instagram**, que **no necesita página de Facebook**.

1. En la app de Instagram, cambia la cuenta a **profesional** (Creador o Empresa) en *Configuración* → *Tipo de cuenta*.
2. Entra en https://developers.facebook.com → *Mis apps* → **Crear app** (caso de uso: gestionar contenido de Instagram).
3. Añade el producto **Instagram** → *Configuración de la API con inicio de sesión de Instagram*.
4. En *Roles de la app* → *Roles* → **Evaluadores de Instagram**, añade tu cuenta.
5. Acepta la invitación desde Instagram: *Configuración* → *Apps y sitios web* → *Invitaciones de evaluador*.
6. En el panel de la app, *Generar token de acceso* para tu cuenta, con los permisos `instagram_business_basic` e `instagram_business_content_publish`.
7. Copia el **ID de usuario** en `INSTAGRAM_USER_ID` y el token en `INSTAGRAM_ACCESS_TOKEN`.

En **modo desarrollo esto basta para tu propia cuenta**: no necesitas revisión de app porque solo publicas en cuentas con rol en la app. El token dura 60 días y el sistema lo renueva solo cada 30 (requiere `FABRICA_CLAVE_TOKENS`). Cada Reel se marca con `is_ai_generated` (etiqueta "Info de IA").

## 10. Clave de cifrado de tokens — 1 min

```powershell
.\.venv\Scripts\python.exe -m fabrica clave
```

Copia el resultado en `FABRICA_CLAVE_TOKENS`. Sirve para cifrar los tokens que rotan (TikTok, Instagram) antes de guardarlos en el repositorio público.

## 11. Comprobar

```powershell
.\.venv\Scripts\python.exe -m fabrica verificar
```

```powershell
.\make.ps1 test
```

## 12. GitHub Actions (ejecución automática gratis) — 15 min

1. Crea un repositorio **público** en GitHub. En los públicos los minutos de Actions son ilimitados; en los privados hay una cuota mensual.
2. Sube el código. `.env` **no** se sube porque está en `.gitignore`.
3. En *Settings* → *Secrets and variables* → *Actions*:
   - En **Secrets**, crea uno por cada variable de tu `.env` que tenga valor, con el mismo nombre.
   - En **Variables**, crea `FABRICA_MODO` = `review`.
4. En la pestaña *Actions*, abre **fabrica** → *Run workflow*, con modo `dry-run` la primera vez.
5. Desde entonces se ejecuta **cada hora** él solo.

Ten en cuenta que en un repositorio público el código y la base de datos (guiones, títulos, IDs de publicación) son visibles. Los tokens van cifrados y las claves están en Secrets.

## 13. Uso diario

- **Semanas 1-2 (`review`)**: te llega cada vídeo por Telegram; respondes `/aprobar N` o `/descartar N`. Solo se publica lo aprobado, a las horas de `config.yaml`.
- **Después (`auto`)**: cambia la variable `FABRICA_MODO` a `auto`. Si algo falla (token caducado, cuota agotada, QA fallido), te llega un aviso.
- **Los lunes** se genera el informe semanal en `data/informes/` (en la rama `estado`).
