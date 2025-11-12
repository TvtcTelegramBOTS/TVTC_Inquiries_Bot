# bot.py
import os
import re
import sys
import io
import json
import time
import asyncio
import threading
import subprocess
import pandas as pd
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)
from PyPDF2 import PdfReader, PdfWriter

# ضمان طباعة عربية مباشرة
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# =========================
# إعدادات أساسية
# =========================
FILES = {
    "schedule": "Scheduals.pdf",
    "advisor": "Advisors.csv",
    "remaining": "Remaining.pdf",
    "gpa": "GPA.pdf",
    "majors": "TNumbers with majors.pdf",
    "ids": "IDs.csv",
    "certificates": "Certificates.pdf",
}

# ✅ استخدم متغير البيئة TELEGRAM_TOKEN
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not BOT_TOKEN:
    print("❌ لم يتم العثور على متغير TELEGRAM_TOKEN. ضعه في إعدادات الخادم أو عرّفه محليًا للتجربة.", flush=True)
    sys.exit(1)

# =========================
# حالة البوت (تُعرض للداثبورد)
# =========================
STATUS = {
    "running": False,
    "telegram_connected": False,
    "indexing": False,
    "current_file": "",
    "index_progress": 0.0,   # 0..100
    "last_user": ""
}
_status_lock = threading.Lock()

def _set_status(**kwargs):
    with _status_lock:
        STATUS.update(kwargs)

def _get_status():
    with _status_lock:
        return dict(STATUS)

# =========================
# أدوات مساعدة
# =========================
def convert_arabic_to_english(arabic_number: str) -> str:
    arabic_digits = {
        '٠': '0','١': '1','٢': '2','٣': '3','٤': '4',
        '٥': '5','٦': '6','٧': '7','٨': '8','٩': '9'
    }
    return ''.join(arabic_digits.get(ch, ch) for ch in arabic_number)

# =============== أدوات مساعدة للهوية والاسم ===============
AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

def normalize_digits(s: str) -> str:
    """تحويل الأرقام العربية-الهندية إلى إنجليزية + إزالة محارف خفية."""
    return (s or "").translate(AR_DIGITS).replace('\u200f', '').replace('\u200e', '').strip()

def is_valid_nid(nid: str) -> bool:
    """هوية وطنية سعودية: تبدأ بـ 1 وطولها 10 أرقام."""
    nid = normalize_digits(nid)
    return bool(re.fullmatch(r'1\d{9}', nid))

def looks_like_ar_name(line: str) -> bool:
    if not re.search(r'[اأإآء-ي]', line):
        return False
    s = re.sub(r'[^اأإآء-ي\s]', '', line).strip()
    if not s:
        return False
    words = [w for w in s.split() if len(w) >= 2]
    return 2 <= len(words) <= 5

def clean_ar_name(line: str) -> str:
    s = re.sub(r'[^\w\s\u0600-\u06FF]', ' ', line)  # إبقاء العربية والمسافات
    s = re.sub(r'\s+', ' ', s).strip()
    # إزالة ألفاظ وصفية شائعة لو ظهرت ملتصقة بالاسم
    s = re.sub(r'\b(الطالب|المتدرب|اسم|Name)\b', '', s).strip()
    return s

def extract_first_name(full_name: str) -> str:
    """
    أول اسم منطقي مع مراعاة المركّب (عبد الرحمن، عبد الله).
    لو ما قدر، يرجع أول كلمة سليمة.
    """
    full_name = clean_ar_name(full_name)
    parts = full_name.split()
    if not parts:
        return "عزيزنا"
    if len(parts) >= 2 and parts[0] in ("عبد", "أبو", "أم", "ابن", "بن"):
        return f"{parts[0]} {parts[1]}"
    return parts[0]

# =========================
# تهيئة الفهارس (تشغل بالخلفية)
# =========================
INDEXES = {
    "schedule": {},
    "advisor": None,
    "remaining": {},
    "gpa": {},
    "majors": {},
    "ids": {},
}

