"""This module provides the FastAPI API definition."""

import logging
import os
from typing import Dict, List, Tuple

import yaml
from fastapi import FastAPI

from document import config
from document.domain import model, resource_lookup
from document.domain.document_generator import DocumentGenerator

# import json


app = FastAPI()

with open(config.get_logging_config_file_path(), "r") as f:
    logging_config = yaml.safe_load(f.read())
    logging.config.dictConfig(logging_config)

logger = logging.getLogger(__name__)


# FIXME This could be async def, see
# ~/.ghq/github.com/hogeline/sample_fastapi/code/main.py, instead of synchronous.
# @app.post(f"{config.get_api_root()}/document")
@app.post("/documents", response_model=model.FinishedDocumentDetails)
def document_endpoint(
    document_request: model.DocumentRequest,
) -> model.FinishedDocumentDetails:
    """
    Get the document request and hand it off to the document_generator
    module for processing. Return FinishedDocumentDetails instance
    containing URL of resulting PDF.
    """
    document_generator = DocumentGenerator(
        document_request, config.get_working_dir(), config.get_output_dir(),
    )
    document_generator.run()

    # FIXME Eventually we'll provide a REST GET endpoint from
    # which to retrieve the document in the API
    finished_document_path = document_generator.get_finished_document_filepath()
    details = model.FinishedDocumentDetails(
        # FIXME document_generator.get_finished_document_filepath()
        # will become document_generator.get_finished_document_url()
        # and will return the URL of the PDF served through FastAPI
        # FileResponse method.
        finished_document_path=finished_document_path
    )

    logger.debug("details: {}".format(details))
    return details


# @app.get(f"{config.get_api_root()}/language_codes_names_and_resource_types")
@app.get("/language_codes_names_and_resource_types")
def lang_codes_names_and_resource_types() -> List[Tuple[str, str, List[str]]]:
    """
    Return list of tuples of lang_code, lang_name, resource_types for
    all available language codes.
    """
    lookup_svc = resource_lookup.BIELHelperResourceJsonLookup()
    return lookup_svc.lang_codes_names_and_resource_types()


# @app.get(f"{config.get_api_root()}/language_codes")
@app.get("/language_codes")
def lang_codes() -> List[str]:
    """Return list of all available language codes."""
    lookup_svc = resource_lookup.BIELHelperResourceJsonLookup()
    return lookup_svc.lang_codes()


# @app.get(f"{config.get_api_root()}/language_codes_and_names")
@app.get("/language_codes_and_names")
def lang_codes_and_names() -> List[Tuple[str, str]]:
    """Return list of all available language code, name tuples."""
    lookup_svc = resource_lookup.BIELHelperResourceJsonLookup()
    return lookup_svc.lang_codes_and_names()


# @app.get(f"{config.get_api_root()}/resource_types")
@app.get("/resource_types")
def resource_types() -> List[str]:
    """Return list of all available resource types."""
    lookup_svc = resource_lookup.BIELHelperResourceJsonLookup()
    return lookup_svc.resource_types()


# @app.get(f"{config.get_api_root()}/resource_codes")
@app.get("/resource_codes")
def resource_codes() -> List[str]:
    """Return list of all available resource codes."""
    lookup_svc = resource_lookup.BIELHelperResourceJsonLookup()
    return lookup_svc.resource_codes()


@app.get("/health/status")
def health_status() -> Tuple[Dict, int]:
    """Ping-able server endpoint."""
    return {"status": "ok"}, 200
