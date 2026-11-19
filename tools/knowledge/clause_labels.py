"""Display only clause/table headings literally present in an OCR candidate."""
import re


def clause_label(text, original):
    if '条款待核' not in original:
        return original
    # Require a line heading and a boundary. Decimal measurements (e.g. 0.04%)
    # and references inside prose are not clause headings.
    matches = re.finditer(r'(?m)^\s*(表\s*\d{1,2}\.\d{1,2}\.\d{1,2}(?:[-－]\d{1,2})?|[1-9]\d?\.\d{1,2}\.\d{1,2})(?=\s|[\u3400-\u9fff]|$)', text)
    headings = list(dict.fromkeys(re.sub(r'\s+', '', m.group(1)) for m in matches))[:16]
    if not headings:
        return original
    return original + '；片段原文条／表号：' + '、'.join(headings) + '（OCR候选，须原页核验）'
