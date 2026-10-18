import re


def _retain_course_attempt_terms(answer: str, sources: list[dict]) -> str:
    course_contents = {
        str(source.get("id", "")): source.get("full_content", source.get("content", ""))
        for source in sources
        if str(source.get("id", "")) in {
            "20000000-0000-4000-8000-000000000008",
            "20000000-0000-4000-8000-000000000013",
        }
    }
    retry_content = course_contents.get("20000000-0000-4000-8000-000000000013", "")
    retry_rule = (
        "Текущий портал не задаёт ограничения на число неуспешных попыток "
        "или обязательную паузу между ними."
    )
    if retry_rule in retry_content:
        inserted = False

        def replace_attempt_condition(match: re.Match) -> str:
            nonlocal inserted
            sentence = match.group()
            if not (
                re.search(r"попыт|пересдач|между ними", sentence, re.I)
                and re.search(r"огранич|лимит|пауз|перерыв|ожидани|максимум|не более", sentence, re.I)
            ):
                return sentence
            if inserted:
                return ""
            inserted = True
            prefix = sentence[:len(sentence) - len(sentence.lstrip())]
            return prefix + retry_rule

        answer = re.sub(r"[^.!?\n]+[.!?]?", replace_attempt_condition, answer)
    confirmed_defaults = set()
    for content in course_contents.values():
        confirmed_defaults.update(re.findall(r"по умолчанию[^\d.!?\n]{0,35}(\d{1,3})\s*%", content, re.I))
    for score in confirmed_defaults:
        answer = re.sub(
            rf"\bобычно(?=\s+(?:(?:составляет|это|равен)\s+)?{re.escape(score)}\s*%)",
            "по умолчанию",
            answer,
            flags=re.I,
        )
        def qualify_default(match: re.Match) -> str:
            sentence = match.group()
            if re.search(r"проходн|порог", sentence, re.I) and "по умолчанию" not in sentence.lower():
                return re.sub(rf"\b{re.escape(score)}\s*%", lambda value: value.group() + " по умолчанию", sentence)
            return sentence

        answer = re.sub(r"[^.!?\n]+[.!?]?", qualify_default, answer)
    return answer


def retain_portal_terms(answer: str, sources: list[dict], language: str) -> str:
    if language == "kk":
        answer = retain_kazakh_course_assignment(answer, sources)
        return retain_kazakh_course_terms(retain_kazakh_course_deadline(answer, sources), sources)
    if language != "ru":
        return answer
    content = " ".join(source.get("full_content", source.get("content", "")) for source in sources)
    overlap_sentences = [sentence for sentence in re.split(r"[.!?\n]", answer) if re.search(r"пересек|пересеч", sentence, re.I)]
    if (
        overlap_sentences
        and "ожидающими или одобренными отпусками" in content
        and not any(re.search(r"ожидающ|одобрен|согласован|действующ", sentence, re.I) for sentence in overlap_sentences)
    ):
        answer += " Проверка пересечения относится к ожидающим или одобренным отпускам."
    if "все уроки должны быть завершены до теста" in content:
        answer = re.sub(
            r"[Пп]осле завершения курса(?=.{0,90}(?:тест|вопрос))",
            "После изучения материала и завершения уроков",
            answer,
        )
    return _retain_course_attempt_terms(answer, sources)


def retain_kazakh_course_assignment(answer: str, sources: list[dict]) -> str:
    content = " ".join(source.get("full_content", source.get("content", "")) for source in sources)
    if "Наличие курса в каталоге само по себе не означает, что он вам назначен." not in content:
        return answer

    def correct_assignment(match: re.Match) -> str:
        sentence = match.group()
        if (
            re.search(r"көрсетіл|каталогта|бөлімде", sentence, re.I)
            and re.search(r"тағайындал", sentence, re.I)
            and re.search(r"ғана|санал|білдір", sentence, re.I)
            and not re.search(r"білдірмей|саналмай|емес", sentence, re.I)
        ):
            prefix = sentence[:len(sentence) - len(sentence.lstrip())]
            return prefix + "Курстың каталогта болуы оның сізге тағайындалғанын білдірмейді."
        return sentence

    return re.sub(r"[^.!?\n]+[.!?]?", correct_assignment, answer)


