# bot.py
import os
import re
import sys
import io
import json
import time
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

# =========================
# فهرسة PDF (مع تقدم لحظي)
# =========================
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
                index.setdefault(match, []).append(i-1)  # صفر-مؤشر
            percent = (i / total_pages) * 100
            _set_status(index_progress=percent)
            print(f"فهرسة remaining: الصفحة {i}/{total_pages} ({percent:.1f}%)", flush=True)
            time.sleep(0.01)  # السماح لخادم الحالة بالرد

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

def build_index(pdf_path):
    _set_status(indexing=True, current_file=os.path.basename(pdf_path), index_progress=0.0)
    try:
        if not os.path.exists(pdf_path):
            print(f"⚠️ الملف {pdf_path} غير موجود.", flush=True)
            return {}
        print(f"⏳ فهرسة (index) الملف: {pdf_path}", flush=True)
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        index = {}
        start_time = time.time()

        for i, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            for m in re.findall(r"\b44\d{7}\b", text):
                if m not in index:
                    index[m] = i-1
            percent = (i / total_pages) * 100
            _set_status(index_progress=percent)
            print(f"فهرسة index: الصفحة {i}/{total_pages} ({percent:.1f}%)", flush=True)
            time.sleep(0.01)

        elapsed = time.time() - start_time
        print(f"✅ تم فهرسة {pdf_path} ({len(index)} متدرب) خلال {elapsed:.1f} ثانية.", flush=True)
        return index
    except Exception as e:
        print("❌ خطأ أثناء فهرسة:", e, flush=True)
        import traceback; traceback.print_exc()
        return {}
    finally:
        _set_status(indexing=False, current_file="", index_progress=0.0)

# =========================
# تهيئة الفهارس (تشغل بالخلفية)
# =========================
INDEXES = {
    "schedule": {},
    "advisor": None,
    "remaining": {},
    "gpa": {},
    "majors": {}
}

