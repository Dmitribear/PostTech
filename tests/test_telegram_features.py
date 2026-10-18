import pytest
from test_telegram_worker import (
    CID,
    RID,
    USER,
    FakePortal,
    FakeTelegram,
    button,
    mutations,
    run,
    update,
)

from app.application.dto.digital_hr import CourseProgressUpdate
from app.infrastructure.ai.jana_actions import KAZAKH_ACTION_LABELS
from app.telegram.bot import JANA_CALLBACKS, Bot
from app.telegram.client import RemoteError


class CoursePortal(FakePortal):
    def __init__(self):
        super().__init__()
        self.course = {
            "id": CID,
            "title": "Аналитика данных",
            "course_type": "external",
            "provider": "Яндекс Практикум",
            "external_url": "https://practicum.yandex.ru/data-analyst/",
            "description": "Повышение квалификации",
            "owner_employee_id": "employee-one",
            "assignment": {
                "progress_percent": 25,
                "status": "in_progress",
                "score_percent": None,
                "due_on": "2026-12-01",
            },
            "lessons": [],
            "quiz": [],
        }
        self.progress_events = 0

    async def request(self, method, path, user_id=None, **kwargs):
        if method == "PATCH" and path == f"/academy/courses/{CID}/progress":
            self.calls.append((method, path, user_id, kwargs))
            payload = CourseProgressUpdate.model_validate(kwargs["body"])
            current = self.course["assignment"]
            if payload.progress_percent > current["progress_percent"]:
                self.progress_events += 1
                current.update(
                    progress_percent=payload.progress_percent,
                    status="completed"
                    if payload.progress_percent == 100
                    else "in_progress",
                )
            return dict(current)
        return await super().request(method, path, user_id, **kwargs)


def buttons(tg):
    return [item for row in tg.messages[-1][2]["inline_keyboard"] for item in row]


@pytest.mark.parametrize("personal", [False, True])
def test_external_and_personal_courses_show_provider_deadline_link_and_no_quiz(
    personal,
):
    async def scenario():
        api, tg = CoursePortal(), FakeTelegram()
        api.course["owner_employee_id"] = "employee-one" if personal else None
        await Bot(api, tg).handle_update(update(callback=f"course:{CID}"))
        text = tg.messages[-1][1]
        assert "Яндекс Практикум" in text and "2026-12-01" in text and "25%" in text
        assert any(
            item.get("url") == api.course["external_url"] for item in buttons(tg)
        )
        assert any(
            item.get("callback_data") == f"progress:{CID}" for item in buttons(tg)
        )
        assert not any(
            item.get("callback_data", "").startswith(("quiz:", "material:"))
            for item in buttons(tg)
        )
        assert "Результат" not in text and not mutations(api)

    run(scenario())


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        "http://example.com",
        "https://user:pass@example.com",
        "https://localhost",
        "https://127.0.0.1",
        "https://example.com/a b",
        "https://example.com\\@evil.invalid",
    ],
)
def test_course_buttons_reject_unsafe_external_links(link):
    async def scenario():
        api, tg = CoursePortal(), FakeTelegram()
        api.course["external_url"] = link
        await Bot(api, tg).handle_update(update(callback=f"course:{CID}"))
        assert not any("url" in item for item in buttons(tg))

    run(scenario())


@pytest.mark.parametrize("progress", [55, 100])
def test_external_progress_requires_confirmation_and_updates_same_api(progress):
    async def scenario():
        api, tg = CoursePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update(callback=f"progress:{CID}"))
        await bot.handle_update(update(f"{progress}%", number=2))
        assert not mutations(api) and bot.sessions[USER].flow is None
        if progress == 100:
            assert "не проверка площадкой" in tg.messages[-1][1]
        confirm = button(tg)
        await bot.handle_update(update(callback=confirm, number=3))
        call = mutations(api)[-1]
        assert call[:3] == ("PATCH", f"/academy/courses/{CID}/progress", USER)
        assert call[3]["body"] == {"progress_percent": progress}
        assert api.course["assignment"]["progress_percent"] == progress
        assert (
            f"Прогресс: {progress}%" in tg.messages[-1][1]
            and "None%" not in tg.messages[-1][1]
        )
        assert any(item.get("callback_data") == f"course:{CID}" for item in buttons(tg))
        await bot.handle_update(update(callback=confirm, number=4))
        assert len(mutations(api)) == 1

    run(scenario())


def test_progress_delivery_retry_reuses_key_and_does_not_duplicate_progress():
    async def scenario():
        api, tg = CoursePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update(callback=f"progress:{CID}"))
        await bot.handle_update(update("100", number=2))
        confirm = button(tg)
        tg.failure = RemoteError("Telegram", 503)
        with pytest.raises(RemoteError):
            await bot.handle_update(update(callback=confirm, number=3))
        first_key = mutations(api)[-1][3]["key"]
        tg.failure = None
        await bot.handle_update(update(callback=confirm, number=3))
        assert mutations(api)[-1][3]["key"] == first_key
        assert api.progress_events == 1

    run(scenario())


