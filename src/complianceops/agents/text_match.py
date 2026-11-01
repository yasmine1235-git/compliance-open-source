"""Pattern matching over document text."""

import re
import unicodedata


def normalize(text: str) -> str:
    """Remove accents and collapse whitespace, so line breaks and OCR accents do not matter."""
    decomposed = unicodedata.normalize("NFKD", text.replace("’", "'"))
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.split())


def first_match(pattern: str, texts: list[str]) -> tuple[int, int] | None:
    """Return the text index and offset of the first match, or ``None``."""
    compiled = re.compile(pattern, re.IGNORECASE)
    for index, text in enumerate(texts):
        match = compiled.search(text)
        if match:
            return index, match.start()
    return None


def blank_matches(pattern: str, texts: list[str]) -> list[str]:
    """Replace matches with spaces, keeping the offsets of everything else."""
    compiled = re.compile(pattern, re.IGNORECASE)
    return [compiled.sub(lambda match: " " * len(match.group()), text) for text in texts]
