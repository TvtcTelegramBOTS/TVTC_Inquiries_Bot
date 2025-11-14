import pdfplumber
import pytesseract
from PIL import Image

# تعديل المسار حسب نظامك
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

PDF_PATH = "Certificates.pdf"   # عدّله لمسار شهادة فيها رقم الهوية العربي

print("🔍 قراءة الصفحة المطلوبة...")

with pdfplumber.open(PDF_PATH) as pdf:
    page_number = int(input("📄 أدخل رقم الصفحة التي فيها الهوية العربية: "))
    page = pdf.pages[page_number - 1]

    # تحويل الصفحة لصورة
    img = page.to_image(resolution=300).original

    # استخراج النص الخام *بدون أي تطبيع*
    raw_text = pytesseract.image_to_string(img, lang="ara+eng")

    print("\n================ RAW OCR TEXT ================\n")
    print(raw_text)
    print("\n===============================================\n")