@pytest.mark.parametrize("value", ["-1", "101", "50.5", "nan", "25", "0", "двадцать"])
def test_invalid_or_regressing_progress_never_reaches_mutation(value):
    async def scenario():
        api, tg = CoursePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update(callback=f"progress:{CID}"))
        await bot.handle_update(update(value, number=2))
        assert (
            not mutations(api) and bot.sessions[USER].flow["step"] == "course_progress"
        )

    run(scenario())


@pytest.mark.parametrize("variant", ["internal", "unassigned", "completed"])
def test_progress_entry_rechecks_course_type_assignment_and_completion(variant):
    async def scenario():
        api, tg = CoursePortal(), FakeTelegram()
        if variant == "internal":
            api.course["course_type"] = "internal"
        elif variant == "unassigned":
            api.course["assignment"] = None
        else:
            api.course["assignment"].update(status="completed", progress_percent=100)
        bot = Bot(api, tg)
        await bot.handle_update(update(callback=f"progress:{CID}"))
        assert bot.sessions[USER].flow is None and not mutations(api)

    run(scenario())


@pytest.mark.parametrize("action", ["quiz", "material"])
def test_old_external_course_buttons_show_current_course_instead_of_dead_end(action):
    async def scenario():
        api, tg = CoursePortal(), FakeTelegram()
        await Bot(api, tg).handle_update(update(callback=f"{action}:{CID}"))
        assert "Яндекс Практикум" in tg.messages[-1][1]
        assert not mutations(api)

    run(scenario())


@pytest.mark.parametrize("scope", ["mine", "review"])
def test_review_inbox_uses_the_same_pending_filter_as_portal(scope):
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        await Bot(api, tg).handle_update(update(callback=f"requests:{scope}:10"))
        params = next(call[3]["params"] for call in api.calls if call[1] == "/requests")
        assert params == {
            "scope": scope,
            "limit": 10,
            "offset": 10,
            **({"status": "pending"} if scope == "review" else {}),
        }

    run(scenario())


@pytest.mark.parametrize("role", ["hr_admin", "director", "manager"])
def test_pending_card_names_actual_approver_instead_of_assuming_manager(role):
    async def scenario():
        api, tg = FakePortal(), FakeTelegram()
        api.result["approvers"] = [
            {"full_name": "Назначенный согласующий", "role": role}
        ]
        await Bot(api, tg).handle_update(update(callback=f"request:{RID}"))
        text = tg.messages[-1][1]
        assert "Ждёт решения" in text and "Согласует: Назначенный согласующий" in text
        assert "У руководителя" not in text

    run(scenario())


class AnswerPortal(FakePortal):
    def __init__(self, answer):
        super().__init__()
        self.answer = {"answer": "Ответ по базе знаний", "sources": [], **answer}

    async def request(self, method, path, user_id=None, **kwargs):
        if path == "/ai/ask":
            self.calls.append((method, path, user_id, kwargs))
            return self.answer
        return await super().request(method, path, user_id, **kwargs)


@pytest.mark.parametrize("action_id", list(JANA_CALLBACKS))
def test_jana_actions_use_known_callbacks_and_ignore_untrusted_links_and_labels(
    action_id,
):
    async def scenario():
        api, tg = (
            AnswerPortal(
                {
                    "actions": [
                        {
                            "id": action_id,
                            "label": "Злой текст",
                            "href": "https://evil.invalid",
                        },
                        {"id": action_id},
                        {"id": "unknown", "href": "https://evil.invalid"},
                    ]
                }
            ),
            FakeTelegram(),
        )
        await Bot(api, tg).handle_update(update("Как это сделать?"))
        matches = [
            item
            for item in buttons(tg)
            if item.get("callback_data") == JANA_CALLBACKS[action_id]
        ]
        assert len(matches) == 1 and matches[0]["text"] != "Злой текст"
        assert not any("url" in item or "web_app" in item for item in buttons(tg))
        assert not any(
            "unknown" in item.get("callback_data", "") for item in buttons(tg)
        )
        assert all(call[1] == "/ai/ask" for call in mutations(api))

    run(scenario())


