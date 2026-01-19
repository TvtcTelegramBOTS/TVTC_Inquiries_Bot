#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Given a trainee ID (44xxxxxxx), find the page(s) containing that ID in the majors PDF,
then detect the trainee's major by searching for known garbled Arabic phrases.

Output: ONLY the major name (Arabic), or "غير معروف" if no phrase matched.

Usage:
  python major_only.py 446266254 --pdf "TNumbers with majors.pdf"
  python major_only.py 446266254 --pdf "TNumbers with majors.pdf" --window 2
"""

import argparse
import os
import re
import unicodedata
from typing import Dict, Optional, List

from PyPDF2 import PdfReader

def normalize_text(s: str) -> str:
    """Light normalization: NFKC + remove bidi chars + collapse spaces + arabic-indic digits -> ascii."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    s = re.sub(r"[\u200f\u200e\u200b\u202a\u202b\u202c\u202d\u202e]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

# Garbled phrase -> Major (Arabic name)
PHRASE_TO_MAJOR: Dict[str, str] = {
    "قيرتتلارصاتت لاااتتلااييرت": "السلامة والصحة المهنية",
    "لااا لقللتلا رارهترا": "المختبرات الكيميائية",
    "عرلتلاارلقمتلاليقرل": "الموارد البشرية",
    "قيرتت ابرتتلالرقت": "حماية البيئة",
    "قيرتترماتتلةينرت": "سلامة الأغذية",
}

SID_RE = re.compile(r"^44\d{7}$")

def find_pages_with_id(reader: PdfReader, student_id: str) -> List[int]:
    """Return all 0-based page indexes that contain the student_id (after normalization)."""
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if student_id in normalize_text(text):
            pages.append(i)
    return pages

def detect_major(text: str) -> Optional[str]:
    norm = normalize_text(text)
    for phrase, major in PHRASE_TO_MAJOR.items():
        if normalize_text(phrase) in norm:
            return major
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("student_id", help="Trainee ID starting with 44 (9 digits). Example: 446266254")
    ap.add_argument("--pdf", default="TNumbers with majors.pdf", help="Path to majors PDF")
    ap.add_argument("--window", type=int, default=1,
                    help="Search +/- N pages around pages that contain the ID (default 1)")
    args = ap.parse_args()

    sid = normalize_text(args.student_id)
    if not SID_RE.fullmatch(sid):
        raise SystemExit("❌ أدخل رقم متدرب صحيح يبدأ بـ 44 ويتكون من 9 أرقام.")

    if not os.path.exists(args.pdf):
        raise SystemExit(f"❌ ملف PDF غير موجود: {args.pdf}")

    reader = PdfReader(args.pdf)
    hit_pages = find_pages_with_id(reader, sid)

    if not hit_pages:
        print("غير معروف")
        return

    # Search around each hit page (page-window .. page+window)
    total_pages = len(reader.pages)
    checked = set()
    for p in hit_pages:
        start = max(0, p - args.window)
        end = min(total_pages - 1, p + args.window)
        for i in range(start, end + 1):
            if i in checked:
                continue
            checked.add(i)
            text = reader.pages[i].extract_text() or ""
            major = detect_major(text)
            if major:
                print(major)
                return

    print("غير معروف")

if __name__ == "__main__":
    main()
