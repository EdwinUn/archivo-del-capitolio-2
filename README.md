# archivo-del-capitolio-2
El Sistema de Gestión Documental Inteligente es una aplicación web que permite subir, leer y organizar documentos PDF de manera eficiente.
El sistema puede leer el contenido de los archivos tanto de forma directa como mediante OCR, utilizando PyTesseract y pdf2image, lo que permite extraer texto incluso de documentos escaneados.

Cada documento puede ser etiquetado manualmente y, además, el sistema sugiere etiquetas automáticas basadas en el contenido analizado.
También permite buscar, filtrar y gestionar documentos de forma accesible, manteniendo metadatos como el nombre, fecha de carga y etiquetas.

-Tecnologías
Python

Reflex (para la interfaz web)

SQLModel (gestión de base de datos)

Radix Themes

Pathlib (manejo de rutas y archivos)

PyPDF2 (lectura de contenido PDF)

PyTesseract (OCR)

pdf2image (conversión de PDF a imagen para análisis OCR)

-Instalación y ejecución

El acceso se realiza directamente desde el enlace del despliegue web.

-Uso

El sistema se utiliza por medio de la web.
Los usuarios pueden:

Subir archivos PDF al sistema.

Visualizar el contenido leído.

Etiquetar los documentos o usar las etiquetas sugeridas automáticamente.

Buscar y filtrar documentos por etiquetas.

Consultar los metadatos almacenados.

-Autores

May Pech Aldair Emanuel

Un Uicab Edwin Geovanni

Yama Uitz Adrian Enrique

Cervera Xool Javier Antonio

Bates Espada Carlos Alfredo

- Estado actual

Versión inicial del sistema funcional con carga de documentos, lectura OCR y etiquetado básico.
Futuras mejoras planeadas incluyen:

Panel de administración de usuarios.

Integración de un motor de búsqueda más avanzado.

API REST para conexión con otros sistemas.