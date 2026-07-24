from io import BytesIO
from pathlib import Path
from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from apps.catalog.models import SiteConfiguration
from apps.quotes.formatting import format_decimal_it, format_money


def build_customer_pdf(quote) -> bytes:
    buffer = BytesIO()
    configured = SiteConfiguration.load()
    default_logo = settings.BASE_DIR / "static" / "images" / "officine-pollastri-logo.png"
    company = {
        "name": configured.company_name or settings.COMPANY["name"],
        "address": configured.address or settings.COMPANY["address"],
        "vat": configured.vat or settings.COMPANY["vat"],
        "email": configured.email or settings.COMPANY["email"],
        "phone": configured.phone or settings.COMPANY["phone"],
        "terms": configured.terms or settings.COMPANY["terms"],
        "logo_path": configured.logo.path if configured.logo else (settings.COMPANY["logo_path"] or default_logo),
        "primary_color": configured.primary_color,
    }
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8.5, leading=11))
    styles.add(ParagraphStyle(name="SmallHeader", parent=styles["Small"], textColor=colors.white, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Right", parent=styles["BodyText"], alignment=TA_RIGHT))
    styles.add(ParagraphStyle(name="CenteredTitle", parent=styles["Title"], alignment=TA_CENTER, textColor=colors.HexColor(company["primary_color"])))

    def safe(value) -> str:
        return escape(str(value or ""))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#b8c4cd"))
        canvas.line(18 * mm, 16 * mm, 192 * mm, 16 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(18 * mm, 10 * mm, company["name"])
        canvas.drawRightString(192 * mm, 10 * mm, f"Pagina {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title=f"Preventivo {quote.number}", author=company["name"], pageCompression=0,
    )
    story = []
    logo_path = company.get("logo_path")
    if logo_path and Path(logo_path).is_file():
        source_width, source_height = ImageReader(logo_path).getSize()
        scale = min((48 * mm) / source_width, (20 * mm) / source_height)
        story.append(Image(logo_path, width=source_width * scale, height=source_height * scale))
    company_lines = [company.get("name", ""), company.get("address", "")]
    if company.get("vat"):
        company_lines.append(f"P. IVA: {company['vat']}")
    contacts = " - ".join(value for value in (company.get("phone"), company.get("email")) if value)
    if contacts:
        company_lines.append(contacts)
    story.extend([Paragraph("<br/>".join(safe(line) for line in company_lines), styles["BodyText"]), Spacer(1, 8 * mm)])
    story.append(Paragraph("Preventivo", styles["CenteredTitle"]))
    story.append(Spacer(1, 4 * mm))
    customer = quote.client.name if quote.client else "Cliente non indicato"
    info = [
        [Paragraph("Numero preventivo", styles["Small"]), Paragraph(quote.number, styles["BodyText"]), Paragraph("Data", styles["Small"]), quote.date.strftime("%d/%m/%Y")],
        [Paragraph("Cliente", styles["Small"]), Paragraph(safe(customer), styles["BodyText"]), Paragraph("Referente", styles["Small"]), Paragraph(safe(quote.client_contact or "—"), styles["BodyText"])],
        [Paragraph("Email referente", styles["Small"]), Paragraph(safe(quote.client_email or "—"), styles["BodyText"]), "", ""],
    ]
    info_table = Table(info, colWidths=[32 * mm, 60 * mm, 25 * mm, 57 * mm])
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf2f6")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#edf2f6")),
        ("SPAN", (1, 2), (3, 2)),
        ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#9eacb7")),
        ("INNERGRID", (0, 0), (-1, -1), .25, colors.HexColor("#c7d0d7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([info_table, Spacer(1, 7 * mm)])

    headers = ["Codice", "Rev.", "Descrizione", "Dimensioni", "Q.tà", "Materiali e peso", "Lavorazioni comprese"]
    data = [[Paragraph(safe(h), styles["SmallHeader"]) for h in headers]]
    for item in quote.items.all():
        materials = "<br/>".join(
            f"{safe(row.material.name)}: {format_decimal_it(row.weight_kg, 3)} kg/pezzo"
            for row in item.materials.all()
        ) or "—"
        included_work = []
        for phase in item.phases.filter(active=True):
            label = safe(phase.definition.name)
            if phase.definition.code == "trattamento-esterno" and phase.treatments.exists():
                treatments = ", ".join(
                    f"{safe(row.get_treatment_type_display())}{': ' + safe(row.description) if row.description else ''}"
                    for row in phase.treatments.all()
                )
                label = f"{label}: {treatments}"
            included_work.append(label)
        data.append([
            Paragraph(safe(item.code), styles["Small"]), Paragraph(safe(item.revision or "—"), styles["Small"]),
            Paragraph(safe(item.description or "—"), styles["Small"]), Paragraph(safe(item.dimensions_display or "—"), styles["Small"]),
            str(item.quantity), Paragraph(materials, styles["Small"]), Paragraph("<br/>".join(included_work) or "—", styles["Small"]),
        ])
    items_table = Table(data, repeatRows=1, colWidths=[21 * mm, 11 * mm, 36 * mm, 23 * mm, 11 * mm, 42 * mm, 30 * mm])
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(company["primary_color"])), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#a8b5bf")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f9")]), ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([Paragraph("Articoli", styles["Heading2"]), items_table, Spacer(1, 6 * mm)])
    story.append(Paragraph(f"<b>Fattibilità:</b> {safe(quote.get_feasibility_display())}", styles["BodyText"]))
    if quote.customer_notes:
        story.extend([Spacer(1, 3 * mm), Paragraph("Note per il cliente", styles["Heading3"]), Paragraph(safe(quote.customer_notes), styles["BodyText"])])
    amount = format_money(quote.offered_price) if quote.offered_price is not None else "Importo da definire"
    amount_table = Table([[Paragraph("<b>Totale preventivo</b>", styles["Heading3"]), Paragraph(f"<b>{amount}</b>", styles["Right"])]], colWidths=[100 * mm, 74 * mm])
    amount_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e8f1f7")), ("BOX", (0, 0), (-1, -1), 1, colors.HexColor(company["primary_color"])), ("PADDING", (0, 0), (-1, -1), 12)]))
    story.extend([Spacer(1, 8 * mm), amount_table, Spacer(1, 8 * mm)])
    story.append(KeepTogether([
        Paragraph("Condizioni e accettazione", styles["Heading3"]),
        Paragraph(safe(company.get("terms") or "Condizioni da definire."), styles["BodyText"]),
        Spacer(1, 15 * mm),
        Table([["Data ____________________", "Firma ______________________________"]], colWidths=[75 * mm, 99 * mm]),
    ]))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