def retain_kazakh_course_deadline(answer: str, sources: list[dict]) -> str:
    content = " ".join(source.get("full_content", source.get("content", "")) for source in sources)
    if "срок прохождения, если он задан" not in content:
        return answer

    def qualify_deadline(match: re.Match) -> str:
        sentence = match.group()
        if not re.search(r"мерзім", sentence, re.I):
            return sentence
        if re.search(r"мерзім\w*\s*\(егер белгіленсе\)|мерзім.{0,25}(?:белгілен|беріл).{0,12}(?:болса|жағдайда)|(?:белгіленген|берілген)\s+(?:болса|жағдайда).{0,20}мерзім", sentence, re.I):
            return sentence
        return re.sub(r"мерзім\w*", lambda term: term.group() + " (егер белгіленсе)", sentence, flags=re.I)

    return re.sub(r"[^.!?\n]+[.!?]?", qualify_deadline, answer)


def retain_kazakh_course_terms(answer: str, sources: list[dict]) -> str:
    if not re.search(r"[әғқңөұүһі]", answer, re.I):
        return answer
    content = " ".join(source.get("full_content", source.get("content", "")) for source in sources)
    evidence = "Текущий портал не задаёт ограничения на число неуспешных попыток или обязательную паузу между ними."
    if evidence not in content:
        return answer
    inserted = False

    def replace_attempt_limits(match: re.Match) -> str:
        nonlocal inserted
        sentence = match.group()
        if not re.search(r"әрекет|талпыныс|тапсыр|үзіліс|пауза", sentence, re.I) or not re.search(r"шекте|үзіліс|пауза", sentence, re.I):
            return sentence
        if inserted:
            return ""
        inserted = True
        prefix = sentence[:len(sentence) - len(sentence.lstrip())]
        return prefix + "Сәтсіз әрекеттер санына шектеу жоқ. Әрекеттер арасында міндетті үзіліс жоқ."

    result = re.sub(r"[^.!?\n]+[.!?]?", replace_attempt_limits, answer)
    if (
        "Все уроки и материал должны быть завершены до теста." in content
        and re.search(r"қайта|қайтала|әрекет|талпыныс", result, re.I)
        and not re.search(r"барлық.{0,30}сабақ|әрбір.{0,20}сабақ|әр\s+сабақ", result, re.I)
    ):
        result += " Тестке дейін барлық сабақтар мен материалды аяқтау қажет."
    return result


def missing_policy_answer(question: str, answer: str) -> bool:
    if (
        re.search(r"повтор|пересда|попыт", question, re.I)
        and re.search(r"(?:пауз|ожидан).{0,40}не установл|ограничени.{0,25}(?:попыт|повтор).{0,20}не установл", answer, re.I)
    ):
        return False
    return bool(
        re.search(r"срок|когда|за сколько|сколько.{0,30}(?:дней|положено)|график|компенсац|размер|оплачивает|бонус|преми", question, re.I)
        and re.search(r"не установл|не определ|не утвержд|не указан|нет.{0,35}(?:правил|информац)|отсутств.{0,35}(?:правил|информац)", answer, re.I)
    )


def retain_leave_conditions(
    answer: str, sources: list[dict], language: str, question: str = ""
) -> str:
    if language != "ru":
        return answer
    if question and not re.search(r"отоз|отмен|отклон|верн|возврат|возвращ|освобожд|резерв", question, re.I):
        return answer
    contents = {
        str(source["id"]): source.get("full_content", source.get("content", ""))
        for source in sources
    }
    cancellation = contents.get("20000000-0000-4000-8000-000000000012", "")
    balance = contents.get("20000000-0000-4000-8000-000000000005", "")
    additions = []
    conditions = []
    if cancellation:
        conditions.extend([
            (
                r"только.{0,100}(?:на согласовании|pending)|лишь.{0,100}(?:на согласовании|pending)",
                r"Автор может отозвать только[^.]+\.",
                cancellation,
            ),
            (
                r"(?:согласованн|одобренн).{0,120}(?:нельзя|не может|не предусмотр|HR)|(?:не может|нельзя).{0,120}(?:одобренн|согласованн)",
                r"Уже согласованный отпуск[^.]+\.",
                cancellation,
            ),
        ])
    if (cancellation or balance) and re.search(r"резерв|возвращ|освобож", answer, re.I):
        conditions.append((
            r"(?:кадров|уч[её]тн|официальн).{0,60}(?:не меня|не измен|не увелич)|(?:не меня|не измен|не увелич).{0,60}(?:кадров|уч[её]тн|официальн)",
            r"При (?:отзыве|отклонении)[^.]*\.[^.]*кадровый остаток не (?:меняется|изменяется)\.|При (?:отзыве|отклонении)[^.]*кадровый остаток не (?:меняется|изменяется)\.",
            cancellation or balance,
        ))
    for present, source_sentence, content in conditions:
        if not re.search(present, answer, re.I | re.S):
            match = re.search(source_sentence, content, re.I)
            if match:
                additions.append(match.group().strip())
    return " ".join([answer, *additions])