# =========================
# فهرسة PDF (مع تقدم لحظي)
# =========================
def build_index(pdf_path, index_path="schedule_index.json"):
    """فهرسة ملف الجدول (Schedule) لاستخراج مواقع المتدربين حسب أرقامهم."""
    _set_status(indexing=True, current_file=os.path.basename(pdf_path), index_progress=0.0)
    try:
        if not os.path.exists(pdf_path):
            print(f"⚠️ الملف {pdf_path} غير موجود.", flush=True)
            return {}

        print(f"⏳ فهرسة الملف: {pdf_path}", flush=True)
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        index = {}
        start_time = time.time()

        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for m in re.findall(r"\b44\d{7}\b", text):
                if m not in index:
                    index[m] = i - 1
            percent = (i / total_pages) * 100
            _set_status(index_progress=percent)
            print(f"📄 فهرسة الصفحة {i}/{total_pages} ({percent:.1f}%)", flush=True)
            time.sleep(0.01)

        elapsed = time.time() - start_time
        print(f"✅ تم فهرسة {len(index)} متدرب من {pdf_path} خلال {elapsed:.1f} ثانية.", flush=True)
        return index
    except Exception as e:
        print("❌ خطأ أثناء فهرسة الجدول:", e, flush=True)
        import traceback; traceback.print_exc()
        return {}
    finally:
        _set_status(indexing=False, current_file="", index_progress=0.0)

def build_remaining_index(pdf_path, index_path="remaining_index.json"):
    _set_status(indexing=True, current_file=os.path.basename(pdf_path), index_progress=0.0)
    try:
        meta_path = index_path + ".meta"
        if os.path.exists(index_path) and os.path.exists(meta_path):
            pdf_mtime = os.path.getmtime(pdf_path)
            meta_mtime = float(open(meta_path, "r").read())
            if pdf_mtime <= meta_mtime:
                print(f"✅ فهرس {pdf_path} جاهز مسبقًا.", flush=True)
                with open(index_path, "r", encoding="utf-8") as f:
                    return json.load(f)

        print(f"⏳ فهرسة (remaining) الملف: {pdf_path}", flush=True)
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        index = {}
        start_time = time.time()

        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for match in re.findall(r"\b44\d{7}\b", text):
                index.setdefault(match, []).append(i - 1)
            percent = (i / total_pages) * 100
            _set_status(index_progress=percent)
            print(f"فهرسة remaining: الصفحة {i}/{total_pages} ({percent:.1f}%)", flush=True)
            time.sleep(0.01)

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
        with open(meta_path, "w") as m:
            m.write(str(os.path.getmtime(pdf_path)))

        elapsed = time.time() - start_time
        print(f"✅ تم بناء فهرس remaining ({len(index)} متدرب) خلال {elapsed:.1f} ثانية.", flush=True)
        return index
    except Exception as e:
        print("❌ خطأ أثناء فهرسة remaining:", e, flush=True)
        import traceback; traceback.print_exc()
        return {}
    finally:
        _set_status(indexing=False, current_file="", index_progress=0.0)

def build_certificates_index(pdf_path, index_path="certificates_index.json"):
    """📜 فهرسة ملف الشهادات بالاعتماد على رقم الهوية الوطنية (قد تتكرر في عدة صفحات)."""
    _set_status(indexing=True, current_file=os.path.basename(pdf_path), index_progress=0.0)
    try:
        if not os.path.exists(pdf_path):
            print(f"⚠️ ملف الشهادات غير موجود: {pdf_path}", flush=True)
            return {}

        meta_path = index_path + ".meta"
        if os.path.exists(index_path) and os.path.exists(meta_path):
            pdf_mtime = os.path.getmtime(pdf_path)
            meta_mtime = float(open(meta_path, "r").read())
            if pdf_mtime <= meta_mtime:
                print("✅ فهرس الشهادات جاهز مسبقًا.", flush=True)
                with open(index_path, "r", encoding="utf-8") as f:
                    return json.load(f)

        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        index = {}

        print(f"🔍 فهرسة الشهادات ({pdf_path}) ...", flush=True)
        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""

            # 🟢 دعم الهوية بالأرقام العربية أو الإنجليزية
            matches = re.findall(r"[1١][0-9٠-٩]{9}", text)
            for match in matches:
                nid = normalize_digits(match)  # تحويل الأرقام العربية إلى إنجليزية
                if is_valid_nid(nid):         # تأكد من صلاحية الهوية
                    index.setdefault(nid, []).append(i - 1)

            percent = (i / total_pages) * 100
            _set_status(index_progress=percent)
            if i % 10 == 0 or i == total_pages:
                print(f"📜 صفحة {i}/{total_pages} - تقدم {percent:.1f}%", flush=True)

        # حفظ الفهرس النهائي
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
        with open(meta_path, "w") as m:
            m.write(str(os.path.getmtime(pdf_path)))

        print(f"✅ تم بناء فهرس الشهادات ({len(index)} هوية لديها شهادة واحدة أو أكثر).", flush=True)
        return index
    except Exception as e:
        print("❌ خطأ أثناء فهرسة الشهادات:", e, flush=True)
        import traceback; traceback.print_exc()
        return {}
    finally:
        _set_status(indexing=False, current_file="", index_progress=0.0)

