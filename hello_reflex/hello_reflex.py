# hello_reflex.py
# (Código completo y corregido, listo para usar)

from _future_ import annotations

import os
import re
import io
from pathlib import Path
from datetime import datetime
from typing import List, Any 

import reflex as rx
from sqlmodel import Field, select

# ---------------- Rutas de trabajo ----------------
ASSETS_DIR = Path("assets")
DOCS_DIR = ASSETS_DIR / "docs"
DOCS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------- Modelo persistente ----------------
class Document(rx.Model, table=True):
    id: int | None = Field(default=None, primary_key=True)
    filename: str
    relpath: str                         
    text_snippet: str = ""               
    tags_str: str = ""                   
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

    @staticmethod
    def tags_to_str(tags: list[str]) -> str:
        clean = sorted({t.strip().lower() for t in tags if t and t.strip()})
        return ",".join(clean)

    @staticmethod
    def str_to_tags(tags_str: str) -> list[str]:
        if not tags_str:
            return []
        return [t for t in (x.strip() for x in tags_str.split(",")) if t]


# ---------------- Utilidades ----------------
def _safe_filename(name: str) -> str:
    base = os.path.basename(name)
    base = re.sub(r"[^\w\-. ]+", "_", base, flags=re.I)
    return base or f"file_{int(datetime.utcnow().timestamp())}.pdf"


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Intenta extraer texto con PyPDF2; si queda vacío, usa OCR si está disponible."""
    text = ""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                parts.append("")
        text = "\n".join(parts).strip()
    except Exception:
        text = ""

    if not text:
        try:
            from pdf2image import convert_from_bytes
            import pytesseract
            images = convert_from_bytes(pdf_bytes, dpi=200)
            ocr_parts = []
            for img in images:
                try:
                    ocr_parts.append(pytesseract.image_to_string(img) or "")
                except Exception:
                    ocr_parts.append("")
            text = "\n".join(ocr_parts).strip()
        except Exception:
            pass

    return text


# ---------------- Sugerencia de etiquetas ----------------
PRESET_TAGS = {
    "factura": ["subtotal", "iva", "rfc", "factura", "total", "folio", "cfdi", "emisor", "receptor"],
    "contrato": ["contrato", "cláusula", "acuerdo", "firmante", "vigencia", "obligaciones", "rescindir"],
    "impuestos": ["impuesto", "sat", "declaración", "retenciones", "isr", "iva", "anual"],
    "personal": ["currículum", "cv", "empleo", "reclutamiento", "postulante", "nombramiento"],
    "legal": ["demanda", "notificación", "juzgado", "representante legal", "poder", "amparo"],
    "proveedores": ["proveedor", "cotización", "orden de compra", "oc", "suministro"],
    "finanzas": ["balance", "ingresos", "egresos", "presupuesto", "flujo de efectivo"],
    "educación": ["constancia", "certificado", "calificaciones", "kárdex", "boleta"],
    "salud": ["receta", "diagnóstico", "consulta", "medicamento"],
}

def suggest_tags(text: str, top_k: int = 5) -> list[str]:
    text_low = text.lower()
    scores: dict[str, int] = {}
    for tag, kws in PRESET_TAGS.items():
        s = sum(text_low.count(k.lower()) for k in kws)
        if s > 0:
            scores[tag] = s
    for kw in ["2023", "2024", "2025", "confidencial", "urgente"]:
        c = text_low.count(kw)
        if c > 0:
            scores[kw] = scores.get(kw, 0) + c
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [t for t, _ in ranked[:top_k]]


# ---------------- Estado ----------------
class State(rx.State):
    # Campos y valores
    manual_tags: str = ""
    search_text: str = ""
    search_tag: str = ""
    info: str = ""
    loading: bool = False

    last_suggested: list[str] = []

    # Lista serializable (tipado explícito)
    visible_docs: list[dict[str, Any]] = [] 

    # ---- setters explícitos (evitan deprecation) ----
    def set_manual_tags(self, v: str):
        self.manual_tags = v

    def set_search_text(self, v: str):
        self.search_text = v

    def set_search_tag(self, v: str):
        self.search_tag = v

    # ---- ciclo de vida ----
    def on_load(self):
        return self.refresh_list()

    def set_info(self, msg: str):
        self.info = msg

    # ---- consultas DB -> visible_docs ----
    def refresh_list(self):
        """Carga y filtra documentos; convierte a dicts serializables para foreach."""
        with rx.session() as sess:
            docs = list(sess.exec(select(Document).order_by(Document.uploaded_at.desc())).all())

        st = self.search_text.strip().lower()
        tg = self.search_tag.strip().lower()

        result: list[dict[str, Any]] = []
        for d in docs:
            ok = True
            if st:
                ok = (st in d.filename.lower()) or (st in (d.text_snippet or "").lower())
            if ok and tg:
                ok = tg in set(Document.str_to_tags(d.tags_str))
            if ok:
                result.append(
                    {
                        "id": d.id,
                        "filename": d.filename,
                        "url": f"/assets/{d.relpath}",
                        "date": d.uploaded_at.strftime("%Y-%m-%d %H:%M"),
                        "snippet": d.text_snippet or "",
                        "tags": Document.str_to_tags(d.tags_str),
                    }
                )

        self.visible_docs = result

    # ---- subida ----
    async def handle_upload(self, files: list[rx.UploadFile]):
        if not files:
            self.info = "No se adjuntó ningún archivo."
            return

        self.loading = True
        self.info = "Procesando documentos…"
        created = 0

        for uf in files:
            if not uf.filename.lower().endswith(".pdf"):
                continue
            data = await uf.read()
            filename = _safe_filename(uf.filename)
            dest = DOCS_DIR / filename
            try:
                with open(dest, "wb") as f:
                    f.write(data)
            except Exception as e:
                self.info = f"Error guardando {filename}: {e}"
                continue

            text = extract_text_from_pdf(data) or ""
            snippet = (text[:300] + "…") if len(text) > 300 else text

            auto = suggest_tags(text)
            self.last_suggested = auto

            manual = [t.strip() for t in self.manual_tags.split(",")] if self.manual_tags else []
            all_tags = Document.tags_to_str(manual + auto)

            with rx.session() as sess:
                doc = Document(
                    filename=filename,
                    relpath=str(Path("docs") / filename).replace("\\", "/"),
                    text_snippet=snippet or "",
                    tags_str=all_tags,
                )
                sess.add(doc)
                sess.commit()
                created += 1

        self.loading = False
        self.info = f"Se indexaron {created} documento(s)."
        self.manual_tags = ""
        return self.refresh_list()

    # ---- acciones ----
    def delete_doc(self, doc_id: int):
        with rx.session() as sess:
            d = sess.get(Document, doc_id)
            if d is None:
                self.info = "Documento no encontrado."
                return
            try:
                p = ASSETS_DIR / Path(d.relpath)
                if p.exists():
                    p.unlink()
            except Exception:
                pass
            sess.delete(d)
            sess.commit()
        self.info = "Documento eliminado."
        return self.refresh_list()

    def clear_filters(self):
        self.search_text = ""
        self.search_tag = ""
        return self.refresh_list()


# ---------------- Componentes UI ----------------
def tag_badge(tag: str) -> rx.Component:
    return rx.badge(tag, color_scheme="gray", variant="soft", class_name="rounded-full")


def doc_card_from_dict(d: rx.Var[dict[str, Any]]) -> rx.Component:
    
    # CORRECCIÓN: Forzar el tipo de la lista anidada "tags"
    tags_list: rx.Var[List[str]] = d["tags"].to(List[str]) 
    
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text(d["filename"], weight="bold"),
                rx.spacer(),
                rx.text(d["date"], size="2", color_scheme="gray"),
                align="center",
                width="100%",
            ),
            rx.text(d["snippet"], size="2", color_scheme="gray"),
            rx.hstack(rx.foreach(tags_list, lambda t: tag_badge(t)), wrap="wrap", gap="2"),
            rx.hstack(
                rx.link(rx.button("Abrir"), href=d["url"], is_external=True),
                rx.button("Eliminar", color_scheme="red", variant="soft", on_click=State.delete_doc(d["id"])),
                align="start",
                gap="3",
            ),
            align="start",
            gap="3",
            width="100%",
        ),
        class_name="w-full",
        size="3",
        variant="surface",
    )


def sidebar_upload() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Cargar PDF", size="5"),
            rx.text("Arrastra o selecciona archivos (.pdf).", size="2", color_scheme="gray"),
            
            rx.upload(
                rx.vstack(rx.icon("upload"), rx.text("Suelta PDFs aquí o haz clic", size="2")),
                accept={"application/pdf": [".pdf"]},
                max_files=10,
                disabled=State.loading,
                on_drop=State.handle_upload,
                width="100%",
                class_name="border-2 border-dashed rounded-2xl p-6",
            ),
            
            rx.cond(
                State.loading,
                rx.hstack(
                    rx.spinner(size="2"), # CORREGIDO: Usamos '2' para el tamaño.
                    rx.text("Procesando documentos...", color_scheme="blue", size="3"),
                    gap="3",
                    align="center",
                ),
                rx.text(State.info, color_scheme="gray"),
            ),
            
            rx.divider(),
            rx.text("Etiquetas manuales (separadas por comas)", size="2"),
            rx.input(
                placeholder="ej. contrato, 2025, confidencial",
                value=State.manual_tags,
                on_change=State.set_manual_tags,
                width="100%",
            ),
            rx.divider(),
            rx.heading("Sugerencias (último PDF)", size="4"),
            rx.hstack(rx.foreach(State.last_suggested, lambda t: tag_badge(t)), wrap="wrap", gap="2", width="100%"),
            
            align="start",
            gap="3",
            width="100%",
        ),
        size="3",
        variant="surface",
        class_name="w-full",
    )


def search_bar() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Buscar y filtrar", size="5"),
            rx.hstack(
                rx.input(
                    placeholder="Buscar por nombre o contenido…",
                    value=State.search_text,
                    on_change=State.set_search_text,
                    width="100%",
                ),
                rx.input(
                    placeholder="Filtrar por etiqueta (ej. factura)…",
                    value=State.search_tag,
                    on_change=State.set_search_tag,
                    width="50%",
                ),
                rx.button("Aplicar", on_click=State.refresh_list),
                rx.button("Limpiar", variant="soft", on_click=State.clear_filters),
                width="100%",
                align="center",
                spacing="3",
            ),
            align="start",
            gap="3",
            width="100%",
        ),
        size="3",
        variant="surface",
        class_name="w-full",
    )


def docs_grid() -> rx.Component:
    # CORRECCIÓN: 'columns' en rx.grid debe ser un string.
    return rx.grid(
        rx.foreach(State.visible_docs, lambda d: doc_card_from_dict(d)),
        columns="1 2 3",
        gap="4",
        width="100%",
    )


def header_bar() -> rx.Component:
    return rx.hstack(
        rx.heading("Archivo del Capitolio", size="8"),
        rx.spacer(),
        rx.color_mode.button(position="top-right"),
        align="center",
        width="100%",
        padding_y="3",
    )


def index() -> rx.Component:
    return rx.container(
        header_bar(),
        rx.grid(
            rx.vstack(sidebar_upload(), align="start", gap="4", width="100%"),
            rx.vstack(search_bar(), docs_grid(), align="start", gap="4", width="100%"),
            # CORRECCIÓN: 'columns' del layout principal debe ser un string.
            columns="1 2", 
            gap="5",
            width="100%",
        ),
        padding_y="4",
        min_height="90vh",
    )


# ---------------- App ----------------
app = rx.App()
app.add_page(index, route="/", title="Sistema de Gestión Documental")