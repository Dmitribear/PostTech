class ApplicationError(Exception):
    def __init__(
        self, status_code: int, detail: str = "", headers: dict[str, str] | None = None
    ):
        self.status_code = status_code
        self.detail = detail
        self.headers = headers
        super().__init__(detail)


class StorageError(Exception):
    def __init__(self, error: dict):
        self.code = str(error.get("code", "unknown"))
        self.message = str(error.get("message", "Storage operation failed"))
        super().__init__(self.message)


class StorageUnavailable(Exception):
    pass
