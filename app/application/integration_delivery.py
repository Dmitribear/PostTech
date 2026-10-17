from app.application.dependencies import dependencies


def configuration(destination: str):
    return dependencies().integrations.configuration(destination)


def configured_destinations() -> dict[str, bool]:
    return dependencies().integrations.configured_destinations()
