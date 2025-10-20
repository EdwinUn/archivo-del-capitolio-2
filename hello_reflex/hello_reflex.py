# hello_reflex.py
# Sistema de Gestión Documental Inteligente SIN Chakra (compatible con Reflex core)

from __future__ import annotations
import os, re, string
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

import reflex as rx
from sqlmodel import Field, select
from PyPDF2 import PdfReader
import pdfplumber

# --------- Rutas ---------
DOCS_DIR = Path("assets/docs")
DOCS_DIR.mkdir(parents=True, exist_ok=True)

# --------- Modelo ---------
class Document(rx.Model, table=True):
    id: int | None = Field(default=None, primary_key=True)
    filename: str
    filepath: str
    text_snippet: str = ""
    tags_str: str = ""
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

    @staticmethod
    def normalize_tags(tags: List[str]) -> str:
        clean = sorted({t.strip().lower() for t in tags if t and t.strip()})
        return ",".join(clean)

    @property
    def tags(self) -> List[str]:
        if not self.tags_str:
            return []
        return [t.strip() for t in self.tags_str.split(",") if t.strip()]

# --------- Utilidades PDF y Modelo de IA (TF-IDF/Frecuencia) ---------
STOPWORDS = {
    "el","la","los","las","un","una","unos","unas","de","del","al","a","y","o","u","que","en","se","para","por",
    "con","sin","como","es","son","ser","fue","era","han","ha","hay","más","menos","ya","no","sí","lo","le","les",
    "esto","esta","este","estas","estos","eso","esa","ese","esos","esas","muy","también","entre","sobre","hasta",
    "desde","cuando","qué","cuál","cual","donde","porque","ante","bajo","cabe","contra","hacia","según","mediante",
    "documento","pdf","archivo","archivos","capitolio"
}

