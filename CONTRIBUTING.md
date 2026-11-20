# Contribuir a StemForge

¡Gracias por querer mejorar StemForge! Puedes ayudar de dos formas.

## Reportar un problema o proponer una idea

Abre un [Issue](https://github.com/vicvinue/stemforge/issues) y cuenta:

- qué hiciste, qué esperabas y qué pasó;
- tu equipo (Mac o Windows, y con qué tarjeta gráfica) y la versión de StemForge (aparece en el pie de la ventana);
- si puedes, el registro de la app: `~/Library/Logs/StemForge.log` (Mac) o
  `%LOCALAPPDATA%\StemForge\logs\StemForge.log` (Windows).

## Proponer cambios en el código (pull request)

1. Si el cambio es grande, abre antes un Issue para conversarlo y no trabajar en balde.
2. Haz un *fork* del repositorio y crea una rama para tu cambio.
3. Prepara el entorno y ejecuta la app desde el código siguiendo la
   [guía para desarrolladores](docs/DESARROLLO.md).
4. Comprueba que los tests pasan: `.venv/bin/python -m pytest -q`.
5. Abre un *pull request* hacia `main` explicando qué cambia y por qué. Si toca la interfaz, adjunta
   una captura.

El autor revisa cada propuesta y decide si la incorpora. Solo el autor publica versiones de StemForge.

## Condiciones

StemForge **no** es software libre: su código está a la vista, pero su [licencia](LICENSE) no permite
redistribuirlo ni venderlo. Al contribuir:

- Puedes descargar, compilar, ejecutar y modificar el código **solo para preparar y probar tus
  contribuciones**. No publiques ni compartas compilaciones propias ni versiones modificadas.
- Declaras que tu contribución es obra tuya (o que tienes derecho a aportarla) y concedes al autor
  permiso para usarla, modificarla y distribuirla como parte de StemForge (punto 3 de la
  [licencia](LICENSE)). Sigues siendo su autor.