def load_ids_from_csv(csv_path: str):
    """
    🔹 تحميل بيانات المتدربين من ملف CSV يحتوي على الأعمدة:
    الفصل التدريبي,"الوحدة التدريبية","المرحلة","القسم","البرنامج",
    "رقم المتدرب","اسم المتدرب","المعدل التراكمي","السجل المدني","الجنس","الجنسية","رقم الجوال"
    🔸 النتيجة: {"رقم المتدرب": {"nid": "السجل المدني", "name": "اسم المتدرب"}}
    """
    index = {}
    if not os.path.exists(csv_path):
        print(f"⚠️ ملف CSV غير موجود: {csv_path}", flush=True)
        return index

    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str, quotechar='"')
        for _, row in df.iterrows():
            sid = str(row.get("رقم المتدرب", "")).strip()
            nid = str(row.get("السجل المدني", "")).strip()
            name = str(row.get("اسم المتدرب", "")).strip()
            if re.fullmatch(r"44\d{7}", sid) and re.fullmatch(r"1\d{9}", nid):
                index[sid] = {"nid": nid, "name": name}
        print(f"✅ تم تحميل بيانات {len(index)} متدرب من CSV بنجاح.", flush=True)
    except Exception as e:
        print(f"❌ خطأ أثناء قراءة CSV: {e}", flush=True)
        import traceback; traceback.print_exc()

    return index


def build_majors_index(pdf_path, index_path="majors_index.json"):
    try:
        meta_path = index_path + ".meta"
        if os.path.exists(index_path) and os.path.exists(meta_path):
            pdf_mtime = os.path.getmtime(pdf_path)
            meta_mtime = float(open(meta_path, "r").read())
            if pdf_mtime <= meta_mtime:
                print("✅ فهرس التخصصات جاهز مسبقًا.", flush=True)
                with open(index_path, "r", encoding="utf-8") as f:
                    return json.load(f)

        print(f"🔍 بناء فهرس التخصصات {pdf_path} ...", flush=True)
        reader = PdfReader(pdf_path)
        index = {}
        total_pages = len(reader.pages)

        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            student_ids = re.findall(r"\b44\d{7}\b", text)
            if student_ids:
                for sid in student_ids:
                    index[sid] = text
            if i % 10 == 0 or i == total_pages:
                percent = (i / total_pages) * 100
                print(f"📄 فهرسة الصفحة {i}/{total_pages} ({percent:.1f}%)", flush=True)
                time.sleep(0.01)

        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False)
        with open(meta_path, "w") as m:
            m.write(str(os.path.getmtime(pdf_path)))

        print(f"✅ تم بناء فهرس التخصصات ({len(index)} متدرب).", flush=True)
        return index
    except Exception as e:
        print("❌ خطأ أثناء فهرسة التخصصات:", e, flush=True)
        import traceback; traceback.print_exc()
        return {}


