"""Text-only scope checks before FAQ retrieval; no model, storage or actions."""

import re

_UNKNOWN = "В базе нет подтверждённого ответа. Уточните у HR."
_RESTRICTED_REASON = (
    "Я отвечаю по общей базе знаний. Личные данные и действия с заявками "
    "доступны в соответствующих разделах платформы."
)
_CALENDAR_REASON = (
    "Файл календаря доступен только в карточке одобренной заявки на отпуск."
)

# Preserve the existing checks and their order. These are scope checks, not a
# claim that a matching request could otherwise perform a database mutation.
_RESTRICTED = re.compile(
    r"(?:игнорируй|забудь|ignore|disregard).{0,100}(?:инструк|правил|system|previous)"
    r"|(?:придумай|выдумай|сочини).{0,80}(?:правил|политик|ответ|срок)"
    r"|(?:одобри|отклони|измени|назначь|удали|отмени|убери|оформи|отправь|создай|запиши|переведи|исправь|добавь|напомни|approve|delete)\b"
    r"|(?:парол|токен|api.?key|system prompt|системн\w* промпт)"
    r"|(?:покажи|назови|скажи|узнай|выведи).{0,80}(?:зарплат|оклад|чуж|коллег|подчин)"
    r"|(?:сколько|какой|каков).{0,60}(?:у меня|мой|моя).{0,50}(?:зарплат|оклад)",
    re.I | re.S,
)
_QUESTION_PARTS = re.compile(
    r"\?\s*|\b(?:и|а также|а ещё|а еще|и ещё|и еще)\s+"
    r"(?=(?:какой|какая|какие|когда|сколько|кто|где|как|за сколько)\b)",
    re.I,
)
# A brief request to clarify the same question adds no second business intent.
# Keep the allowed vocabulary closed: another policy, amount or person cannot
# be hidden behind an unrestricted "не понимаю ..." exception.
_META_CLARIFICATION = re.compile(
    r"(?:я\s+)?(?:не\s+(?:пойму|понимаю|понял[а]?|разобрался|разобралась)"
    r"|запутался|запуталась|хочу\s+(?:понять|разобраться)|(?:объясни|подскажи|поясни)(?:те)?)"
    r"(?:[\s,]+(?:что|че|чё|как|это|здесь|тут|допустимо|правильно|нужно|сделать|работает"
    r"|пожалуйста|простыми|словами|в|этом|мне)){0,8}",
    re.I,
)
_FORM_NAVIGATION = re.compile(
    r"\b(?:какой|каком)\s+раздел|\b(?:где|куда)\b.{0,30}(?:откры|зайти|перейти|подать)"
    r"|\bкак\b.{0,35}(?:подать|оформить|запросить|отправить|создать)",
    re.I,
)
_FORM_FIELDS = re.compile(r"\bпол[яе]\b|данн|\bдат[уы]\b|сумм|комментар", re.I)
_FORM_FILL = re.compile(r"заполн|внест|указать|впис|ввести|ввод|задать|добав", re.I)
_OTHER_FORM_OBJECT = re.compile(
    r"профил|регистрац|аккаунт|уч[её]тн.{0,15}запис|курс|обучен|календар|событи", re.I
)
_UNSUPPORTED_QUALIFICATION = re.compile(
    r"за свой сч[её]т|неоплачиваем|без сохранения|испытательн|задним числом"
    r"|(?:без|обойти).{0,35}(?:соглас|разреш|одобрен|руковод|начальств)"
    r"|декрет|больнич|беремен|увольнен|компенсац|празднич|расписан|график"
    r"|(?:за|через|на|до|после)\s+(?:\d+|один|два|три|четыре|пять|шесть|семь|десять|несколько)\s+(?:дн|день|недел|месяц)"
    r"|(?:всей|полной|всю)\s+зарплат",
    re.I,
)
_REQUEST_ACTION = re.compile(
    r"\b(?:подать|подавать|подач[а-яё]*|оформить|оформлять|оформлени[а-яё]*"
    r"|отправить|отправлять|отправк[а-яё]*|создать|создавать|создани[а-яё]*)\b",
    re.I,
)
_REQUEST_NOUN = re.compile(r"заявк|заявлен", re.I)
_REQUEST_KIND = re.compile(r"отпуск|отдых|аванс", re.I)

