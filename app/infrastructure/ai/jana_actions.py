import re


ACTION_ROUTES = {
    "leave_new": ("Оформить отпуск", "/calendar?select=1"),
    "advance_new": ("Запросить аванс", "/requests/new?type=advance"),
    "requests_mine": ("Мои заявки", "/requests"),
    "academy": ("Обучение", "/academy"),
    "profile": ("Мой профиль", "/profile"),
    "calendar": ("Календарь", "/calendar"),
    "notifications": ("Уведомления", "/notifications"),
    "requests_review": ("Согласования", "/requests?scope=review"),
    "support": ("Обратиться в HR", "/support"),
}

SOURCE_ACTIONS = {
    1: "leave_new", 2: "advance_new", 3: "profile", 4: "requests_mine",
    5: "profile", 6: "profile", 7: "academy", 8: "academy",
    9: "notifications", 10: "support", 11: "calendar", 12: "requests_mine",
    13: "academy", 14: "leave_new", 15: "support", 16: "requests_review",
    17: "requests_mine", 18: "requests_mine",
}

KAZAKH_ACTION_LABELS = {
    "leave_new": "Демалысты рәсімдеу",
    "advance_new": "Аванс сұрау",
    "requests_mine": "Менің өтінімдерім",
    "academy": "Оқу",
    "profile": "Менің профилім",
    "calendar": "Күнтізбе",
    "notifications": "Хабарламалар",
    "requests_review": "Келісулер",
    "support": "HR-ға жүгіну",
}

KAZAKH_UI_CAPTIONS = {
    **{ACTION_ROUTES[key][0]: label for key, label in KAZAKH_ACTION_LABELS.items()},
    "Продолжить": "Жалғастыру",
    "Отправить заявку": "Өтінім жіберу",
    "Отозвать заявку": "Өтінімді кері қайтару",
    "Завершить урок": "Сабақты аяқтау",
    "Завершить тест": "Тестті аяқтау",
    "Повторить тест": "Тестті қайталау",
    "Повторить материал": "Материалды қайталау",
    "На согласовании": "Келісуде",
    "Согласовано": "Келісілді",
    "Отклонено": "Қабылданбады",
    "Отозвана": "Кері қайтарылған",
    "На согласование": "Келісуге",
    "Согласовать заявку": "Өтінімді келісу",
    "Передать вопрос в HR": "Сұрақты HR-ға жіберу",
    "Завершено": "Аяқталды",
    "Заявки": "Өтінімдер",
}


def localize_ui_captions(answer: str, language: str) -> str:
    if language != "kk":
        return answer
    for label, translated in KAZAKH_UI_CAPTIONS.items():
        answer = re.sub(r'([«"“])' + re.escape(label) + r'([»"”])', lambda match: match[1] + translated + match[2], answer)
    return answer


def source_action_ids(sources: list[dict]) -> list[str]:
    actions = []
    for source in sources:
        source_id = str(source["id"])
        if source_id.startswith("20000000-0000-4000-8000-"):
            try:
                action = SOURCE_ACTIONS.get(int(source_id.rsplit("-", 1)[-1]))
            except ValueError:
                continue
            if action:
                actions.append(action)
    return list(dict.fromkeys(actions))


def action_buttons(ids: list[str], role: str = "worker", language: str = "ru") -> list[dict]:
    buttons = []
    for action_id in dict.fromkeys(ids):
        if action_id not in ACTION_ROUTES:
            continue
        if action_id == "requests_review" and role not in {"manager", "director", "hr_admin"}:
            continue
        label, href = ACTION_ROUTES[action_id]
        if language == "kk":
            label = KAZAKH_ACTION_LABELS[action_id]
        buttons.append({"id": action_id, "label": label, "href": href})
    return buttons[:3]
