import os
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from PyPDF2 import PdfReader, PdfWriter

# 🔹 إعدادات أساسية
PDF_FILE = "Scheduals.pdf"
import os
BOT_TOKEN = "7952874560:AAGfvHVSFGY9eid9DJhLMpwUzbYiDJwwusw"


# 🔹 بناء فهرس يحتوي على موقع كل رقم أكاديمي (صفحة البداية)
def build_index(pdf_path):
    index = {}
    reader = PdfReader(pdf_path)
    print("⏳ جاري تحليل الملف واستخراج الأرقام الأكاديمية...")
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        matches = re.findall(r"\b44\d{7}\b", text)
        for m in matches:
            if m not in index:  # أول ظهور للطالب
                index[m] = i
    print(f"✅ تم العثور على {len(index)} طالباً في {len(reader.pages)} صفحة.")
    return index

INDEX = build_index(PDF_FILE)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً 👋\nأرسل رقمك التدريبي (يبدأ بـ 44 ويتكون من 9 أرقام) للحصول على جدولك الدراسي الكامل بصيغة PDF."
    )

async def get_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    student_id = update.message.text.strip()

    if not re.match(r"^44\d{7}$", student_id):
        await update.message.reply_text("⚠️ الرجاء إدخال رقم تدريبي صحيح يبدأ بـ 44 ويتكون من 9 أرقام.")
        return

    if student_id not in INDEX:
        await update.message.reply_text("❌ لم يتم العثور على جدول بهذا الرقم الأكاديمي.")
        return

    # 🔸 إرسال رسالة انتظار
    waiting_msg = await update.message.reply_text("⏳ يرجى الانتظار، جاري جلب ملف الجدول الخاص بك...")

    reader = PdfReader(PDF_FILE)
    writer = PdfWriter()

    # صفحة البداية
    start_page = INDEX[student_id]

    # تحديد نهاية نطاق الصفحات
    sorted_students = sorted(INDEX.items(), key=lambda x: x[1])
    current_index = sorted_students.index((student_id, start_page))

    if current_index < len(sorted_students) - 1:
        end_page = sorted_students[current_index + 1][1]
    else:
        end_page = len(reader.pages)

    # جمع الصفحات الخاصة بالطالب
    for i in range(start_page, end_page):
        writer.add_page(reader.pages[i])

    output_file = f"{student_id}.pdf"
    with open(output_file, "wb") as f:
        writer.write(f)

    # إرسال الملف أولاً
    await update.message.reply_document(
        open(output_file, "rb"),
        filename=f"{student_id}.pdf",
        caption=f"📄 جدول المتدرب رقم {student_id}"
    )

    # 🔹 الآن نحذف رسالة "يرجى الانتظار"
    try:
        await waiting_msg.delete()
    except:
        pass

    os.remove(output_file)


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, get_schedule))
    print("🚀 البوت يعمل الآن...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
