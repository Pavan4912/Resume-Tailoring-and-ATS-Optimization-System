"""JD text is untrusted data: normalise it, cap it, and flag instruction-like content."""
from __future__ import annotations
import re
import unicodedata

INJECTION = re.compile(r"(ignore (all |any )?(previous|prior|above) (instructions|rules)|disregard .{0,30}instructions|"
                       r"you are now|system prompt|reveal .{0,20}(prompt|instructions))", re.I)


class JDError(ValueError):
    pass


def sanitize_jd(text: str, max_chars: int = 50000) -> tuple[str, list[str]]:
    if not text or not text.strip():
        raise JDError("The job description is empty.")
    if len(text) > max_chars:
        raise JDError(f"The job description is longer than {max_chars} characters.")
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    warnings = []
    if INJECTION.search(text):
        warnings.append("The JD contains instruction-like text. It is treated purely as data and ignored as instructions.")
    if len(re.findall(r"\w+", text)) < 15:
        warnings.append("The JD is very short; keyword analysis will be unreliable.")
    return text, warnings