def initialize_indexes():
    print("🚀 بدء تشغيل النظام وفهرسة الملفات بالخلفية...", flush=True)
    try:
        print("\n📂 فهرسة SCHEDULE ...", flush=True)
        INDEXES["schedule"] = build_index(FILES["schedule"])
        time.sleep(0.3)

        print("\n📂 فهرسة REMAINING ...", flush=True)
        INDEXES["remaining"] = build_remaining_index(FILES["remaining"])
        time.sleep(0.3)

        INDEXES["gpa"] = {}

        print("\n📂 فهرسة IDs ...", flush=True)
        INDEXES["ids"] = load_ids_from_csv("IDs.csv")
        time.sleep(0.3)

        print("\n📂 فهرسة MAJORS ...", flush=True)
        INDEXES["majors"] = build_majors_index(FILES["majors"])
        time.sleep(0.3)

        print("\n📂 فهرسة CERTIFICATES ...", flush=True)
        INDEXES["certificates"] = build_certificates_index(FILES["certificates"])
        time.sleep(0.3)

        INDEXES["advisor"] = None
        print("\n----------------------------", flush=True)
        print("✅ جميع الفهارس جاهزة بنجاح.", flush=True)
    except Exception as e:
        print("❌ خطأ أثناء التهيئة:", e, flush=True)
        import traceback; traceback.print_exc()

# =========================
# ضغط PDF
# =========================
def _gs_binary():
    # استخدم gswin64c على ويندوز، و gs على أنظمة أخرى
    return "gswin64c" if os.name == "nt" else "gs"

def compress_pdf_with_ghostscript(input_file: str, output_file: str, max_size_mb: float = 3.0):
    """ضغط PDF بواسطة Ghostscript مع خطة بديلة."""
    print(f"⏳ ضغط الملف {input_file} ...", flush=True)
    try:
        command = [
            _gs_binary(), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dQUIET", "-dBATCH",
            f"-sOutputFile={output_file}", input_file
        ]
        subprocess.run(command, check=True)
        size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"✅ تم ضغط الملف ({size_mb:.2f} MB) باستخدام إعداد /ebook", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ فشل الضغط الأول ({e})، تجربة إعداد /screen...", flush=True)
        try:
            command = [
                _gs_binary(), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
                "-dPDFSETTINGS=/screen", "-dNOPAUSE", "-dQUIET", "-dBATCH",
                f"-sOutputFile={output_file}", input_file
            ]
            subprocess.run(command, check=True)
            size_mb = os.path.getsize(output_file) / (1024 * 1024)
            print(f"✅ تم ضغط الملف ({size_mb:.2f} MB) باستخدام إعداد /screen", flush=True)
            return True
        except Exception as e2:
            print(f"❌ فشل الضغط تمامًا ({e2})، سيتم استخدام النسخة الأصلية.", flush=True)
            return False

# =========================
# الخدمات
# =========================
async def send_advisor(update, context, student_id):
    csv_path = FILES.get("advisor")
    if not os.path.exists(csv_path):
        await update.message.reply_text("❌ ملف المرشد غير متاح حالياً.")
        return
    sent_msg = await update.message.reply_text("👨‍🏫 جاري البحث عن مرشدك التدريبي...")
    try:
        df = pd.read_csv(csv_path, encoding='utf-8', dtype=str)
    except Exception as e:
        await sent_msg.delete()
        await update.message.reply_text(f"❌ خطأ في قراءة ملف المرشدين: {e}")
        return

    advisor_name = None
    mask = df.apply(lambda row: row.astype(str).str.contains(student_id, regex=False, na=False).any(), axis=1)
    matched_rows = df[mask]
    if not matched_rows.empty:
        for _, row in matched_rows.iterrows():
            text = " ".join(row.dropna().astype(str))
            match = re.search(r"00\d{5,7}\s*([^\d\n\r]+)", text)
            if match:
                advisor_name = match.group(1).strip()
                advisor_name = re.sub(r"مرشد أكاديمي", "", advisor_name)
                advisor_name = advisor_name.replace(",", "").replace('"', "").strip()
                break
    await sent_msg.delete()
    if advisor_name:
        await update.message.reply_text(f"👨‍🏫 مرشدك التدريبي هو:\nأ. {advisor_name}")
    else:
        await update.message.reply_text("⚠️ لم يتم العثور على اسم المرشد.")

async def send_gpa(update, context, student_id):
    pdf_path = FILES.get("gpa")
    if not os.path.exists(pdf_path):
        await update.message.reply_text("❌ ملف المعدل غير متاح حالياً.")
        return
    sent_msg = await update.message.reply_text("🎓 جاري البحث عن معدلك...")
    gpa_value = None
    try:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                if student_id in line:
                    match = re.search(r"\b\d\.\d{2}\b", line)
                    if match:
                        gpa_value = match.group(0)
                        break
            if gpa_value:
                break
    except Exception as e:
        await sent_msg.delete()
        await update.message.reply_text(f"❌ خطأ في قراءة ملف المعدل: {e}")
        return

    await sent_msg.delete()
    if gpa_value:
        await update.message.reply_text(f"🎓 معدلك هو: {gpa_value}")
    else:
        await update.message.reply_text("⚠️ لم يتم العثور على المعدل.")