# A second-person request followed by an action differs from asking for its
# procedure ("можешь объяснить, как мне отправить") or who has that authority.
_ACTION_INFINITIVE = (
    r"(?:отправить|подать|оформить|одобрить|отклонить|отменить|удалить|создать"
    r"|изменить|поменять|исправить|назначить|добавить|записать|перевести|напомнить)"
)
_DELEGATED_ACTION = re.compile(
    r"\b(?:можешь|можете|сможешь|сможете|могла?\s+бы|могли\s+бы)"
    r"(?:[\s,]+(?:ты|вы|мне|пожалуйста|сейчас|просто|сама|сам|сами|бы)){0,6}"
    r"[\s,]+" + _ACTION_INFINITIVE + r"\b"
    r"|\b(?:хочу|нужно|надо|прошу).{0,35}\bчтобы\s+(?:ты|вы)\b.{0,35}"
    r"(?:отправ|пода[лт]|оформ|одобр|отклон|отмен|удал|созда|измен|помен|исправ|назнач|добав|записа|переве)"
    r"|\b" + _ACTION_INFINITIVE + r"\b.{0,100}\b(?:за меня|вместо меня)\b",
    re.I | re.S,
)

_ADVANCE = re.compile(r"аванс", re.I)
_FEE = re.compile(r"комисси|\bсбор(?:а|ы|ов|ом|у)?\b|\bплатн", re.I)
_REPEAT = re.compile(
    r"повторн|\bснова\b|\bвтор(?:ой|ого|ую|ым)\b|дважды|ещ[её]\s+(?:один|раз)"
    r"|уже.{0,60}(?:получил|получал|выда[нл]|запросил|пода[лн])",
    re.I,
)
_ADVANCE_POLICY = re.compile(
    r"получить|запросить|оформить|подать|попросить|взять|выдадут|положен|разреш|можно|доступ[её]н",
    re.I,
)
_PROFILE = re.compile(r"профил|карточк|кадров.{0,15}данн", re.I)
_AUTOMATIC = re.compile(
    r"автоматич|автообнов|синхрониз|\bсам[аои]?\s+(?:измен|обнов|исправ)", re.I
)
_PROFILE_CHANGE = re.compile(r"измен|исправ|обнов|смен|синхрониз|помен|заполн", re.I)
_RESTORE_OR_APPEAL = re.compile(r"восстанов|обжал|оспор|апелляци", re.I)
_EDIT_ACTION = re.compile(
    r"\b(?:изменить|редактировать|отредактировать|исправить|поменять|перенести|отменить|отозвать|удалить)\b",
    re.I,
)
_OTHER_EDIT_TARGET = re.compile(r"календар|событи|профил|кадров", re.I)
_REQUEST_FIELD = re.compile(r"\bдат|сумм|коммент|\bтип\b|\bначал|окончан", re.I)
_SPECIAL_EMPLOYMENT = re.compile(
    r"совместительств|несовершеннолет|\bгпх\b|гражданско[ -]правов",
    re.I,
)
_LEAVE_PROCEDURE = re.compile(
    r"оформ|подать|запросить|взять|получить|положен|разреш|можно", re.I
)
_CONTACT_DETAILS = re.compile(
    r"\b(?:какой|какая|какую|какие|каким|куда|где)\b.{0,70}(?:почт|телефон|e[ -]?mail)"
    r"|(?:почт|телефон|e[ -]?mail).{0,35}\b(?:какой|какая|какую|какие|где)\b"
    r"|\b(?:назови|сообщи|укажи|пришли|дай|подскажи)\s+(?:мне\s+)?"
    r"(?:контактн[а-яё]*\s+)?(?:адрес|номер|почт|телефон|e[ -]?mail)"
    r"|\b(?:какой|какому|каком|какие)\b.{0,25}адрес.{0,50}(?:напис|отправ|обра|прос|заяв|кадр|hr)"
    r"|адрес.{0,30}(?:отдел[а-яё]*\s+кадр|кадров[а-яё]*\s+служб)"
    r"|(?:адрес|номер|телефон|e[ -]?mail).{0,25}\b(?:hr|эйчар|кадровик[а-яё]*)\b"
    r"|\b(?:hr|эйчар|кадровик[а-яё]*)\b.{0,25}(?:адрес|телефон|e[ -]?mail)",
    re.I,
)
_BALANCE_TOPIC = re.compile(r"отпуск|отдых|неиспользован|\bдн(?:и|ей)\b", re.I)
_PERSONAL_REFERENCE = re.compile(
    r"\b(?:у меня|мне|мой|моя|мо[её]|мои|моих|моего|моему|мо[её]й|мо[её]м|мою|моим|моими|за мной)\b",
    re.I,
)
_BALANCE_VALUE_REQUEST = re.compile(
    r"\b(?:сколько|каков[а-яё]*|какой|назови|покажи|скажи|сообщи|выведи|проверь|узнай)\b",
    re.I,
)
_BALANCE_NAVIGATION = re.compile(
    r"\b(?:где|куда|в каком разделе|в какой части|как)\s+"
    r"(?:(?:я могу|мне|можно|самостоятельно|сотруднику|в портале)\s+)?"
    r"(?:посмотреть|проверить|узнать|увидеть|найти|открыть|зайти)"
    r"|\bгде\b.{0,60}(?:отображ|указан|находит)"
    r"|\b(?:какой|каком)\s+раздел",
    re.I,
)
_DIRECT_BALANCE_REQUEST = re.compile(
    r"\b(?:назови|скажи|сообщи|выведи|проверь|узнай)\b[\s,]+"
    r"(?:(?:мне|пожалуйста|сейчас)\s+)*(?:сколько|мой|моя|мо[её]|мои|остаток|баланс)",
    re.I,
)
_OFFICIAL_FIELD = re.compile(
    r"\bимя\b|фамили|должност|руководител|начальник|дат.{0,15}при[её]м|подраздел|компани|организаци",
    re.I,
)
_PROFILE_VALUE_REQUEST = re.compile(
    r"\b(?:какое|какая|какой|каков[а-яё]*|кто|когда|назови|покажи|скажи|сообщи|выведи|проверь|узнай)\b"
    r"|как\s+зовут|что\s+указано",
    re.I,
)
_DIRECT_PROFILE_VALUE = re.compile(
    r"\b(?:назови|покажи|скажи|сообщи|выведи|проверь|узнай)\s+"
    r"(?:(?:мне|пожалуйста|мою|мой|мо[её]|текущ[а-яё]*|официальн[а-яё]*|полно[а-яё]*)\s+){0,5}"
    r"(?:имя|фамили|должност|руководител|начальник|дат[ау]|подраздел|компани|организаци)",
    re.I,
)
_PROFILE_CORRECTION = re.compile(
    r"исправ|измен|редактир|помен|ошиб|неверн|неправильн", re.I
)
_PROFILE_VISIBILITY = re.compile(
    r"\bкто\s+(?:(?:может|вправе)\s+)?(?:вид|просматр|читать|имеет|получает)"
    r"|(?:может|вправе).{0,45}(?:видеть|просматривать|читать)"
    r"|\bкакой\s+доступ\b|\bкакие\s+права\b",
    re.I,
)
_SUPPORTING_DOCUMENT = re.compile(r"документ|справк|подтверждающ.{0,20}бумаг", re.I)
_DOCUMENT_REQUIREMENT = re.compile(
    r"обязател|прилож|прикреп|требу|нужн|необходим|\bкакие\b", re.I
)
_SHARING = re.compile(
    r"поделить|переда|пересла|отправ|показ|\bдать.{0,60}доступ|предостав.{0,60}доступ",
    re.I,
)
_OUTSIDER = re.compile(
    r"внешн|подрядч|посторон|партн[её]р|контрагент|третьим|третьему|за предел", re.I
)
_CALENDAR = re.compile(r"календар|google|calendar|\bics\b|событи", re.I)
_OTHER_CALENDAR = re.compile(
    r"outlook|яндекс|yandex|apple|icloud|\bical\b|айклауд|аутлук", re.I
)
_NOT_APPROVED = re.compile(
    r"отклон|неодобр|не согласован|\b(?:pending|rejected)\b"
    r"|\bне\s+(?:(?:ещ[её]|пока|был[аои]?)\s+){0,3}(?:одобр|согласов|утвержд|рассмотр)"
    r"|решени.{0,40}отсутств|\bнет.{0,30}решени"
    r"|ожида.{0,25}(?:одобр|согласов|рассмотр)",
    re.I,
)
_REQUEST_OUTCOME = re.compile(
    r"статус|решени|(?:итог|результат).{0,25}рассмотр|рассмотрели|рассмотрен",
    re.I,
)
_COMMENT = re.compile(r"комментар", re.I)
_COMMENT_INPUT = re.compile(r"указать|добав|заполн|впис|напис|ввести|ввод", re.I)
_CALENDAR_SYNCHRONIZATION = re.compile(r"синхронизац|синхрониз", re.I)
_CALENDAR_AUTOMATIC = re.compile(
    r"автоматич|автообнов|автоизмен|автоудал|\bсам[аои]?\b|\bсами\b", re.I
)
_CALENDAR_CHANGE = re.compile(r"обнов|измен|удал|исчез|перенес|сдвин|отмен", re.I)
_IMPORTED_LEAVE = re.compile(
    r"импорт.{0,50}(?:отпуск|событи)|(?:отпуск|событи).{0,50}импорт", re.I
)
_INITIAL_IMPORT = re.compile(
    r"импортировать|загрузить|скачать|добавить|перенести|занести|взять.{0,15}файл|где.{0,20}файл",
    re.I,
)
_COURSE_TOPIC = re.compile(r"курс|обучен|учебн|academy|академ", re.I)
_COURSE_ASSIGNMENT = re.compile(
    r"назначить|назначать|назначает|назначают"
    r"|выдавать|выда[её]т|выдать|\bдать\b",
    re.I,
)
_COURSE_ASSIGNMENT_NOUN = re.compile(r"назначени[ея]|назначением|выдач", re.I)
_ASSIGNMENT_AUTHORITY = re.compile(
    r"\bкто\b|\bкем\b|у\s+кого|вправе|может|право|полномоч|руководител|начальник|\bhr\b|кадровик",
    re.I,
)
_COURSE_LOCATION = re.compile(
    r"\bгде\b|в\s+каком\s+(?:разделе|меню)|куда.{0,20}(?:зайти|перейти)"
    r"|как.{0,20}(?:найти|открыть|посмотреть)",
    re.I,
)
_ACCOUNT_SETUP = re.compile(r"регистрац|зарегистр|аккаунт|уч[её]тн.{0,12}запис", re.I)
_PROFILE_CREATION = re.compile(r"созда|появ|привяз|связ|отсутств", re.I)
_LEAVE_EXPORT = re.compile(
    r"\b(?:выгруз|экспорт|скач|файл)[а-яё]*.{0,40}отпуск|отпуск.{0,40}(?:выгруз|экспорт|скач|файл)",
    re.I,
)
_FORM_TARGETS = [
    re.compile(pattern, re.I)
    for pattern in (
        r"\b(?:оформ[а-яё]*|пода[а-яё]*|запрашив[а-яё]*|запрос[а-яё]*|созда[а-яё]*|отправ[а-яё]*)\s+"
        r"(?:(?:заявк|заявлен)[а-яё]*\s+на\s+)?(аванс|отпуск)[а-яё]*\b",
        r"\b(аванс|отпуск)[а-яё]*\s+(?:я\s+)?(?:оформ|пода|запраш|созда|отправ)[а-яё]*\b",
        r"\b(?:заявк|заявлен|форм)[а-яё]*\s+(?:на\s+)?(аванс|отпуск)[а-яё]*\b",
    )
]
_CURRENT_REQUEST_VALUE = re.compile(
    r"статус|решени|рассмотр|одобр|отклон|согласов", re.I
)
_CURRENT_REQUEST_ASK = re.compile(
    r"\b(?:какое|какой|каков[а-яё]*|когда|кто|что|назови|скажи|сообщи|выведи|проверь|узнай)\b"
    r"|(?:рассмотрели|одобрен[аыо]?)\s+ли",
    re.I,
)
_STATUS_DEFINITION = re.compile(r"означ|значит|расшифр|как\s+поним", re.I)
_VALUE_LOCATION = re.compile(
    r"\bгде\b|в\s+каком\s+(?:разделе|месте)|в\s+какой\s+(?:карточке|части)"
    r"|как\s+(?:мне\s+)?(?:проверить|узнать|посмотреть|увидеть)|куда\s+(?:зайти|перейти)",
    re.I,
)
_DIRECT_STATUS_VALUE = re.compile(
    r"\b(?:назови|скажи|сообщи|выведи|проверь|узнай)[\s,]+(?:мне\s+)?"
    r"(?:(?:текущ[а-яё]*|последн[а-яё]*|мой|мо[её])\s+)?(?:статус|решени|рассмотр|одобр)",
    re.I,
)
_PROFILE_DUMP = re.compile(
    r"\b(?:выведи|покажи|прочитай|перечисли|получи|загрузи|назови)\b", re.I
)
_REVIEWER_ROLE = re.compile(
    r"\bчьего\s+(?:рассмотрения|согласования|одобрения)"
    r"|\bкто\b.{0,40}(?:рассматрива|рассмотр[ие]т|согласовыва|согласует|одобряет)",
    re.I,
)
_CORRECTION_WAIT = re.compile(
    r"(?:через|за)\s+сколько|сколько.{0,20}(?:времен|дн|час|ждать)|\bкогда\b", re.I
)
_FUTURE_CORRECTION = re.compile(
    r"исправит|исправят|исправлени|изменит|изменят|обновит|обновят|поправит|поправят",
    re.I,
)


