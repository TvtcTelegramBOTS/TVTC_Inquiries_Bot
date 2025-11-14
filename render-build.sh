#!/usr/bin/env bash
set -o errexit

# تحديث النظام
apt-get update

# تثبيت Tesseract OCR
apt-get install -y tesseract-ocr

# تثبيت لغات OCR العربية
apt-get install -y tesseract-ocr-ara

# تثبيت ghostscript للضغط
apt-get install -y ghostscript

# تثبيت poppler-utils إذا احتجناه لاحقاً
apt-get install -y poppler-utils

# تثبيت متطلبات البايثون
pip install -r requirements.txt