def initialize_indexes():
    print("🚀 بدء تشغيل النظام وفهرسة الملفات بالخلفية...", flush=True)
    try:
        # schedule
        print("\n📂 فهرسة SCHEDULE ...", flush=True)
        INDEXES["schedule"] = build_index(FILES["schedule"])

        # remaining
        print("\n📂 فهرسة REMAINING ...", flush=True)
        INDEXES["remaining"] = build_remaining_index(FILES["remaining"])

        # gpa (قد لا يحتاج فهرسة؛ نتركه فارغ)
        INDEXES["gpa"] = {}

        # majors (فهرس نصي سريع للبحث)
        print("\n📂 فهرسة MAJORS ...", flush=True)
        INDEXES["majors"] = build_majors_index(FILES["majors"])

        # advisor (CSV لا يحتاج فهرسة)
        INDEXES["advisor"] = None

        print("\n✅ تم تجهيز جميع الفهارس بنجاح.", flush=True)
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
            # احصل على نهاية مقطع الطالب عبر الطالب التالي
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
        # 📦 ضغط الملف قبل الإرسال
        if service == "remaining":
            # نضغط ملف المقررات المتبقية إلزاميًا حتى يكون أسرع في التحميل
            success = compress_pdf_with_ghostscript(output_file, compressed)
            if not success:
                print("⚠️ فشل الضغط، سيتم إرسال النسخة الأصلية.", flush=True)
                compressed = output_file
        else:
            # باقي الخدمات تُضغط كالمعتاد فقط
            compress_pdf_with_ghostscript(output_file, compressed)

        captions = {
            "schedule": f"📄 جدول المتدرب رقم {student_id}",
            "remaining": f"📚 المقررات المتبقية للمتدرب رقم {student_id}",
            "gpa": f"🎓 المعدل للمتدرب رقم {student_id}",
        }

        await update.message.reply_document(
            open(compressed, "rb"),
            filename=f"{service}_{student_id}.pdf",
            caption=captions.get(service, f"📄 ملف {service} للمتدرب {student_id}")
        )
    except Exception as e:
        await update.message.reply_text(f"❌ حدث خطأ أثناء تجهيز الملف: {e}")
        import traceback; traceback.print_exc()
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
        # نحفظ الرقم مؤقتًا قبل المسح
        last_id = context.user_data.get("student_id")

        # نمسح كل البيانات
        context.user_data.clear()

        # نعيد تخزين آخر رقم بشكل دائم حتى بعد المسح
        if last_id:
            context.user_data["last_student_id"] = last_id

        # 🔹 نحذف لوحة الأزرار القديمة (حتى تختفي أيقونة القائمة)
        await update.message.reply_text(" ", reply_markup=ReplyKeyboardRemove())

        # 🔹 زر إعادة تسجيل الدخول
        inline_keyboard = [
            [InlineKeyboardButton("اضغط هنا لإعادة تسجيل الدخول", callback_data="relogin")]
        ]

        # 🔹 رسالة واحدة أنيقة
        await update.message.reply_text(
            "👋 تم تسجيل خروجك بنجاح.\n\n🔁 أدخل رقم تدريبي آخر أو اضغط الزر أدناه لإعادة تسجيل الدخول:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard)
        )

        return

    # إعادة تسجيل الدخول
    if txt == "🔁 إعادة تسجيل الدخول":
        last_id = context.user_data.get("last_student_id")
        if not last_id:
            await update.message.reply_text("⚠️ لا يوجد رقم تدريبي سابق لإعادة تسجيل الدخول.")
            return

        context.user_data["student_id"] = last_id
        keyboard = [
            [KeyboardButton("📄 جدولي"), KeyboardButton("📚 مقرراتي المتبقية")],
            [KeyboardButton("👨‍🏫 مرشدي التدريبي"), KeyboardButton("🎓 معدلي")],
            [KeyboardButton("📑 خطتي التفصيلية")],
            [KeyboardButton("📤 تسجيل الخروج")]
        ]
        await update.message.reply_text(
            f"✅ تم تسجيل دخولك مجددًا بالرقم ({last_id})\nاختر الخدمة:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return


    # إدخال رقم المتدرب
    if re.match(r"^44\d{7}$", student_id):
        # إذا المستخدم مسجّل دخول مسبقًا
        if "student_id" in context.user_data:
            await update.message.reply_text("⚠️ يرجى تسجيل الخروج أولًا قبل إدخال رقم جديد.")
            return

        # تسجيل جديد
        context.user_data["student_id"] = student_id
        keyboard = [
            [KeyboardButton("📄 جدولي"), KeyboardButton("📚 مقرراتي المتبقية")],
            [KeyboardButton("👨‍🏫 مرشدي التدريبي"), KeyboardButton("🎓 معدلي")],
            [KeyboardButton("📑 خطتي التفصيلية")],
            [KeyboardButton("📤 تسجيل الخروج")]
        ]
        await update.message.reply_text(
            f"✅ تم تسجيل دخولك بالرقم ({student_id}). اختر الخدمة:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return

    # خرائط الأزرار إلى الخدمات
    mapping = {
        "📄 جدولي": "schedule",
        "📚 مقرراتي المتبقية": "remaining",
        "👨‍🏫 مرشدي التدريبي": "advisor",
        "🎓 معدلي": "gpa",
        "📑 خطتي التفصيلية": "detailed_plan",
    }
    service = mapping.get(txt)
    if service:
        sid = context.user_data.get("student_id")
        if not sid:
            await update.message.reply_text("⚠️ الرجاء إدخال رقمك التدريبي أولاً.")
            return
        await send_pdf(update, context, service)
        return

    await update.message.reply_text("⚠️ يرجى إدخال رقم تدريبي صحيح يبدأ بـ 44 أو اختر خدمة من الأزرار.")

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

            # إعادة تخزين رقم المتدرب
            context.user_data["student_id"] = last_id

            # تعديل الرسالة الأصلية لتأكيد الدخول
            await query.edit_message_text(
                f"✅ تم تسجيل دخولك مجددًا بالرقم ({last_id})."
            )

            # إرسال رسالة جديدة مع قائمة الخدمات (ReplyKeyboardMarkup)
            keyboard = [
                [KeyboardButton("📄 جدولي"), KeyboardButton("📚 مقرراتي المتبقية")],
                [KeyboardButton("👨‍🏫 مرشدي التدريبي"), KeyboardButton("🎓 معدلي")],
                [KeyboardButton("📑 خطتي التفصيلية")],
                [KeyboardButton("📤 تسجيل الخروج")]
            ]

            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="اختر الخدمة:",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
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
            # إيقاف خادم الحالة
            import os as _os, signal as _signal
            _os.kill(_os.getpid(), _signal.SIGTERM)
        except Exception as e:
            print("⚠️ فشل إنهاء العملية:", e, flush=True)
        time.sleep(0.2)
        os._exit(0)


if __name__ == "__main__":
    main()
