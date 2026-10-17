from httpx import HTTPError
from postgrest.exceptions import APIError

from app.domain.errors import StorageError, StorageUnavailable
from app.infrastructure.database.client import get_supabase_client


class SupabaseQuery:
    def __init__(self, query):
        self._query = query

    def __getattr__(self, method):
        def apply(*args, **kwargs):
            return SupabaseQuery(getattr(self._query, method)(*args, **kwargs))

        return apply

    def execute(self):
        try:
            return self._query.execute()
        except APIError as error:
            raise StorageError(
                {"code": error.code, "message": error.message}
            ) from error
        except HTTPError as error:
            raise StorageUnavailable("Database transport unavailable") from error


class SupabaseGateway:
    def table(self, resource: str):
        return SupabaseQuery(get_supabase_client().table(resource))

    def rpc(self, operation: str, arguments: dict):
        return SupabaseQuery(get_supabase_client().rpc(operation, arguments))
