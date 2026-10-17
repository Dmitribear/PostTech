from collections.abc import Callable
from dataclasses import dataclass

from app.application.ports import DataGateway, IntegrationDelivery, InvitationSender


@dataclass(frozen=True)
class Dependencies:
    data: Callable[[], DataGateway]
    mail: InvitationSender
    integrations: IntegrationDelivery


_dependencies: Dependencies | None = None


def configure(dependencies: Dependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def dependencies() -> Dependencies:
    if _dependencies is None:
        raise RuntimeError("Application dependencies have not been configured")
    return _dependencies


def get_data_gateway() -> DataGateway:
    return dependencies().data()
