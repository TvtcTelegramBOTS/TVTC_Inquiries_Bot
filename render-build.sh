#!/usr/bin/env bash
set -o errexit

# تحديث النظام
apt-get update

# تثبيت ghostscript للضغط
apt-get install -y ghostscript

# تثبيت متطلبات البايثون
pip install -r requirements.txt