def _has_multiple_intents(question: str) -> bool:
    parts = [part.strip(" .!\t\r\n") for part in _QUESTION_PARTS.split(question)]
    parts = [part for part in parts if part]
    if len(parts) <= 1:
        return False
    parts = [
        parts[0],
        *(part for part in parts[1:] if not _META_CLARIFICATION.fullmatch(part)),
    ]
    if len(parts) == 1:
        return False
    # Opening the form and filling its fields are the same published procedure.
    # A different request type, payment deadline or another topic still fails.
    leave = bool(re.search(r"отпуск|отдых", question, re.I))
    advance = bool(_ADVANCE.search(question))
    one_form = leave != advance and all(
        (
            _FORM_NAVIGATION.search(part)
            or (_FORM_FIELDS.search(part) and _FORM_FILL.search(part))
        )
        and not (
            _FORM_FIELDS.search(part)
            and _FORM_FILL.search(part)
            and _OTHER_FORM_OBJECT.search(part)
        )
        for part in parts
    )
    return not one_form


def _edits_request(question: str) -> bool:
    """Do not substitute a submission guide for an unknown edit procedure.

    The first named object after the action distinguishes editing a request
    from editing a calendar event or profile mentioned in the same sentence.
    A status question about an edited/withdrawn request has no edit infinitive.
    """
    for action in _EDIT_ACTION.finditer(question):
        following = question[action.end() : action.end() + 100]
        request = _REQUEST_NOUN.search(following)
        other = _OTHER_EDIT_TARGET.search(following)
        if request and (other is None or request.start() < other.start()):
            return True
        preceding = question[max(0, action.start() - 100) : action.start()]
        if (
            other is None
            and _REQUEST_NOUN.search(preceding)
            and _REQUEST_FIELD.search(following)
        ):
            return True
    return False


