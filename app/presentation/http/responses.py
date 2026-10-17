from fastapi.responses import Response

from app.application.ports import FileResult


def render_result(result):
    if isinstance(result, FileResult):
        return Response(
            result.content, media_type=result.media_type, headers=result.headers
        )
    return result
