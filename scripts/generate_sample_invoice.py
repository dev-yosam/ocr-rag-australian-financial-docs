"""Generate only synthetic data; expected.json is an independent test oracle."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
from app.core.config import ROOT


def main() -> None:
    destination = ROOT / "samples/tax_invoices/sample_invoice.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1654, 2339), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=37)
    title = ImageFont.load_default(size=65)
    draw.text((110, 110), "TAX INVOICE", fill="#16324f", font=title)
    draw.text((110, 230), "SYNTHETIC - NOT VALID FOR PAYMENT", fill="#b42318", font=font)
    lines = [
        "Supplier: Example Synthetic Services Pty Ltd",
        "Supplier ABN: 00 000 000 000",
        "Customer: Example Synthetic Customer",
        "Invoice Number: SYN-2026-0001",
        "Invoice Date: 11 September 2026",
        "Currency: AUD",
    ]
    for index, line in enumerate(lines):
        draw.text((110, 380 + index * 90), line, fill="black", font=font)
    draw.line((110, 1000, 1540, 1000), fill="#16324f", width=4)
    draw.text((110, 1050), "Description", fill="black", font=font)
    draw.text((1150, 1050), "Amount (AUD)", fill="black", font=font)
    draw.text((110, 1150), "Synthetic document processing service", fill="black", font=font)
    draw.text((1240, 1150), "1,000.00", fill="black", font=font)
    for index, line in enumerate(["Subtotal: AUD 1,000.00", "GST: AUD 100.00", "Total: AUD 1,100.00"]):
        draw.text((850, 1400 + index * 100), line, fill="black", font=font)
    draw.text((110, 2000), "All details are fictional. ABN is a deliberate dummy.", fill="#555555", font=font)
    image.save(destination)
    print("Synthetic invoice PNG generated")


if __name__ == "__main__":
    main()
