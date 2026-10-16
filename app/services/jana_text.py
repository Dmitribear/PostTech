"""Conservative typo repair for a small HR vocabulary, without rewriting intent."""

import re

# Deliberately not every word in the knowledge base. For example, correcting
# "облучение" to "обучение" would turn an unrelated medical question into HR.
# Negations, amounts, names, actions and general vocabulary are not fuzzy targets.
_TARGETS = frozenset({
    "отпуск", "отпуска", "отпуску", "отпуске", "отпуском", "отпусков",
    "аванс", "аванса", "авансу", "авансе", "авансом", "авансов",
    "заявка", "заявки", "заявку", "заявке", "заявок", "заявками",
    "заявление", "заявления", "заявлению", "заявлении", "заявлений",
    "уведомление", "уведомления", "уведомлений", "уведомлении", "уведомлениях",
    "профиль", "профиля", "профиле", "профилю", "профилей",
    "календарь", "календаря", "календаре", "календарём", "календарю",
    "синхронизация", "синхронизации", "синхронизацию",
})
# Reviewed misspellings of question verbs; do not fuzzy-match arbitrary verbs.
_TYPOS = {
    "офрмить": "оформить", "посматреть": "посмотреть", "запрасить": "запросить",
    "отпск": "отпуск", "отпсук": "отпуск", "отпукс": "отпуск", "авнас": "аванс",
    "уведмления": "уведомления", "профль": "профиль", "назначеные": "назначенные",
}
_WORD = re.compile(r"(?<![\w-])[а-яё]{5,}(?![\w-])", re.I)
_ADDRESS = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+|\bwww\.\S+|[\w.+-]+@[\w.-]+\.[\w.-]+", re.I)


def _one_edit(left: str, right: str) -> bool:
    """One insertion/deletion/substitution or adjacent transposition."""
    if abs(len(left) - len(right)) > 1 or left == right:
        return False
    if len(left) == len(right):
        positions = [i for i, (a, b) in enumerate(zip(left, right, strict=True)) if a != b]
        return len(positions) == 1 or (
            len(positions) == 2 and positions[1] == positions[0] + 1
            and left[positions[0]] == right[positions[1]]
            and left[positions[1]] == right[positions[0]]
        )
    short, long = (left, right) if len(left) < len(right) else (right, left)
    offset = next((i for i, (a, b) in enumerate(zip(short, long)) if a != b), len(short))
    return short[offset:] == long[offset + 1:]


def normalize_question(question: str) -> str:
    """Repair at most two unambiguous domain typos; keep all other text intact."""
    replacements = []
    addresses = [match.span() for match in _ADDRESS.finditer(question)]
    for match in _WORD.finditer(question):
        if any(start <= match.start() < end for start, end in addresses):
            continue
        original = match.group()
        word = original.casefold()
        if word in _TARGETS or word in _TYPOS.values():
            continue
        # Short unknown words are too ambiguous (e.g. опуск / отпуск, Авант /
        # аванс). For them use only reviewed misspellings. Also preserve possible
        # proper names instead of inferring a domain term from capitalization.
        if word not in _TYPOS and (len(word) < 8 or original[0].isupper()):
            continue
        candidates = [_TYPOS[word]] if word in _TYPOS else [target for target in _TARGETS if _one_edit(word, target)]
        if len(candidates) != 1:
            continue
        replacement = candidates[0]
        if original.isupper():
            replacement = replacement.upper()
        elif original[0].isupper():
            replacement = replacement.capitalize()
        replacements.append((match.start(), match.end(), replacement))
    if len(replacements) > 2:
        return question
    for start, end, replacement in reversed(replacements):
        question = question[:start] + replacement + question[end:]
    return question