def card_is_applicable(question: str, card_id: str) -> bool:
    """Reject a semantically related procedure that cannot answer the intent.

    This never chooses an answer or examines scores. Callers must preserve
    negative candidates, confidence checks and source validation; applicability
    is not a reason to substitute a different source after source validation fails.
    """
    if card_id in {"leave_apply", "advance_apply"}:
        targets = {
            match.group(1).casefold()
            for pattern in _FORM_TARGETS
            for match in pattern.finditer(question)
        }
        wanted = "отпуск" if card_id == "leave_apply" else "аванс"
        if targets and targets != {wanted}:
            return False
        if _REQUEST_NOUN.search(question):
            reviewer_role = (
                card_id == "leave_apply"
                and re.search(r"отпуск", question, re.I)
                and _REVIEWER_ROLE.search(question)
            )
            if _REQUEST_OUTCOME.search(question) and not reviewer_role:
                return False
            if _COMMENT.search(question) and not _COMMENT_INPUT.search(question):
                return False
    if card_id in {"calendar_import", "calendar_sync"} and not (
        _CALENDAR.search(question)
        or _IMPORTED_LEAVE.search(question)
        or _LEAVE_EXPORT.search(question)
    ):
        return False
    if card_id == "calendar_import":
        if _CALENDAR_SYNCHRONIZATION.search(question):
            return False
        if _CALENDAR_AUTOMATIC.search(question) and _CALENDAR_CHANGE.search(question):
            return False
    if (
        card_id == "calendar_sync"
        and _INITIAL_IMPORT.search(question)
        and not (
            _CALENDAR_CHANGE.search(question)
            or _CALENDAR_SYNCHRONIZATION.search(question)
            or _CALENDAR_AUTOMATIC.search(question)
        )
    ):
        return False
    if _COURSE_TOPIC.search(question):
        assignment = _COURSE_ASSIGNMENT.search(question) or (
            _COURSE_ASSIGNMENT_NOUN.search(question)
            and _ASSIGNMENT_AUTHORITY.search(question)
            and not _COURSE_LOCATION.search(question)
        )
        if card_id == "course_find" and assignment:
            return False
        if (
            card_id == "course_assign"
            and (
                _COURSE_LOCATION.search(question)
                or re.search(r"каталог|список", question, re.I)
            )
            and not assignment
        ):
            return False
    linking = (
        _ACCOUNT_SETUP.search(question)
        and _PROFILE_CREATION.search(question)
        and (_PROFILE.search(question) or re.search(r"\bрол[ьи]\b", question, re.I))
    )
    if (
        card_id == "profile_fix"
        and linking
        and not _PROFILE_CORRECTION.search(question)
    ):
        return False
    if (
        card_id == "profile_access"
        and _OFFICIAL_FIELD.search(question)
        and _PROFILE_CORRECTION.search(question)
        and not linking
    ):
        return False
    return True


