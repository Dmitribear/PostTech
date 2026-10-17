from app.application.dependencies import dependencies


def configured() -> bool:
    return dependencies().mail.configured()


def send(invitation: dict, code: str, token_hash: str) -> str:
    return dependencies().mail.send(invitation, code, token_hash)