# خرائط العبارات إلى ملفات الخطط + كابتشنات
MAJOR_PHRASES_TO_PLAN = {
    "قيرتتلارصاتتللانلتتلااييرت": "VocationalSafetyAndHealth.pdf",
    "لااا لقللتلا رارهترا": "LabsPlan.pdf",
    "قعرلتلااصلقمتلالرقرل": "HRplan.pdf",
    "قحرتتفاارتتلالرقت": "EPplan.pdf",
    "قلرتترغاتتلةمارت": "FoodSafetyPlan.pdf",
}
PLAN_CAPTIONS = {
    "HRplan.pdf": "💼 الخطة التفصيلية لتخصص الموارد البشرية",
    "EPplan.pdf": "🌿 الخطة التفصيلية لتخصص حماية البيئة",
    "FoodSafetyPlan.pdf": "🍽️ الخطة التفصيلية لتخصص سلامة الأغذية",
    "LabsPlan.pdf": "🧪 الخطة التفصيلية لتخصص المختبرات الكيميائية",
    "VocationalSafetyAndHealth.pdf": "🦺 الخطة التفصيلية لتخصص السلامة والصحة المهنية",
}

def _normalize_spaces(s: str) -> str:
    return " ".join((s or "").split())

async def send_detailed_plan(update, context, student_id):
    # نعتمد على majors_index.json المبني مسبقًا
    index_path = "majors_index.json"
    if not os.path.exists(index_path):
        await update.message.reply_text("⚠️ فهرس التخصصات غير جاهز بعد. حاول لاحقًا.")
        return

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            majors_index = json.load(f)
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في قراءة فهرس التخصصات: {e}")
        return

    if student_id not in majors_index:
        await update.message.reply_text("⚠️ لم يتم العثور على بيانات المتدرب في فهرس التخصصات.")
        return

    text = _normalize_spaces(majors_index[student_id])
    plan_file_to_send = None
    for phrase, plan_file in MAJOR_PHRASES_TO_PLAN.items():
        if _normalize_spaces(phrase) in text and os.path.exists(plan_file):
            plan_file_to_send = plan_file
            break

    if not plan_file_to_send:
        await update.message.reply_text("⚠️ لم يتم العثور على التخصص المناسب.")
        return

    caption = PLAN_CAPTIONS.get(plan_file_to_send, "📑 خطتك التفصيلية")
    try:
        with open(plan_file_to_send, "rb") as f:
            await update.message.reply_document(f, filename=os.path.basename(plan_file_to_send), caption=caption)
    except Exception as e:
        await update.message.reply_text(f"❌ تعذر إرسال الملف: {e}")

