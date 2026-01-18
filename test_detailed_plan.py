#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone test for the "Detailed Plan" selection logic.

What it does:
- Loads majors_index.json
- Fetches the major text for a given student_id
- Normalizes Arabic text (light normalization)
- Tries to match phrases in MAJOR_PHRASES_TO_PLAN to select the correct plan PDF
- Prints diagnostics: matched phrase, chosen file, and whether the file exists

Usage:
  python test_detailed_plan.py 44XXXXXXX

Optional:
  python test_detailed_plan.py 44XXXXXXX --all-matches   # show all matching phrases (not just first)
  python test_detailed_plan.py 44XXXXXXX --json majors_index.json
"""

import argparse
import os
import json
import re
from typing import Dict, List, Tuple, Optional

def normalize_ar(text: str) -> str:
    if not text:
        return ""
    # unify whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # remove tatweel + harakat
    text = re.sub(r"[ـًٌٍَُِّْ]", "", text)
    # unify some common variants
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي")
    return text

# 🔧 EDIT THIS mapping to match your project EXACTLY (phrases -> plan PDF file)
MAJOR_PHRASES_TO_PLAN: Dict[str, str] = {
    # Examples (replace with your real phrases/files):
    "قيرتتلارصاتت لاااتتلااييرت": "VocationalSafetyAndHealth.pdf",
    "لااا لقللتلا رارهترا": "LabsPlan.pdf",
    "قيرتت ابرتتلالرقت": "HRplan.pdf",
    "قحرتتفاارتتلالرقت": "EPplan.pdf",
    "قيرتترماتتلةينرت": "FoodSafetyPlan.pdf",
}

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def find_matches(major_text: str) -> List[Tuple[str, str, bool]]:
    """Return a list of (phrase, plan_file, exists) that match major_text."""
    norm_text = normalize_ar(major_text)
    matches: List[Tuple[str, str, bool]] = []
    for phrase, plan_file in MAJOR_PHRASES_TO_PLAN.items():
        if normalize_ar(phrase) in norm_text:
            matches.append((phrase, plan_file, os.path.exists(plan_file)))
    return matches

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("student_id", help="Student ID like 44xxxxxxx")
    ap.add_argument("--json", dest="json_path", default="majors_index.json", help="Path to majors_index.json")
    ap.add_argument("--all-matches", action="store_true", help="Show all matches instead of only first")
    ap.add_argument("--snippet", type=int, default=280, help="How many chars of major text to print")
    args = ap.parse_args()

    if not MAJOR_PHRASES_TO_PLAN:
        print("❌ MAJOR_PHRASES_TO_PLAN is empty.")
        print("   Open this file and fill MAJOR_PHRASES_TO_PLAN with your phrases/files.")
        raise SystemExit(2)

    student_id = str(args.student_id).strip()
    if not os.path.exists(args.json_path):
        print(f"❌ JSON not found: {args.json_path}")
        raise SystemExit(2)

    majors = load_json(args.json_path)
    if student_id not in majors:
        print(f"❌ student_id not found in JSON: {student_id}")
        sample = list(majors.keys())[:10]
        print(f"🔎 Sample keys: {sample}")
        raise SystemExit(3)

    major_text = majors.get(student_id, "")
    print("✅ student_id found")
    print("—" * 60)
    print("🧾 Major text snippet:")
    print(major_text[: args.snippet])
    print("—" * 60)

    matches = find_matches(major_text)

    if not matches:
        print("❌ No phrase matched the extracted major text.")
        print("🔧 Tips:")
        print("  - Confirm the major text snippet contains your phrase exactly (after normalization).")
        print("  - Add/adjust phrases in MAJOR_PHRASES_TO_PLAN.")
        print("  - Check for spelling variants (أ/ا, ى/ي, spaces, etc.).")
        raise SystemExit(4)

    if args.all_matches:
        print(f"✅ Matches found: {len(matches)}")
        for i, (phrase, plan_file, exists) in enumerate(matches, 1):
            print(f"{i}) phrase: {phrase}")
            print(f"   file:   {plan_file}")
            print(f"   exists: {exists}")
    else:
        phrase, plan_file, exists = matches[0]
        print("✅ First match (this is what your bot will likely pick):")
        print(f"   phrase: {phrase}")
        print(f"   file:   {plan_file}")
        print(f"   exists: {exists}")
        if not exists:
            print("⚠️ File does not exist in the current working directory.")
            print("   - Make sure the plan PDF is in the same folder you run this from,")
            print("     or update the path in MAJOR_PHRASES_TO_PLAN.")

if __name__ == "__main__":
    main()