def refusal_reason(question: str, *, clarify_request_kind: bool = True) -> str | None:
    """Return a short scope refusal, or let retrieval validate the question.

    ``None`` does not establish answerability. Similarity, competing matches,
    active sources and exact source fingerprints still have to be checked.
    Before typo normalization, only the missing-request-kind clarification may
    be deferred. Every safety/scope check still runs on the original text.
    """
    if _RESTRICTED.search(question):
        return _RESTRICTED_REASON
    if len(question) > 500 or _has_multiple_intents(question):
        return "Задайте один короткий вопрос, чтобы я мог подобрать точный ответ."
    if _UNSUPPORTED_QUALIFICATION.search(question):
        return _UNKNOWN
    if _DELEGATED_ACTION.search(question):
        return _RESTRICTED_REASON
    if (
        _OFFICIAL_FIELD.search(question)
        and _CORRECTION_WAIT.search(question)
        and _FUTURE_CORRECTION.search(question)
    ):
        return _UNKNOWN
    if (
        _REQUEST_NOUN.search(question)
        and _PERSONAL_REFERENCE.search(question)
        and _CURRENT_REQUEST_VALUE.search(question)
        and _CURRENT_REQUEST_ASK.search(question)
        and (
            _DIRECT_STATUS_VALUE.search(question)
            or not (
                _VALUE_LOCATION.search(question)
                or _STATUS_DEFINITION.search(question)
                or _REVIEWER_ROLE.search(question)
            )
        )
    ):
        return _RESTRICTED_REASON
    if (
        _PROFILE.search(question)
        and _PERSONAL_REFERENCE.search(question)
        and _PROFILE_DUMP.search(question)
        and not (
            _VALUE_LOCATION.search(question) or _PROFILE_CORRECTION.search(question)
        )
    ):
        return _RESTRICTED_REASON
    if (
        _BALANCE_TOPIC.search(question)
        and _PERSONAL_REFERENCE.search(question)
        and _BALANCE_VALUE_REQUEST.search(question)
        and (
            not _BALANCE_NAVIGATION.search(question)
            or _DIRECT_BALANCE_REQUEST.search(question)
        )
    ):
        return _RESTRICTED_REASON
    if _CONTACT_DETAILS.search(question):
        return _UNKNOWN
    if (
        _OFFICIAL_FIELD.search(question)
        and _PERSONAL_REFERENCE.search(question)
        and _PROFILE_VALUE_REQUEST.search(question)
        and (
            _DIRECT_PROFILE_VALUE.search(question)
            or not (
                _BALANCE_NAVIGATION.search(question)
                or _PROFILE_CORRECTION.search(question)
                or _PROFILE_VISIBILITY.search(question)
            )
        )
    ):
        return _RESTRICTED_REASON
    if (
        _SUPPORTING_DOCUMENT.search(question)
        and _DOCUMENT_REQUIREMENT.search(question)
        and (_REQUEST_NOUN.search(question) or _REQUEST_KIND.search(question))
    ):
        return _UNKNOWN
    if _ADVANCE.search(question) and (
        _FEE.search(question)
        or (_REPEAT.search(question) and _ADVANCE_POLICY.search(question))
    ):
        return _UNKNOWN
    if (
        _PROFILE.search(question)
        and _SHARING.search(question)
        and _OUTSIDER.search(question)
    ):
        return _UNKNOWN
    if (
        _PROFILE.search(question)
        and _AUTOMATIC.search(question)
        and _PROFILE_CHANGE.search(question)
    ):
        return _UNKNOWN
    if _REQUEST_NOUN.search(question) and (
        _RESTORE_OR_APPEAL.search(question) or _edits_request(question)
    ):
        return _UNKNOWN
    if (
        re.search(r"отпуск|отдых", question, re.I)
        and _SPECIAL_EMPLOYMENT.search(question)
        and _LEAVE_PROCEDURE.search(question)
    ):
        return _UNKNOWN
    if (
        clarify_request_kind
        and _REQUEST_ACTION.search(question)
        and _REQUEST_NOUN.search(question)
        and not _REQUEST_KIND.search(question)
    ):
        return "Уточните тип заявки: на отпуск или на аванс?"
    if _CALENDAR.search(question):
        if _NOT_APPROVED.search(question):
            return _CALENDAR_REASON
        if _OTHER_CALENDAR.search(question):
            return "В базе нет инструкции для этого календаря. Уточните у HR."
    return None
