# Efecto 3D para imágenes

Convierte cualquier imagen en un clip de vídeo con **efecto 3D**: calcula qué está cerca y qué
está lejos, y mueve la cámara entre esos planos (parallax), con el fondo un poco desenfocado.
Es la misma técnica que usa la fábrica de shorts, pero en una carpeta que puedes copiar donde
quieras y usar con cualquier vídeo.

## Uso rápido (Windows)

1. Copia esta carpeta `efecto3d` donde quieras.
2. **Arrastra** una o varias imágenes, o una carpeta, **encima de `EFECTO3D.bat`**.
3. La primera vez prepara Python y descarga el modelo de profundidad (~100 MB): tarda unos minutos.
4. Los vídeos aparecen en una carpeta `salida_3d` junto a tus imágenes.

Necesitas [Python 3.10+](https://www.python.org/downloads/) con **Add to PATH** marcado.
FFmpeg no hace falta: si no lo tienes, se usa el que trae `imageio-ffmpeg`.

## Desde la terminal

```powershell
.\EFECTO3D.bat foto.jpg
.\EFECTO3D.bat C:\mis_fotos --formato horizontal --dur 4
.\EFECTO3D.bat a.jpg b.jpg c.jpg --unir --salida C:\videos\historia.mp4
.\EFECTO3D.bat foto.png --mov orbita --intensidad 1.5 --guardar-profundidad
```

(En Mac o Linux: `pip install -r requirements.txt` y `python efecto3d.py …` con las mismas opciones.)

| Opción | Qué hace | Por defecto |
|---|---|---|
| `--formato` | `vertical` (1080x1920), `horizontal` (1920x1080), `cuadrado`, `4k-vertical`, `4k-horizontal`, `original` o `ANCHOxALTO` | `vertical` |
| `--dur` | segundos por imagen | `5` |
| `--mov` | `zoom_in`, `zoom_out`, `pan_izq`, `pan_der`, `pan_arriba`, `pan_abajo`, `zoom_in_izq`, `zoom_out_der`, `orbita` o `aleatorio` | `aleatorio` |
| `--intensidad` | separación entre planos: 0.5 suave · 1 normal · 1.5 marcado | `1` |
| `--desenfoque` | desenfoque del fondo de 0 (nada) a 1 (mucho) | `0.5` |
| `--unir` | un solo vídeo con todas las imágenes y fundidos entre ellas | no |
| `--salida` | carpeta de salida, o archivo `.mp4` con `--unir` | `salida_3d/` |
| `--calidad` | CRF de H.264, menor = mejor y más pesado | `18` |
| `--fps` | fotogramas por segundo | `30` |
| `--guardar-profundidad` | guarda también el mapa de profundidad en PNG (blanco = cerca), útil en otros editores | no |
| `--sin-modelo` | no usa el modelo: estimación aproximada, más pobre | no |
| `--semilla` | número para que `aleatorio` repita los mismos movimientos | — |

## Consejos

- Funciona mejor con imágenes que tienen **primer plano y fondo claros**: una figura delante de
  un paisaje, un pasillo, un edificio con algo delante. En texturas planas o texto apenas se nota.
- Los clips salen **sin audio**: añádelos a tu editor (CapCut, DaVinci, Premiere…) como cualquier vídeo.
- Si ves bordes estirados alrededor de una figura, baja `--intensidad` a 0.6–0.8.
- Solo procesa **imágenes**. Para un vídeo, exporta el fotograma que quieras como imagen.

## Créditos

Modelo de profundidad: [Depth Anything V2 Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Small)
(licencia Apache-2.0), en su versión ONNX de `onnx-community`.
