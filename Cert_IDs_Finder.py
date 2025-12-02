import fitz        # PyMuPDF
import re

# رقم هوية سعودي بالأرقام الإنجليزية:
# يبدأ بـ 1 وطوله 10 أرقام
EN_ID = re.compile(r"\b1[0-9]{9}\b")

def detect_english_id(pdf_path):
    doc = fitz.open(pdf_path)
    found_ids = []

    for page_number, page in enumerate(doc, start=1):
        text = page.get_text("text")

        # ابحث عن أي رقم هوية إنجليزي
        matches = EN_ID.findall(text)

        if matches:
            found_ids.append((page_number, matches))

    doc.close()
    return found_ids


if __name__ == "__main__":
    pdf_file = "Certificates.pdf"   # ← ضع اسم الشهادة هنا
    result = detect_english_id(pdf_file)

    if result:
        print("✔ تم العثور على أرقام هوية إنجليزية:")
        for page_no, ids in result:
            print(f"  - صفحة {page_no}: {ids}")
    else:
        print("❌ لا يوجد أي رقم هوية إنجليزي في هذا الملف.")