def test_kazakh_question_uses_kazakh_language_and_action_captions():
    async def scenario():
        api, tg = (
            AnswerPortal(
                {
                    "actions": [
                        {"id": "leave_new", "label": KAZAKH_ACTION_LABELS["leave_new"]}
                    ],
                    "sources": [{"id": CID, "title": "Ереже"}],
                }
            ),
            FakeTelegram(),
        )
        await Bot(api, tg).handle_update(update("Демалысты қалай рәсімдеуге болады?"))
        assert (
            next(call[3]["language"] for call in api.calls if call[1] == "/ai/ask")
            == "kk"
        )
        assert any(
            item["text"] == KAZAKH_ACTION_LABELS["leave_new"] for item in buttons(tg)
        )
        assert any(item["text"].startswith("Дереккөз") for item in buttons(tg))
        assert any(item["text"] == "HR-ға сұрақ қою" for item in buttons(tg))
        assert "Сәл күте тұрыңыз" in tg.messages[0][1]

    run(scenario())


def test_summary_displays_scoped_facts_counts_and_bounded_navigation():
    async def scenario():
        report = {
            "sections": [
                {
                    "title": "Ждут вашего решения",
                    "count": 12,
                    "href": "/requests?scope=review",
                    "items": [
                        {
                            "label": f"Сотрудник {i} · отпуск",
                            "href": "https://evil.invalid",
                        }
                        for i in range(10)
                    ],
                },
                {
                    "title": "Просрочено обучение",
                    "count": 0,
                    "href": "/academy?tab=team",
                    "items": [],
                },
            ]
        }
        api, tg = AnswerPortal({"mode": "summary", "report": report}), FakeTelegram()
        await Bot(api, tg).handle_update(update("Что требует внимания?"))
        text = tg.messages[-1][1]
        assert "Ждут вашего решения: 12" in text and "Сотрудник 7 · отпуск" in text
        assert "Сотрудник 8" not in text and "Ещё 4 — в портале." in text
        assert "Просрочено обучение: 0" in text and "evil.invalid" not in text
        assert any(
            item.get("callback_data") == "requests:review:0" for item in buttons(tg)
        )
        assert not any("url" in item for item in buttons(tg))

    run(scenario())


@pytest.mark.parametrize(
    "navigation",
    ["menu", "courses:0", f"course:{CID}", "profile", "requests:mine:0", "ask"],
)
def test_navigation_cancels_progress_input_without_saving(navigation):
    async def scenario():
        api, tg = CoursePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update(callback=f"progress:{CID}"))
        await bot.handle_update(update(callback=navigation, number=2))
        assert bot.sessions[USER].flow is None and not mutations(api)

    run(scenario())


def test_cancel_invalidates_pending_progress_confirmation():
    async def scenario():
        api, tg = CoursePortal(), FakeTelegram()
        bot = Bot(api, tg)
        await bot.handle_update(update(callback=f"progress:{CID}"))
        await bot.handle_update(update("100", number=2))
        confirm = button(tg)
        await bot.handle_update(update("/cancel", number=3))
        await bot.handle_update(update(callback=confirm, number=4))
        assert not mutations(api)

    run(scenario())


@pytest.mark.parametrize("denied", [False, True])
def test_reviewer_sees_author_or_safe_identifier_when_profile_is_not_accessible(denied):
    class PeoplePortal(FakePortal):
        async def request(self, method, path, user_id=None, **kwargs):
            if path == "/team":
                return (
                    []
                    if denied
                    else [{"id": "other-employee", "full_name": "Алия Серикова"}]
                )
            if path == "/employees/other-employee":
                if denied:
                    raise RemoteError("Portal", 403)
                return {"id": "other-employee", "full_name": "Алия Серикова"}
            return await super().request(method, path, user_id, **kwargs)

    async def scenario():
        api, tg = PeoplePortal(), FakeTelegram()
        api.role = "manager"
        api.result["employee_id"] = "other-employee"
        bot = Bot(api, tg)
        expected = "ID other-em" if denied else "Алия Серикова"
        await bot.handle_update(update(callback="requests:review:0"))
        assert any(expected in item["text"] for item in buttons(tg))
        await bot.handle_update(update(callback=f"request:{RID}", number=2))
        assert f"Сотрудник: {expected}" in tg.messages[-1][1]
        assert any(
            item.get("callback_data") == f"approve:{RID}" for item in buttons(tg)
        )

    run(scenario())


def test_kazakh_summary_localizes_generated_navigation_and_handles_malformed_items():
    async def scenario():
        report = {
            "sections": [
                {
                    "title": "Заявки",
                    "count": 1,
                    "href": "/requests",
                    "items": {"unexpected": "value"},
                }
            ]
        }
        api, tg = AnswerPortal({"mode": "summary", "report": report}), FakeTelegram()
        await Bot(api, tg).handle_update(update("Менің міндеттерім"))
        assert "Заявки: 1" in tg.messages[-1][1]
        assert any(
            item["text"] == KAZAKH_ACTION_LABELS["requests_mine"]
            for item in buttons(tg)
        )

    run(scenario())