def _clean(s: str) -> str:
    s = s.replace("\x00", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def extract_text_from_pdf(path: Path) -> str:
    text = ""
    try:
        reader = PdfReader(str(path))
        parts = []
        for p in reader.pages:
            try:
                parts.append(p.extract_text() or "")
            except Exception:
                parts.append("")
        text = _clean(" ".join(parts))
    except Exception:
        text = ""

    if not text or len(text) < 40:
        try:
            with pdfplumber.open(str(path)) as pdf:
                parts = []
                for pg in pdf.pages:
                    try:
                        parts.append(pg.extract_text() or "")
                    except Exception:
                        parts.append("")
            alt = _clean(" ".join(parts))
            if len(alt) > len(text):
                text = alt
        except Exception:
            pass

    if (not text or len(text) < 40) and os.getenv("ENABLE_OCR", "0") in {"1", "true", "TRUE"}:
        try:
            import pytesseract
            from pdf2image import convert_from_path
            imgs = convert_from_path(str(path))
            ocr_txts = [pytesseract.image_to_string(im, lang="spa+eng") for im in imgs]
            text_ocr = _clean(" ".join(ocr_txts))
            if len(text_ocr) > len(text):
                text = text_ocr
        except Exception:
            pass
    return text

def suggest_tags_from_text(text: str, k: int = 6) -> List[str]:
    if not text:
        return []
    t = text.lower()
    t = t.translate(str.maketrans({c: " " for c in string.punctuation + "¿¡“”¨´`‘’"}))
    tokens = [w for w in t.split() if len(w) > 2 and w not in STOPWORDS and not w.isdigit()]
    if not tokens:
        return []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(stop_words=list(STOPWORDS), max_features=800)
        X = vec.fit_transform([" ".join(tokens)])
        feats = vec.get_feature_names_out()
        scores = X.toarray()[0]
        order = scores.argsort()[::-1]
        raw = [feats[i] for i in order[:k*2]]
    except Exception:
        from collections import Counter
        raw = [w for w, _ in Counter(tokens).most_common(k*2)]
    out: List[str] = []
    for w in raw:
        w = w.strip().lower()
        if w and w not in out and re.search(r"[a-záéíóúñ]", w):
            out.append(w)
        if len(out) >= k:
            break
    return out

# --------- Estado ---------
class AppState(rx.State):
    query: str = ""
    tag_filter: str = ""
    edit_id: Optional[int] = None
    edit_tags_input: str = ""

    def set_query(self, v: str): self.query = v
    def set_tag_filter(self, v: str): self.tag_filter = v
    def set_edit_tags_input(self, v: str): self.edit_tags_input = v

    # NOTA: Los `rx.var` de `docs` y `all_tags` se re-evalúan en el backend 
    # cuando una acción (como `handle_upload`) ha terminado.

    @rx.var
    def docs(self) -> List[dict]:
        with rx.session() as s:
            rows = s.exec(select(Document).order_by(Document.uploaded_at.desc())).all()
        out: List[dict] = []
        for d in rows:
            out.append({
                "id": d.id,
                "filename": d.filename,
                "url": d.filepath,
                "tags": d.tags,
                "uploaded_at": d.uploaded_at.strftime("%Y-%m-%d %H:%M"),
                "snippet": (d.text_snippet[:280] + "…") if len(d.text_snippet) > 280 else d.text_snippet,
            })
        return out

    @rx.var
    def filtered_docs(self) -> List[dict]:
        q = (self.query or "").strip().lower()
        tf = (self.tag_filter or "").strip().lower()
        data = list(self.docs)
        if tf:
            data = [d for d in data if any(tf in t.lower() for t in d["tags"])]
        if q:
            data = [
                d for d in data
                if q in d["filename"].lower()
                or q in d["snippet"].lower()
                or any(q in t for t in d["tags"])
            ]
        return data

    @rx.var
    def all_tags(self) -> List[str]:
        tags = set()
        for d in self.docs:
            for t in d["tags"]:
                tags.add(t)
        
        # Etiquetas predeterminadas si la lista dinámica está vacía
        dynamic_tags = sorted(tags)
        if not dynamic_tags:
            return ["contrato", "factura", "informe", "legal", "personal", "manual", "2025"]

        return dynamic_tags

    async def handle_upload(self, files: List[rx.UploadFile]):
        if not files:
            return
        
        # Esta línea es clave para evitar la re-renderización excesiva durante la subida
        # y para asegurar que el listado de documentos se actualice al final.
        upload_actions = []

        for up in files:
            original = Path(up.filename).name
            unique = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f") + "_" + original
            dst = DOCS_DIR / unique
            
            data = await up.read()
            dst.write_bytes(data)

            text = extract_text_from_pdf(dst)
            snippet = (text or "")[:800]
            suggested = suggest_tags_from_text(text, k=6)

            with rx.session() as s:
                row = Document(
                    filename=original,
                    filepath=f"/docs/{unique}", 
                    text_snippet=snippet,
                    tags_str=Document.normalize_tags(suggested),
                )
                s.add(row)
                s.commit()
                # No se requiere un `upload_actions.append` explícito para la base de datos,
                # ya que se guardó sincrónicamente y los rx.vars se re-evaluarán.

        # MODIFICACIÓN CLAVE: Limpiar la cola de subida y luego devolver una acción 
        # para forzar la re-evaluación del estado.
        return [
            rx.upload_files.clear(),
            AppState.set_query(AppState.query), # Acción que fuerza la re-evaluación de rx.vars
        ]


    def start_edit_id(self, doc_id: int):
        """Busca en DB y abre el editor con las etiquetas actuales."""
        with rx.session() as s:
            row = s.get(Document, doc_id)
            if row:
                self.edit_id = doc_id
                self.edit_tags_input = ", ".join(row.tags)

    def cancel_edit(self):
        self.edit_id = None
        self.edit_tags_input = ""

    def save_tags(self):
        if self.edit_id is None:
            return
        csv = Document.normalize_tags([t for t in self.edit_tags_input.split(",")])
        with rx.session() as s:
            row = s.get(Document, self.edit_id)
            if row:
                row.tags_str = csv
                s.add(row)
                s.commit()
        self.cancel_edit()

    def delete_doc(self, doc_id: int):
        with rx.session() as s:
            row = s.get(Document, doc_id)
            if row:
                try:
                    fs = Path("assets") / Path(row.filepath.lstrip("/"))
                    if fs.exists():
                        fs.unlink(missing_ok=True)
                except Exception:
                    pass
                s.delete(row)
                s.commit()
        self.query = self.query

# --------- UI (solo core) ---------
def tag_pill(t: rx.Var[str] | str) -> rx.Component:
    return rx.box(
        t, padding="4px 8px", border_radius="12px", border="1px solid #ddd",
        margin_right="6px", margin_bottom="6px", display="inline-block", font_size="12px",
    )

def doc_row(d: rx.Var[dict]) -> rx.Component:
    doc_tags: rx.Var[List[str]] = d["tags"].to(List[str]) 
    
    tags_box = rx.box(
        rx.foreach(doc_tags, lambda t: tag_pill(t)),
        margin_top="8px",
    )

    editor = rx.cond(
        AppState.edit_id == d["id"],
        rx.box(
            rx.input(
                value=AppState.edit_tags_input,
                on_change=AppState.set_edit_tags_input,
                placeholder="contrato, factura, 2025",
                width="100%",
            ),
            rx.hstack(
                rx.button("Guardar", on_click=AppState.save_tags),
                rx.button("Cancelar", on_click=AppState.cancel_edit),
                spacing="2",
                margin_top="6px",
            ),
            margin_top="8px",
        ),
        rx.box()
    )

    return rx.box(
        rx.hstack(
            rx.vstack(
                rx.text(d["filename"], weight="bold"),
                rx.text(d["uploaded_at"], size="2", color="#666"),
                align_items="start",
                spacing="1",
            ),
            rx.spacer(),
            rx.link("Abrir / Descargar", href=d["url"], is_external=True),
            spacing="3",
            align_items="center",
        ),
        rx.text(d["snippet"], margin_top="6px"),
        tags_box,
        rx.hstack(
            rx.button("Editar etiquetas", on_click=lambda: AppState.start_edit_id(d["id"])),
            rx.button("Eliminar", on_click=lambda: AppState.delete_doc(d["id"]), color_scheme="red"),
            spacing="2",
            margin_top="8px",
        ),
        editor,
        padding="12px",
        border="1px solid #e5e5e5",
        border_radius="12px",
        _hover={"box_shadow": "0 2px 8px rgba(0,0,0,.06)"},
    )

def upload_zone() -> rx.Component:
    return rx.box(
        rx.text("Sube PDFs; sugeriremos etiquetas automáticamente.", size="2"),
        rx.upload(
            rx.button("Seleccionar PDF(s)"),
            accept={".pdf"}, multiple=True, max_files=10,
            border="2px dashed #cfcfcf", padding="18px", width="100%", margin_top="8px",
        ),
        rx.cond(
            rx.upload_files,
            rx.box(
                rx.text("Archivos listos para cargar:"),
                rx.foreach(rx.upload_files, lambda name: rx.text(name)),
                margin_top="10px",
                padding="8px",
                border="1px solid #ccc",
                border_radius="8px",
            ),
        ),
        rx.hstack(
            rx.button("Cargar a la biblioteca", on_click=lambda: AppState.handle_upload(rx.upload_files())),
            rx.text("Solo PDF • OCR opcional"),
            spacing="3",
            margin_top="8px",
        ),
        padding="12px", border="1px solid #eee", border_radius="12px", background_color="#fafafa",
    )

def search_bar() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.input(
                value=AppState.query,
                on_change=AppState.set_query,
                placeholder="Buscar por nombre, contenido o etiqueta…",
                width="100%",
            ),
            spacing="3",
            width="100%",
        ),
        rx.hstack(
            rx.text("Filtrar por etiqueta:"),
            rx.select(
                # El componente select debe ser compatible con la versión de Reflex
                items=AppState.all_tags, 
                value=AppState.tag_filter, 
                on_change=AppState.set_tag_filter, 
                placeholder="Selecciona una etiqueta...",
                width="260px",
            ),
            spacing="2",
            align_items="center",
        ),
        spacing="3",
        align_items="stretch", width="100%",
    )

def page() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.heading("El Archivo del Capitolio", size="6"),
            rx.text("Sistema de Gestión Documental Inteligente", color="#666"),
            upload_zone(),
            search_bar(),
            rx.separator(margin="6px 0"),
            rx.cond(
                AppState.filtered_docs,
                rx.vstack(
                    rx.foreach(AppState.filtered_docs, lambda d: doc_row(d)),
                    spacing="3",
                    align_items="stretch",
                ),
                rx.text("Sin documentos aún. Sube algunos PDFs para empezar.", color="#666"),
            ),
            spacing="4",
            align_items="stretch", padding_y="20px",
        ),
        max_width="1100px", padding_y="20px",
    )

# --------- App ---------
app = rx.App()
app.add_page(page, route="/", title="Archivo del Capitolio")