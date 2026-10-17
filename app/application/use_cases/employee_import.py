"""Bounded CSV/XLSX parsing; preview never writes profiles or sends emails."""

import base64
import binascii
import csv
import io
import re
import secrets
import zipfile
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.application.use_cases.academy import (
    data_gateway,
    execute_command,
    execute_query,
    read_all_rows,
)
from app.application.use_cases.invitations import code_hash
from app.domain.errors import ApplicationError

HEADERS = [
    "employee_code",
    "full_name",
    "email",
    "company",
    "job_title",
    "department",
    "hired_at",
    "role",
    "manager_email",
]
ALIASES = dict(
    zip(
        [
            "табельный номер",
            "фио",
            "почта",
            "компания",
            "должность",
            "подразделение",
            "дата приёма",
            "роль",
            "почта руководителя",
        ],
        HEADERS,
    )
)
LIMIT = 2 * 1024 * 1024


class ImportRow(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    employee_code: str = Field(min_length=1, max_length=80)
    full_name: str = Field(min_length=3, max_length=200)
    email: str = Field(
        min_length=5, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    )
    company: str = Field(min_length=1, max_length=120)
    job_title: str = Field(min_length=1, max_length=160)
    department: str = Field(min_length=1, max_length=160)
    hired_at: date
    role: str = "worker"
    manager_email: str = ""


def parse_file(filename: str, content: str) -> list[dict]:
    try:
        raw = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ApplicationError(422, "Файл повреждён") from exc
    if len(raw) > LIMIT:
        raise ApplicationError(422, "Максимальный размер файла — 2 МБ")
    suffix = filename.rsplit(".", 1)[-1].lower()
    try:
        if suffix == "csv":
            stream = raw.decode("utf-8-sig")
            delimiter = (
                ";"
                if stream.splitlines()[0].count(";") > stream.splitlines()[0].count(",")
                else ","
            )
            rows = csv.reader(io.StringIO(stream), delimiter=delimiter)
            values = []
            for row in rows:
                if len(values) > 500:
                    raise ApplicationError(
                        422, "Не более 500 сотрудников за один импорт"
                    )
                values.append(row)
        elif suffix == "xlsx":
            # Reject compressed bombs before openpyxl/defusedxml reads the archive.
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if (
                    len(archive.infolist()) > 200
                    or sum(x.file_size for x in archive.infolist()) > 15 * 1024 * 1024
                ):
                    raise ApplicationError(
                        422, "Слишком большой распакованный Excel-файл"
                    )
                from defusedxml.ElementTree import iterparse

                for name in archive.namelist():
                    if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                        with archive.open(name) as xml:
                            for _, node in iterparse(xml, events=("end",)):
                                if node.tag.endswith("}c"):
                                    match = re.fullmatch(
                                        r"([A-Z]+)([0-9]+)", node.get("r", "")
                                    )
                                    if (
                                        not match
                                        or len(match[1]) != 1
                                        or match[1] > "I"
                                        or not 1 <= int(match[2]) <= 501
                                    ):
                                        raise ApplicationError(
                                            422,
                                            "Не более 500 строк и 9 столбцов. Удалите лишние ячейки",
                                        )
                                node.clear()
            from openpyxl import load_workbook

            book = load_workbook(
                io.BytesIO(raw), read_only=True, data_only=False, keep_links=False
            )
            try:
                if len(book.worksheets) != 1:
                    raise ApplicationError(422, "Оставьте один лист с сотрудниками")
                sheet = book.worksheets[0]
                sheet.reset_dimensions()  # Do not trust user-supplied worksheet dimensions.
                values = []
                for row in sheet.iter_rows():
                    if len(values) > 500 or len(row) > len(HEADERS):
                        raise ApplicationError(422, "Не более 500 строк и 9 столбцов")
                    if any(cell.data_type == "f" for cell in row):
                        raise ApplicationError(
                            422, "Замените формулы значениями перед импортом"
                        )
                    values.append([cell.value for cell in row])
            finally:
                book.close()
        else:
            raise ApplicationError(422, "Поддерживаются CSV UTF-8 и XLSX")
    except ApplicationError:
        raise
    except Exception as exc:
        raise ApplicationError(
            422, "Не удалось прочитать файл. Используйте шаблон CSV UTF-8 или XLSX"
        ) from exc
    if not values or len(values) < 2:
        raise ApplicationError(422, "Файл не содержит сотрудников")
    headers = [
        ALIASES.get(str(x or "").strip().lower(), str(x or "").strip().lower())
        for x in values[0]
    ]
    if (
        len(headers) != len(set(headers))
        or set(headers) - set(HEADERS)
        or set(HEADERS[:7]) - set(headers)
    ):
        raise ApplicationError(
            422, "Заголовки не совпадают с шаблоном. Первые семь столбцов обязательны"
        )
    result = []
    for number, values_row in enumerate(values[1:], 2):
        if not any(x is not None and str(x).strip() for x in values_row):
            continue
        if len(values_row) > len(headers):
            raise ApplicationError(422, f"Строка {number}: лишние столбцы")
        converted = {}
        for header, value in zip(headers, values_row):
            if header == "employee_code" and not isinstance(value, str):
                raise ApplicationError(
                    422, f"Строка {number}: табельный номер должен быть текстом"
                )
            if isinstance(value, (date, datetime)):
                value = (
                    value.date().isoformat()
                    if isinstance(value, datetime)
                    else value.isoformat()
                )
            converted[header] = str(value).strip() if value is not None else ""
        result.append({"line": number, "data": converted})
    if not result:
        raise ApplicationError(422, "Файл не содержит сотрудников")
    return result


def build_preview(
    source: list[dict], profiles: list[dict], invitations: list[dict]
) -> tuple[list, list]:
    by_code = {p["employee_code"]: p for p in profiles}
    by_email = {p["email"].lower(): p for p in profiles}
    invites = {i["email"].lower() for i in invitations} | {
        i["employee_code"] for i in invitations
    }
    seen_codes, seen_emails, rows, errors = set(), set(), [], []
    for source_row in source:
        number, data = source_row["line"], source_row["data"]
        try:
            parsed = ImportRow.model_validate(data).model_dump(mode="json")
            parsed["email"] = parsed["email"].lower()
            parsed["manager_email"] = parsed["manager_email"].lower()
            if parsed["role"] not in ("worker", "manager", "director", "hr_admin"):
                raise ValueError("Роль: worker, manager или hr_admin")
            code, email = parsed["employee_code"], parsed["email"]
            if code in seen_codes or email in seen_emails:
                raise ValueError("Повтор почты или табельного номера в файле")
            seen_codes.add(code)
            seen_emails.add(email)
            existing = by_code.get(code)
            manager = (
                by_email.get(parsed["manager_email"])
                if parsed["manager_email"]
                else None
            )
            if parsed["manager_email"] and (
                not manager
                or manager["role"] not in ("manager", "director", "hr_admin")
            ):
                raise ValueError(
                    "Руководитель должен иметь активный профиль. Сначала пригласите руководителя"
                )
            parsed["manager_id"] = manager["id"] if manager else None
            if existing:
                if (
                    existing["email"].lower() != email
                    or by_email.get(email, {}).get("id") != existing["id"]
                ):
                    raise ValueError(
                        "Почта и табельный номер относятся к разным профилям"
                    )
                if (
                    existing["role"] != parsed["role"]
                    or existing.get("manager_id") != parsed["manager_id"]
                ):
                    raise ValueError(
                        "Импорт не меняет роль и руководителя существующего сотрудника"
                    )
                fields = ["full_name", "company", "job_title", "department", "hired_at"]
                changed = [
                    {"field": k, "before": existing[k], "after": parsed[k]}
                    for k in fields
                    if str(existing[k]) != str(parsed[k])
                ]
                rows.append(
                    {
                        **parsed,
                        "line": number,
                        "action": "update" if changed else "unchanged",
                        "changes": changed,
                        "profile_id": existing["id"],
                        "expected_updated_at": existing["updated_at"],
                    }
                )
            else:
                if email in by_email or email in invites or code in invites:
                    raise ValueError(
                        "Уже существует профиль или действующее приглашение"
                    )
                if parsed["role"] == "hr_admin":
                    raise ValueError(
                        "HR-доступ выдаётся отдельным приглашением, а не массовым импортом"
                    )
                rows.append(
                    {
                        **parsed,
                        "line": number,
                        "action": "invite",
                        "changes": [],
                        "vacation_days_remaining": 0,
                    }
                )
        except ValidationError as exc:
            errors.append(
                {
                    "line": number,
                    "message": "Проверьте поля: "
                    + ", ".join(str(e["loc"][0]) for e in exc.errors()),
                }
            )
        except ValueError as exc:
            errors.append({"line": number, "message": str(exc)})
    return rows, errors


def preview(actor, filename, content):
    source = parse_file(filename, content)
    profiles = read_all_rows(
        lambda: (
            data_gateway()
            .table("employee_profiles")
            .select(
                "id,employee_code,full_name,email,company,job_title,department,hired_at,role,manager_id,updated_at"
            )
            .order("id")
        )
    )
    invitations = read_all_rows(
        lambda: (
            data_gateway()
            .table("registration_invitations")
            .select("email,employee_code,consumed_at,revoked_at,expires_at,id")
            .is_("consumed_at", "null")
            .is_("revoked_at", "null")
            .order("id")
        )
    )
    active = [
        i
        for i in invitations
        if not i.get("consumed_at")
        and not i.get("revoked_at")
        and datetime.fromisoformat(i["expires_at"].replace("Z", "+00:00")).timestamp()
        > datetime.now().timestamp()
    ]
    rows, errors = build_preview(source, profiles, active)
    return execute_query(
        data_gateway()
        .table("employee_imports")
        .insert(
            {
                "created_by": actor.id,
                "filename": filename,
                "rows": rows,
                "errors": errors,
            }
        )
    )[0]


def apply(actor, batch_id):
    batches = execute_query(
        data_gateway()
        .table("employee_imports")
        .select("rows")
        .eq("id", str(batch_id))
        .eq("created_by", actor.id)
        .limit(1)
    )
    if not batches:
        raise ApplicationError(404, "Предпросмотр не найден")
    codes = {
        row["employee_code"]: "JP-" + secrets.token_urlsafe(24)
        for row in batches[0]["rows"]
        if row["action"] == "invite"
    }
    result = execute_command(
        "apply_employee_import",
        {
            "p_actor_id": actor.id,
            "p_id": str(batch_id),
            "p_hashes": {k: code_hash(v) for k, v in codes.items()},
        },
    )
    if not result.get("already_applied"):
        result["invitations"] = [
            {**i, "invitation_code": codes[i["employee_code"]]}
            for i in result["invitations"]
        ]
    return result
