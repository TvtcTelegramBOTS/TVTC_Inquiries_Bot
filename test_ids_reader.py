import pdfplumber
import pytesseract
from PIL import Image
import re

# ✳️ حدّد مسار Tesseract حسب تثبيتك
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

pdf_path = "نموذج هويات.pdf"

def extract_name_by_ocr(page, sid_bbox):
    """قصّ المنطقة اليسرى من رقم المتدرب (الاسم عادة هناك)"""
    x0, top, x1, bottom = sid_bbox

    # نحدد مساحة أصغر على يسار رقم المتدرب
    crop_box = (x0 - 370, top - 10, x0 - 50, bottom + 10)

    # تأكد أن الإحداثيات لا تخرج عن حدود الصفحة
    crop_box = tuple(max(0, v) for v in crop_box)

    region = page.within_bbox(crop_box)
    img = region.to_image(resolution=350).original

    # نستخدم OCR مع اللغة العربية
    text = pytesseract.image_to_string(img, lang="ara+eng")
    text = re.sub(r"\s+", " ", text).strip()

    # نحذف أي أرقام محتملة (مثل الجوال أو الهوية)
    text = re.sub(r"\d{5,}", "", text).strip()

    return text

def find_sid_and_nid(page):
    """يجد رقم المتدرب والهوية في نفس السطر"""
    words = page.extract_words()
    data = []
    for w in words:
        if re.fullmatch(r"44\d{7}", w["text"]):
            sid_bbox = (w["x0"], w["top"], w["x1"], w["bottom"])
            nid = None
            for n in words:
                if abs(n["top"] - w["top"]) < 12 and re.fullmatch(r"1\d{9}", n["text"]):
                    nid = n["text"]
                    break
            data.append((w["text"], nid, sid_bbox))
    return data


with pdfplumber.open(pdf_path) as pdf:
    for page_num, page in enumerate(pdf.pages, start=1):
        results = find_sid_and_nid(page)
        if not results:
            continue
        print(f"\n📄 صفحة {page_num}")
        for sid, nid, bbox in results:
            name = extract_name_by_ocr(page, bbox)
            print(f"📘 المتدرب: {sid}\n🪪 الهوية: {nid or '❌ غير موجود'}\n👤 الاسم (OCR): {name or '❌ غير مقروء'}\n{'-'*40}")
