"""Use explicit dictionary inflections without treating derived words as synonyms."""
import re

_INFLECTION = re.compile(r"(?:复数|过去式|过去分词|现在分词|第三人称单数|比较级|最高级)\s*[：:]\s*([^|\n]+)")


def explicit_forms(blob: str) -> set[str]:
    forms = set()
    for match in _INFLECTION.finditer(str(blob or "")):
        forms.update(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", match.group(1)))
    return forms
