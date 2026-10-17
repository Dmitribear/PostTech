from app.application.dependencies import Dependencies, configure
from app.infrastructure import integrations, invitation_email
from app.infrastructure.database.gateway import SupabaseGateway


def configure_application() -> None:
    configure(
        Dependencies(
            data=SupabaseGateway, mail=invitation_email, integrations=integrations
        )
    )
