"""This module provides the FastAPI API definition."""

from doc.config import settings
from doc.domain import exceptions
from doc.entrypoints.routes import router as doc_router
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from passages.entrypoints.routes import router as passages_router
from stet.entrypoints.routes import router as stet_router

app = FastAPI()


logger = settings.logger(__name__)

# CORS configuration to allow frontend to talk to backend
origins = settings.BACKEND_CORS_ORIGINS

logger.debug("CORS origins: %s", origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(exceptions.InvalidDocumentRequestException)
def invalid_document_request_exception_handler(
    request: Request, exc: exceptions.InvalidDocumentRequestException
) -> JSONResponse:
    logger.error(f"{request}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "message": f"{exc.message}",
        },
    )


@app.exception_handler(exceptions.ResourceAssetFileNotFoundError)
def resource_asset_file_not_found_exception_handler(
    request: Request, exc: exceptions.ResourceAssetFileNotFoundError
) -> JSONResponse:
    logger.error(f"{request}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "message": f"{exc.message}",
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    exc_str = f"{exc}".replace("\n", " ").replace("   ", " ")
    logger.error(f"{request}: {exc_str}")
    content = {"status_code": 10422, "message": exc_str, "data": None}
    return JSONResponse(
        content=content, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )


CLONE_CONTENTION_RETRY_AFTER_SECONDS = 30  # tune to your typical clone duration


@app.exception_handler(exceptions.AssetCloneContentionTimeout)
async def clone_contention_timeout_handler(
    request: Request, exc: exceptions.AssetCloneContentionTimeout
) -> JSONResponse:
    # The details are already logged at the raise site. Don't send server
    # file paths to the client.
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": str(CLONE_CONTENTION_RETRY_AFTER_SECONDS)},
        content={
            "detail": "Required resources are still being prepared by another "
            "request. Please retry shortly."
        },
    )


app.include_router(doc_router)
app.include_router(stet_router)
app.include_router(passages_router)