async def send_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE, service: str):
    student_id = context.user_data.get("student_id")
    if not student_id:
        await update.message.reply_text("⚠️ الرجاء إدخال رقمك التدريبي أولاً.")
        return

    if service == "advisor":
        await send_advisor(update, context, student_id)
        return
    if service == "gpa":
        await send_gpa(update, context, student_id)
        return
    if service == "detailed_plan":
        await send_detailed_plan(update, context, student_id)
        return

    messages = {
        "schedule": "📄 جاري تجهيز جدولك...",
        "remaining": "📚 جاري حصر مقرراتك المتبقية...",
        "certificates": "📜 جاري تجهيز شهاداتك...",
    }
    sent_msg = await update.message.reply_text(messages.get(service, "⏳ جاري تجهيز الملف..."))

    pdf_path = FILES.get(service)
    index = INDEXES.get(service)
    if not pdf_path or not os.path.exists(pdf_path):
        await sent_msg.delete()
        await update.message.reply_text("❌ الملف المطلوب غير متاح حالياً.")
        return

    try:
        reader = PdfReader(pdf_path)
        writer = PdfWriter()

        if service == "certificates":
            pdf_path = FILES.get("certificates")
            index = INDEXES.get("certificates")
            ids_map = INDEXES.get("ids") or {}
            student_info = ids_map.get(student_id, {})
            nid = student_info.get("nid")

            if not nid or nid not in index:
                await sent_msg.delete()
                await update.message.reply_text("⚠️ لم يتم العثور على شهادات لهذا المتدرب.")
                return

            for i in index[nid]:
                writer.add_page(reader.pages[i])

            output_file = f"certificates_{student_id}.pdf"
            with open(output_file, "wb") as f:
                writer.write(f)

            compressed = f"compressed_certificates_{student_id}.pdf"
            success = compress_pdf_with_ghostscript(output_file, compressed)
            if not success:
                compressed = output_file

            await update.message.reply_document(
                open(compressed, "rb"),
                filename=os.path.basename(compressed),
                caption=f"📜 شهادات البرامج الخاصة بالمتدرب رقم {student_id}"
            )

            await sent_msg.delete()
            try:
                os.remove(output_file)
                if compressed != output_file:
                    os.remove(compressed)
            except Exception:
                pass
            return

        if service == "remaining":
            pages = index.get(student_id, [])
            if not pages:
                await sent_msg.delete()
                await update.message.reply_text(f"❌ لم يتم العثور على مقررات المتدرب {student_id}.")
                return
            for i in pages:
                writer.add_page(reader.pages[i])
        else:
            if student_id not in index:
                await sent_msg.delete()
                await update.message.reply_text("❌ لم يتم العثور على بياناتك.")
                return
            start = index[student_id]
            sorted_students = sorted(index.items(), key=lambda x: x[1])
            end = len(reader.pages)
            for sid, page_idx in sorted_students:
                if page_idx > start:
                    end = page_idx
                    break
            for i in range(start, end):
                writer.add_page(reader.pages[i])

        output_file = f"{service}_{student_id}.pdf"
        with open(output_file, "wb") as f:
            writer.write(f)

        compressed = f"compressed_{service}_{student_id}.pdf"
        if service == "remaining":
            success = compress_pdf_with_ghostscript(output_file, compressed)
            if not success:
                print("⚠️ فشل الضغط، سيتم إرسال النسخة الأصلية.", flush=True)
                compressed = output_file
        else:
            compress_pdf_with_ghostscript(output_file, compressed)

        captions = {
            "schedule": f"📄 جدول المتدرب رقم {student_id}",
            "remaining": f"📚 المقررات المتبقية للمتدرب رقم {student_id}",
            "gpa": f"🎓 المعدل للمتدرب رقم {student_id}",
            "certificates": f"📜 شهادات البرامج الخاصة بالمتدرب {student_id}",
        }

        await update.message.reply_document(
            open(compressed, "rb"),
            filename=f"{service}_{student_id}.pdf",
            caption=captions.get(service, f"📄 ملف {service} للمتدرب {student_id}")
        )

    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء تجهيز الملف: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await sent_msg.delete()
        try:
            if os.path.exists(output_file):
                os.remove(output_file)
            if os.path.exists(compressed) and compressed != output_file:
                os.remove(compressed)
        except Exception:
            pass



