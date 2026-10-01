"""Use explicit dictionary inflections without treating derived words as synonyms."""
import re

_INFLECTION = re.compile(r"(?:复数|过去式|过去分词|现在分词|第三人称单数|比较级|最高级)\s*[：:]\s*([^|\n]+)")
_SINGLE_FORM = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")


def explicit_forms(blob: str) -> set[str]:
    forms = set()
    for match in _INFLECTION.finditer(str(blob or "")):
        for alternative in match.group(1).split("或"):
            form = alternative.strip()
            # "more even" is a phrase, not the independent form "more".
            if _SINGLE_FORM.fullmatch(form):
                forms.add(form)
    return forms
