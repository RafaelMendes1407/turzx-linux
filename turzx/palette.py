"""Category filtering shared by the component library and its tests."""

import unicodedata

from .metrics import CATEGORIES, spec


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def groups(keys, selected="cpu", query=""):
    query = normalized(query.strip())
    result = {}
    for category, title in CATEGORIES.items():
        if not query and category != selected:
            continue
        matches = [key for key in keys if spec(key).category == category and
                   (not query or query in normalized(spec(key).label) or query in normalized(title))]
        if matches:
            result[category] = matches
    return result