# =========================
# دالة مساعدة لبناء لوحة الأزرار
# =========================
def build_main_keyboard(student_id: str):
    """بناء لوحة الخدمات بناءً على حالة المتدرب (هل له مقررات أو شهادات)."""
    has_remaining = student_id in INDEXES.get("remaining", {})

    # نحصل على رقم الهوية من فهرس IDs
    ids_map = INDEXES.get("ids", {})
    rec = ids_map.get(student_id, {})
    nid = rec.get("nid", "")

    # هل يوجد شهادة بناء على رقم الهوية؟
    has_certificate = False
    if nid and nid in INDEXES.get("certificates", {}):
        has_certificate = True

    keyboard = [
        [KeyboardButton("📄 جدولي")],
        [KeyboardButton("👨‍🏫 مرشدي التدريبي"), KeyboardButton("🎓 معدلي")],
        [KeyboardButton("📑 خطتي التفصيلية")],
        [KeyboardButton("📤 تسجيل الخروج")]
    ]

    # نضيف المقررات إن وجدت
    if has_remaining:
        keyboard[0].append(KeyboardButton("📚 مقرراتي المتبقية"))

    # نضيف زر الشهادات فقط إذا له شهادة
    if has_certificate:
        keyboard[1].insert(0, KeyboardButton("📜 شهادات البرامج"))

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# =========================
# معالجات الرسائل
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 مرحباً!\nأرسل رقمك التدريبي (يبدأ بـ 44 ويتكون من 9 أرقام) للحصول على خدماتك.",
        reply_markup=ReplyKeyboardRemove()
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    student_id = convert_arabic_to_english(txt)
    _set_status(last_user=student_id)
    print(f"💬 المستخدم: {txt}", flush=True)

                # تسجيل الخروج
    if txt.strip() == "📤 تسجيل الخروج":
        last_id = context.user_data.get("student_id")
        context.user_data.clear()

        if last_id:
            context.user_data["last_student_id"] = last_id

        # ✅ إزالة لوحة الأزرار (حتى تختفي أيقونة المربعات)
        await update.message.reply_text(
            "جارٍ تسجيل الخروج...",
            reply_markup=ReplyKeyboardRemove()
        )
        await asyncio.sleep(0.3)

        # ✅ إرسال رسالة العد التنازلي مع زر إعادة التسجيل
        sent_msg = await update.message.reply_text(
            "✅ تم تسجيل خروجك بنجاح.\n\n"
            "يمكنك إدخال رقم تدريبي جديد أو إعادة تسجيل الدخول خلال 60 ثانية 🕐",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 إعادة تسجيل الدخول", callback_data="relogin")]
            ])
        )

        async def countdown_message(msg, chat_id):
            try:
                # 🕒 مجموعة رموز الساعة لتبديلها كل ثانية
                clock_emojis = ["🕐","🕑","🕒","🕓","🕔","🕕","🕖","🕗","🕘","🕙","🕚","🕛"]
                for remaining in range(59, 0, -1):
                    await asyncio.sleep(1)
                    clock = clock_emojis[remaining % len(clock_emojis)]
                    await msg.edit_text(
                        f"✅ تم تسجيل خروجك بنجاح.\n\n"
                        f"يمكنك إدخال رقم تدريبي جديد أو إعادة تسجيل الدخول قبل {remaining} ثانية {clock}",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔁 إعادة تسجيل الدخول", callback_data='relogin')]
                        ])
                    )

                # ⏳ بعد انتهاء المهلة
                await msg.delete()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "👋 مرحباً!\n"
                        "أرسل رقمك التدريبي\n"
                        "(يبدأ بـ 44 ويتكون من 9 أرقام) للحصول على خدماتك"
                    ),
                    reply_markup=ReplyKeyboardRemove()
                )
            except Exception as e:
                print("⚠️ خطأ أثناء العد التنازلي:", e, flush=True)

        # تشغيل العدّ التنازلي بالخلفية
        asyncio.create_task(countdown_message(sent_msg, update.effective_chat.id))
        return

        # ========= مرحلة التحقق على خطوتين =========

    # 1️⃣ المستخدم أدخل رقم متدرب صالح 44xxxxxxx
    if re.match(r"^44\d{7}$", student_id):
        if "student_id" in context.user_data:
            await update.message.reply_text("⚠️ يرجى تسجيل الخروج أولًا قبل إدخال رقم جديد.")
            return

        context.user_data["pending_student_id"] = student_id
        await update.message.reply_text("🪪 أدخل رقم الهوية الوطنية (10 أرقام):")
        return

    # 2️⃣ المستخدم في وضع انتظار الهوية وأرسل 10 أرقام
    if "pending_student_id" in context.user_data and re.match(r"^[0-9٠-٩]{10}$", txt):
        entered_nid = normalize_digits(txt)

        if not is_valid_nid(entered_nid):
            await update.message.reply_text("⚠️ أدخل رقم الهوية الوطنية الصحيح (10 أرقام يبدأ بـ 1).")
            return

        pending_id = context.user_data.get("pending_student_id")
        ids_map = INDEXES.get("ids") or {}
        rec = ids_map.get(pending_id)

        if not rec or "nid" not in rec:
            await update.message.reply_text("⚠️ لا توجد بيانات هوية مرتبطة بهذا الرقم التدريبي. تواصل مع الدعم.")
            return

        if normalize_digits(str(rec["nid"])) != entered_nid:
            await update.message.reply_text("❌ رقم الهوية غير مطابق لرقم المتدرب. حاول مرة أخرى.")
            return

        context.user_data["student_id"] = pending_id
        context.user_data.pop("pending_student_id", None)

        full_name = rec.get("name", "").strip()
        first_name = extract_first_name(full_name)

        keyboard = build_main_keyboard(pending_id)

        await update.message.reply_text(
            f"🎉 أهلاً وسهلاً {first_name}!\nالآن يمكنك الاستفادة من خدماتك:",
            reply_markup=keyboard
        )
        return

    # الخدمات
    mapping = {
        "📄 جدولي": "schedule",
        "📚 مقرراتي المتبقية": "remaining",
        "👨‍🏫 مرشدي التدريبي": "advisor",
        "🎓 معدلي": "gpa",
        "📑 خطتي التفصيلية": "detailed_plan",
        "📜 شهادات البرامج": "certificates",
    }

    service = mapping.get(txt)
    if service:
        sid = context.user_data.get("student_id")
        if not sid:
            await update.message.reply_text("⚠️ الرجاء إدخال رقمك التدريبي أولاً.")
            return
        await send_pdf(update, context, service)
        return

    # أي رسالة أخرى غير مفهومة
    await update.message.reply_text(
        "⚠️ يرجى إدخال رقم تدريبي صحيح :\n"
        "(يبدأ بـ 44 ويتكون من 9 أرقام)"
    )

