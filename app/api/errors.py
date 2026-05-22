from fastapi.responses import JSONResponse


def build_error_payload(code: str, message: str, detail=None) -> dict:
    payload = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "detail": detail,
        },
    }
    if detail is not None:
        payload["detail"] = detail
    return payload


def error_response(status_code: int, code: str, message: str, detail=None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_error_payload(code=code, message=message, detail=detail),
    )