# =========================
# التشغيل الرئيسي
# =========================
def main():
    _set_status(running=True, telegram_connected=False)
    # شغّل الفهرسة بالخلفية
    threading.Thread(target=initialize_indexes, daemon=True).start()

    print("🚀 تشغيل البوت...", flush=True)
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # 🟢 معالجات الأوامر والرسائل
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

       # 🟢 تعريف الدالة التي تتعامل مع زر "اضغط هنا لإعادة تسجيل الدخول"
    async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if query.data == "relogin":
            last_id = context.user_data.get("last_student_id")
            if not last_id:
                await query.edit_message_text("⚠️ لا يوجد رقم تدريبي سابق لإعادة تسجيل الدخول.")
                return

            # ✅ حذف رسالة العدّ التنازلي مع الزر فورًا
            try:
                await query.delete_message()
            except Exception:
                pass

            # ✅ إعادة تخزين رقم المتدرب
            context.user_data["student_id"] = last_id

            # ✅ إرسال لوحة الخدمات فقط مع رسالة ترحيبية نظيفة
            keyboard = build_main_keyboard(last_id)

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"✅ تم تسجيل دخولك مجددًا بالرقم ({last_id}).\nاختر الخدمة:",
                reply_markup=keyboard
            )

    # 🟢 تفعيل معالج الأزرار بعد تعريف الدالة
    app.add_handler(CallbackQueryHandler(handle_callback))

    # =========================
    # تهيئة الاتصال بعد بدء التطبيق
    # =========================
    async def post_init(application):
        try:
            me = await application.bot.get_me()
            print(f" معلومات البوت: @{me.username} (id={me.id})", flush=True)
            _set_status(telegram_connected=True)
            await application.bot.set_my_commands([("start", "بدء البوت")])
        except Exception as e:
            print(f"⚠️ تعذر التأكد من اتصال تيليجرام: {e}", flush=True)
            _set_status(telegram_connected=False)

    app.post_init = post_init

    print("✅ البوت جاهز لاستقبال الطلبات الآن.", flush=True)

    # =========================
    # تشغيل البوت
    # =========================
    try:
        app.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        pass
    finally:
        _set_status(
            running=False,
            telegram_connected=False,
            indexing=False,
            current_file="",
            index_progress=0.0
        )
        print("👋 تم إيقاف البوت، يتم إنهاء جميع العمليات...", flush=True)
        try:
            import os as _os, signal as _signal
            _os.kill(_os.getpid(), _signal.SIGTERM)
        except Exception as e:
            print("⚠️ فشل إنهاء العملية:", e, flush=True)
        time.sleep(0.2)
        os._exit(0)


if __name__ == "__main__":
    main()
