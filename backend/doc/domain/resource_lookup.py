"""
This module provides an API for looking up the location of a
resource's asset files in the cloud and acquiring said resource
assets.
"""

import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from os import scandir, stat
from os.path import exists, isdir, join
from pathlib import Path
from typing import Mapping, Optional, Sequence

import requests
from cachetools import TTLCache, cached
from doc.config import settings
from doc.domain.constants import (
    GATEWAY_LANGUAGES,
    RESOURCE_TYPE_CODES_AND_NAMES,
    USFM_RESOURCE_TYPES,
)
from doc.domain import worker
from doc.domain.bible_books import BOOK_CHAPTERS, BOOK_ID_MAP, BOOK_NAMES
from doc.domain.model import (
    NON_USFM_RESOURCE_TYPES,
    Content,
    LangDirEnum,
    Language,
    RepoEntry,
    ResourceLookupDto,
    SourceData,
)
from doc.utils.file_utils import (
    delete_tree,
    file_needs_update,
)
from doc.utils.list_utils import unique_tuples, unique_book_codes
from doc.utils.text_utils import maybe_correct_book_name, normalize_localized_book_name
from doc.utils.url_utils import (
    get_last_segment,
    get_book_name_from_title_file,
    book_codes_and_names_from_manifest,
)
from fastapi import HTTPException, status
from filelock import FileLock, Timeout
from pydantic import HttpUrl, ValidationError

logger = settings.logger(__name__)

fetch_source_data_cache: TTLCache[str, SourceData] = TTLCache(
    maxsize=1, ttl=settings.DATA_API_CACHE_TTL_SECONDS
)

fetch_non_primary_source_data_cache: TTLCache[str, SourceData] = TTLCache(
    maxsize=1, ttl=settings.DATA_API_CACHE_TTL_SECONDS
)


@cached(fetch_source_data_cache)
def fetch_source_data(
    data_api_url: HttpUrl = settings.DATA_API_URL,
    user_agent_str: str = settings.USER_AGENT_STR,
    x_requested_with_value: str = settings.X_REQUESTED_WITH_VALUE,
) -> Optional[SourceData]:
    """
    Downloads data from a GraphQL API.

    >>> from doc.domain import resource_lookup
    >>> ();result = resource_lookup.fetch_source_data();() # doctest: +ELLIPSIS
    (...)
    >>> result.git_repo[0]
    RepoEntry(repo_url=HttpUrl('https://content.bibletranslationtools.org/0success/cli_1co_text_reg'), content=Content(resource_type='reg', language=Language(english_name='Chakali', ietf_code='cli', national_name='Chakali', direction=<LangDirEnum.LTR: 'ltr'>)))
    """
    graphql_query = """
query MyQuery {
  git_repo(
    where: {content: {wa_content_metadata: {status: {_eq: "Primary"}}}}
  ) {
    repo_url
    content {
      resource_type
      language {
        english_name
        ietf_code
        national_name
        direction
      }
    }
  }
}
    """
    query_json = {"query": graphql_query}
    headers = {"User-Agent": user_agent_str, "X-Requested-With": x_requested_with_value}
    try:
        response = requests.post(str(data_api_url), json=query_json, headers=headers)
        if response.status_code == 200:
            data_payload = response.json().get("data", {})
            if "git_repo" in data_payload:
                valid_repos = [
                    repo
                    for repo in data_payload["git_repo"]
                    if repo.get("content", {}).get("resource_type") is not None
                    and repo.get("content", {}).get("language") is not None
                ]
                # Sort for test stability - ensures consistent ordering
                valid_repos.sort(key=lambda repo: repo["repo_url"])
                return SourceData.model_validate({"git_repo": valid_repos})
            else:
                logger.info("Invalid payload structure, no data.")
                return SourceData(git_repo=[])
        else:
            logger.info(
                "Failed to get data from data API, graphql API might be down..."
            )
            return SourceData(git_repo=[])
    except requests.RequestException as e:
        logger.exception("Request failed: %s", e)
        logger.info("Failed to get data from data API, API might be down...")
        return SourceData(git_repo=[])
    except ValidationError as e:
        logger.exception(
            "Request failed due to invalid data returned from data API: %s", e
        )
        logger.info(
            "Some of the data returned by data API is invalid, check logs for details"
        )
        return SourceData(git_repo=[])


@cached(fetch_non_primary_source_data_cache)
def fetch_non_primary_source_data(
    data_api_url: HttpUrl = settings.DATA_API_URL,
    user_agent_str: str = settings.USER_AGENT_STR,
    x_requested_with_value: str = settings.X_REQUESTED_WITH_VALUE,
) -> Optional[SourceData]:
    """
    Downloads data from a GraphQL API.

    >>> from doc.domain import resource_lookup
    >>> ();result = resource_lookup.fetch_source_data();() # doctest: +ELLIPSIS
    (...)
    >>> len(result.git_repo) > 0
    True
    """
    graphql_query = """
query MyQuery {
  git_repo(
    where: {content: {language: {ietf_code: {_eq: "bg"}}}}
  ) {
    repo_url
    content {
      resource_type
      language {
        english_name
        ietf_code
        national_name
        direction
      }
    }
  }
}
    """
    query_json = {"query": graphql_query}
    headers = {"User-Agent": user_agent_str, "X-Requested-With": x_requested_with_value}
    try:
        response = requests.post(str(data_api_url), json=query_json, headers=headers)
        if response.status_code == 200:
            data_payload = response.json().get("data", {})
            if "git_repo" in data_payload:
                valid_repos = [
                    repo
                    for repo in data_payload["git_repo"]
                    if repo.get("content", {}).get("resource_type") is not None
                    and repo.get("content", {}).get("language") is not None
                    and "WA-Catalog" in repo.get("repo_url", {})
                ]
                # Sort for test stability - ensures consistent ordering
                valid_repos.sort(key=lambda repo: repo["repo_url"])
                return SourceData.model_validate({"git_repo": valid_repos})
            else:
                logger.info("Invalid payload structure, no data.")
                return SourceData(git_repo=[])
        else:
            logger.info(
                "Failed to get data from data API, graphql API might be down..."
            )
            return SourceData(git_repo=[])
    except requests.RequestException as e:
        logger.exception("Request failed: %s", e)
        logger.info("Failed to get data from data API, API might be down...")
        return SourceData(git_repo=[])
    except ValidationError as e:
        logger.exception(
            "Request failed due to invalid data returned from data API: %s", e
        )
        logger.info(
            "Some of the data returned by data API is invalid, check logs for details"
        )
        return SourceData(git_repo=[])


def lang_codes_and_names(
    # lang_code_filter_list: Sequence[str] = settings.LANG_CODE_FILTER_LIST,
    gateway_languages: frozenset[str] = GATEWAY_LANGUAGES,
) -> Sequence[tuple[str, str, bool]]:
    """
    >>> from doc.domain import resource_lookup
    >>> ();result = resource_lookup.lang_codes_and_names();() # doctest: +ELLIPSIS
    (...)
    >>> result[0]
    ('abz', 'Abui', False)
    >>> heart_lang_codes = [lang_code_and_name[0] for lang_code_and_name in resource_lookup.lang_codes_and_names() if not lang_code_and_name[2]]
    >>> sorted(heart_lang_codes)[0]
    'aac'
    """
    data = fetch_source_data()
    non_primary_data = fetch_non_primary_source_data()
    values = []
    if data is None or not data.git_repo:
        logger.info("Data API is down or no git_repo found!")
        return []
    try:
        # if ietf_code not in lang_code_filter_list:
        for repo_info in data.git_repo:
            language_info = repo_info.content
            language = language_info.language
            ietf_code = language.ietf_code
            english_name = language.english_name if language.english_name else ""
            localized_name = language.national_name
            is_gateway = ietf_code in gateway_languages
            if english_name in localized_name:
                values.append((ietf_code, localized_name, is_gateway))
            else:
                values.append(
                    (ietf_code, f"{localized_name} ({english_name})", is_gateway)
                )
    except Exception:
        logger.exception("Failed due to the following exception.")
    if non_primary_data is None or not non_primary_data.git_repo:
        logger.info("Data API is down or no git_repo found!")
        return []
    try:
        for non_primary_repo_info in non_primary_data.git_repo:
            non_primary_language_info = non_primary_repo_info.content
            non_primary_language = non_primary_language_info.language
            non_primary_ietf_code = non_primary_language.ietf_code
            non_primary_english_name = (
                non_primary_language.english_name
                if non_primary_language.english_name
                else ""
            )
            non_primary_localized_name = non_primary_language.national_name
            non_primary_is_gateway = non_primary_ietf_code in gateway_languages
            if non_primary_english_name in non_primary_localized_name:
                values.append(
                    (
                        non_primary_ietf_code,
                        non_primary_localized_name,
                        non_primary_is_gateway,
                    )
                )
            else:
                values.append(
                    (
                        non_primary_ietf_code,
                        f"{non_primary_localized_name} ({non_primary_english_name})",
                        non_primary_is_gateway,
                    )
                )
    except Exception:
        logger.exception("Failed due to the following exception.")
    unique_values = unique_tuples(values)
    return sorted(unique_values, key=lambda value: value[1])


def repos_to_clone(
    lang_code: str,
    augmented_repos_info: list[RepoEntry],
    resource_assets_dir: str = settings.RESOURCE_ASSETS_DIR,
    dcs_mirror_git_username: str = "DCS-Mirror",
    resource_type_codes_and_names: Sequence[str] = list(
        RESOURCE_TYPE_CODES_AND_NAMES.keys()
    ),
) -> list[tuple[HttpUrl, str, str]]:
    repo_clone_list: list[tuple[HttpUrl, str, str]] = []
    try:
        for repo_info in augmented_repos_info:
            content = repo_info.content
            resource_type = content.resource_type
            if (
                content.language.ietf_code == lang_code
                and resource_type in resource_type_codes_and_names
            ):
                url = repo_info.repo_url
                last_segment = get_last_segment(url, lang_code)
                resource_filepath = f"{resource_assets_dir}/{last_segment}"
                repo_components = last_segment.split("_")
                if dcs_mirror_git_username in str(url):
                    repo_components = update_repo_components(repo_components)
                if not any(item[0] == url for item in repo_clone_list):
                    repo_clone_list.append(
                        (
                            url,
                            resource_filepath,
                            resource_type,
                        )
                    )
    except Exception:
        logger.exception("Error during repos_to_clone")
    finally:
        return repo_clone_list


def get_resource_types(
    repo_clone_list: Sequence[tuple[HttpUrl, str, str]],
    book_codes: Sequence[str],
    bc_book_asset_pattern: str = r"^\d{2,}-[0-9a-z]{3}$",
    usfm_resource_types: Sequence[str] = USFM_RESOURCE_TYPES,
    docx_file_path: str = "en_rg_nt_survey.docx",
    resource_type_codes_and_names: Mapping[str, str] = RESOURCE_TYPE_CODES_AND_NAMES,
) -> list[tuple[str, str]]:
    from doc.domain.parsing import find_usfm_files

    resource_types = []
    for url, resource_filepath, resource_type in repo_clone_list:
        if resource_type:
            book_assets = []
            if resource_type in ["tq", "tn", "tn-condensed"]:
                book_assets = [
                    file.name
                    for file in scandir(resource_filepath)
                    if file.is_dir()
                    and not file.name.startswith(".")
                    and file.name.lower() in book_codes
                ]
            elif resource_type == "bc":
                book_assets = [
                    file.name
                    for file in scandir(resource_filepath)
                    if file.is_dir()
                    and not file.name.startswith(".")
                    and re.search(bc_book_asset_pattern, file.name)
                    and file.name.split("-")[1].lower() in book_codes
                ]
            elif resource_type in usfm_resource_types:
                book_assets = find_usfm_files(resource_filepath)
            if book_assets or resource_type == "tw":
                resource_types.append(
                    (
                        resource_type,
                        resource_type_codes_and_names[resource_type],
                    )
                )
    return resource_types


def filter_excluded_resource_types(
    repos_info: list[RepoEntry], excluded: list[tuple[str, str]] = [("en", "udb")]
) -> list[RepoEntry]:
    return [
        entry
        for entry in repos_info
        if (entry.content.language.ietf_code, entry.content.resource_type)
        not in excluded
    ]


@worker.app.task
def resource_types(
    lang_code: str,
    book_codes_str: str,
    book_names: Mapping[str, str] = BOOK_NAMES,
    download_assets: bool = settings.DOWNLOAD_ASSETS,
) -> Sequence[tuple[str, str]]:
    """
    Fetches and processes available resource types for the given language and book codes.

    >>> from doc.domain import resource_lookup
    >>> lang_code = "pt-br"
    >>> books = resource_lookup.book_codes_for_lang(lang_code)
    >>> ();result = resource_lookup.resource_types(lang_code, "".join([book[0] for book in books]));() # doctest: +ELLIPSIS
    (...)
    >>> result
    [('blv', 'Portuguese Bíblia Livre'), ('tw', 'Translation Words'), ('ulb', 'Unlocked Literal Bible')]
    """
    book_codes = book_codes_str.split(",")
    resource_types_: list[tuple[str, str]] = []
    if book_codes and book_codes[0] == "all":
        book_codes = list(book_names.keys())
    data = fetch_source_data()
    repo_clone_list: list[tuple[HttpUrl, str, str]] = []
    if data is None or not data.git_repo:
        logger.info("Data API is down or no git_repo found!")
        return []
    try:
        repos_info = data.git_repo
        repos_info = filter_excluded_resource_types(repos_info)
        augmented_repos_info = add_data_not_supplied_by_data_api(repos_info)
        repo_clone_list = repos_to_clone(lang_code, augmented_repos_info)
        repos_to_clone_ = [
            (url, path)
            for url, path, resource_type_ in repo_clone_list
            if "rg" != resource_type_
        ]
        if download_assets:
            batch_download_repos(repos_to_clone_)
        else:
            clone_git_repos_until_complete(repos_to_clone_)
        resource_types_ = get_resource_types(repo_clone_list, book_codes)
    except Exception:
        logger.exception("Failed due to the following exception.")
    unique_values = unique_tuples(resource_types_)
    return sorted(unique_values, key=lambda value: value[1])


# We found that there are fewer downloads available than clonable repos,
# so we don't currently have the system configured to use this.
def batch_download_repos(
    repos: list[tuple[HttpUrl, str]],
    base_url: HttpUrl = HttpUrl("https://content.bibletranslationtools.org/"),
    base_url_replacement: HttpUrl = HttpUrl(
        "https://content.bibletranslationtools.org/api/v1/repos/"
    ),
    resource_assets_dir: str = settings.RESOURCE_ASSETS_DIR,
    user_agent_str: str = settings.USER_AGENT_STR,
    x_requested_with_value: str = settings.X_REQUESTED_WITH_VALUE,
) -> None:
    """Batch download repos and then batch unzip repos."""
    download_commands = []
    zip_file_paths = []
    for url, resource_filepath in repos:
        zip_file_path = Path(f"{resource_filepath}.zip")
        if isdir(resource_filepath):
            # Instead of checking the directory which was created from
            # a zip with timestamps current when the zip file was created (which
            # would likely be quite old), we instead check the zip file itself.
            if file_needs_update(zip_file_path):
                logger.info(
                    f"Removing stale, incomplete, or corrupt repository: {resource_filepath} and zip file: {zip_file_path}"
                )
                if zip_file_path.is_file():
                    zip_file_path.unlink()
                delete_tree(resource_filepath)
            else:
                logger.info(f"Skipping download: {resource_filepath} already exists.")
                continue
        zip_url_base = re.sub(str(base_url), str(base_url_replacement), str(url))
        zip_url = f"{zip_url_base}/archive/master.zip"
        download_commands.append(
            f"curl -A {user_agent_str} -H 'X-Requested-With: {x_requested_with_value}' -X 'GET' {zip_url} -H 'accept: application/json' --output {zip_file_path} --parallel"
        )
        zip_file_paths.append(zip_file_path)
    download_command = " && ".join(download_commands)
    logger.info(f"Downloading repos with command: {download_command}")
    try:
        subprocess.check_call(download_command, shell=True)
        unzip_commands = [
            f"unzip -q -o {zip_file_path} -d {resource_assets_dir}"
            for zip_file_path in zip_file_paths
        ]
        unzip_command = " && ".join(unzip_commands)
        logger.info(f"Unzipping downloaded files with command: {unzip_command}")
        subprocess.check_call(unzip_command, shell=True)
    except subprocess.CalledProcessError:
        logger.error("Batch download or unzip failed!")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Download of repo master.zip failed",
        )


# Generous ceiling on how long a request will keep waiting behind other
# processes' in-flight clones of the same repos. Normally a contended repo is
# resolved as soon as the holder finishes (or dies, releasing its lock).
CLONE_CONTENTION_CEILING_SECONDS: int = 30 * 60


def clone_git_repos_until_complete(
    repos: list[tuple[HttpUrl, str]],
    max_wait_seconds: int = CLONE_CONTENTION_CEILING_SECONDS,
    lock_timeout_seconds: int = settings.LOCK_TIMEOUT_SECONDS,
) -> None:
    """
    Clone repos, then keep retrying any that batch_clone_git_repos skipped
    because another process held their lock, until all are cloned.

    A skip means another process is (normally) cloning that repo right now.
    On retry, once the holder has finished, the staleness check sees a
    complete, fresh clone and does no work; if the holder died, its lock was
    released and this process performs the clone itself. We never return
    with a missing or partial repo. If max_wait_seconds elapses with repos
    still contended, we log clearly and raise TimeoutError rather than let
    callers proceed with partial assets.
    """
    deadline = time.monotonic() + max_wait_seconds
    pending = repos
    attempt = 0
    while pending:
        attempt += 1
        skipped_paths = set(
            batch_clone_git_repos(pending, lock_timeout_seconds=lock_timeout_seconds)
        )
        if not skipped_paths:
            return
        pending = [(url, path) for url, path in pending if path in skipped_paths]
        if time.monotonic() >= deadline:
            logger.error(
                f"Gave up after {max_wait_seconds}s waiting on {len(pending)} repo(s) "
                f"locked by other processes: {sorted(skipped_paths)}"
            )
            raise TimeoutError(
                f"Timed out waiting for other processes to finish cloning: {sorted(skipped_paths)}"
            )
        logger.info(
            f"Retrying {len(pending)} contended repo(s) (attempt {attempt + 1}): {sorted(skipped_paths)}"
        )


# @worker.app.task
def batch_clone_git_repos(
    repos: list[tuple[HttpUrl, str]],
    asset_caching_enabled: bool = settings.ASSET_CACHING_ENABLED,
    asset_caching_period: int = settings.ASSET_CACHING_PERIOD,
    user_agent_str: str = settings.USER_AGENT_STR,
    x_requested_with_value: str = settings.X_REQUESTED_WITH_VALUE,
    lock_timeout_seconds: int = settings.LOCK_TIMEOUT_SECONDS,
) -> list[str]:
    """
    Clones multiple git repositories in a batch operation.
    - If a repository already exists, is fully cloned, and not stale (with respect to cache period), it is skipped.
      Conversely, if a repository is fully cloned, but stale then it is removed before (re)cloning.
    - If a repository exists but is a partial clone (corrupt or missing key files), it is removed before (re)cloning.
    - If asset_caching_enabled is False, repositories are always removed and re-cloned.

    Each repository's staleness-check, removal, and clone are performed
    while holding a per-`resource_filepath` FileLock, so that two
    concurrent callers (e.g., different gunicorn worker processes handling
    overlapping resource_types/get_book_codes_for_lang requests) computing
    the same deterministic resource_filepath cannot race shutil.rmtree()
    and git clone against each other. lock_timeout_seconds bounds how long
    a caller waits behind another in-flight clone of the same repo before
    giving up on that repo for this request; repos that time out are
    skipped (left untouched) rather than raising, and their paths are
    returned; callers should use clone_git_repos_until_complete, which
    retries them until cloned.
    """
    skipped_resource_filepaths: list[str] = []
    for url, resource_filepath in repos:
        lock = FileLock(resource_filepath + ".lock", timeout=lock_timeout_seconds)
        try:
            with lock:
                do_clone = True
                if asset_caching_enabled:
                    try:
                        git_dir = join(resource_filepath, ".git")
                        stat_ = stat(git_dir)
                        mod_time = datetime.fromtimestamp(stat_.st_mtime)
                        expiry = timedelta(minutes=asset_caching_period)
                        if (
                            all(
                                exists(join(git_dir, filename))
                                for filename in ["config", "HEAD", "objects"]
                            )
                            and any(scandir(resource_filepath))
                            and datetime.now() - mod_time <= expiry
                        ):
                            logger.info(
                                f"Skipping clone: {resource_filepath} already exists, is a valid git repo, and is not stale."
                            )
                            do_clone = False  # ✅ Fully cloned and not stale, reuse
                    except FileNotFoundError:
                        logger.warning(f"Git directory, {git_dir}, not found")
                    if do_clone:
                        logger.info(
                            f"Removing stale, incomplete, or corrupt repository: {resource_filepath}"
                        )
                else:
                    logger.info(
                        f"Asset caching disabled: forcibly removing {resource_filepath}"
                    )
                if do_clone:
                    if isdir(resource_filepath):
                        shutil.rmtree(resource_filepath)
                    clone_command = (
                        f"git -c http.userAgent='{user_agent_str}' "
                        f"-c http.extraHeader='X-Requested-With:{x_requested_with_value}' "
                        f"clone --depth=1 --single-branch '{url}' '{resource_filepath}'"
                    )
                    rc = subprocess.call(clone_command, shell=True)
                    if rc != 0:
                        logger.error(
                            f"git clone failed for {resource_filepath} (exit code {rc})"
                        )
        except Timeout:
            logger.warning(
                f"Skipping {resource_filepath} this request: lock contended, another worker is likely mid-clone; try again shortly."
            )
            skipped_resource_filepaths.append(resource_filepath)
    return skipped_resource_filepaths


# Used by some tests
def usfm_resource_types_and_book_tuples(
    lang_code: str,
    book_codes_str: str,
    usfm_resource_types: Sequence[str] = USFM_RESOURCE_TYPES,
) -> Sequence[tuple[str, str]]:
    """
    >>> from doc.domain import resource_lookup
    >>> lang_code = "ruc"
    >>> ();books = resource_lookup.book_codes_for_lang(lang_code);() # doctest: +ELLIPSIS
    (...)
    >>> ();tuples = resource_lookup.usfm_resource_types_and_book_tuples(lang_code, ",".join([book[0] for book in books]));() # doctest: +ELLIPSIS
    (...)
    >>> sorted(tuples, key=lambda value: value[1])
    [('reg', '1co'), ('reg', '1jn'), ('reg', '1pe'), ('reg', '1th'), ('reg', '1ti'), ('reg', '2co'), ('reg', '2jn'), ('reg', '2pe'), ('reg', '2th'), ('reg', '2ti'), ('reg', '3jn'), ('reg', 'act'), ('reg', 'col'), ('reg', 'eph'), ('reg', 'gal'), ('reg', 'heb'), ('reg', 'jas'), ('reg', 'jhn'), ('reg', 'jud'), ('reg', 'luk'), ('reg', 'mat'), ('reg', 'mrk'), ('reg', 'phm'), ('reg', 'php'), ('reg', 'rev'), ('reg', 'rom'), ('reg', 'tit')]
    """
    from doc.domain.parsing import usfm_asset_file

    book_codes = book_codes_str.split(",")
    data: SourceData | None = fetch_source_data()
    resource_type_and_book_tuples = set()
    if data is None:
        return []
    repos_info = data.git_repo
    augmented_repos_info = add_data_not_supplied_by_data_api(repos_info)
    for repo_info in augmented_repos_info:
        content = repo_info.content
        language_info = content.language
        if language_info.ietf_code == lang_code:
            resource_type = content.resource_type
            if resource_type in usfm_resource_types:
                url = repo_info.repo_url
                for book_code in book_codes:
                    dto = ResourceLookupDto(
                        lang_code=lang_code,
                        lang_name=language_info.english_name,
                        localized_lang_name=language_info.national_name,
                        resource_type=resource_type,
                        resource_type_name="",
                        url=url,
                        lang_direction=LangDirEnum(language_info.direction),
                        book_code=book_code,
                    )
                    resource_filepath = prepare_resource_filepath(dto)
                    if file_needs_update(resource_filepath):
                        provision_asset_files(dto.url, resource_filepath)
                    content_file = usfm_asset_file(dto, resource_filepath, False)
                    if content_file:
                        resource_type_and_book_tuples.add((resource_type, book_code))
    return sorted(resource_type_and_book_tuples, key=lambda value: value[0])


def shared_book_codes(lang0_code: str, lang1_code: str) -> Sequence[tuple[str, str]]:
    """
    Given two language codes, return the intersection of book
    codes between the two languages.

    >>> from doc.domain import resource_lookup
    >>> # Hack to ignore logging output: https://stackoverflow.com/a/33400983/3034580
    >>> ();data = resource_lookup.book_codes_for_lang("pt-br");() # doctest: +ELLIPSIS
    (...)
    >>> list(data)
    [('gen', 'Gênesis'), ('exo', 'Êxodo'), ('lev', 'Levíticos'), ('num', 'Números'), ('deu', 'Deuteronômio'), ('jos', 'Josué'), ('jdg', 'Juízes'), ('rut', 'Rute'), ('1sa', '1 Samuel'), ('2sa', '2 Samuel'), ('1ki', '1 Reis'), ('2ki', '2 Reis'), ('1ch', '1 Crônicas'), ('2ch', '2 Crônicas'), ('ezr', 'Esdras'), ('neh', 'Neemias'), ('est', 'Ester'), ('job', 'Jó'), ('psa', 'Salmos'), ('pro', 'Provérbios'), ('ecc', 'Eclesiastes'), ('sng', 'Cantares de salomão'), ('isa', 'Isaías'), ('jer', 'Jeremias'), ('lam', 'Lamentações'), ('ezk', 'Ezequiel'), ('dan', 'Daniel'), ('hos', 'Oseias'), ('jol', 'Joel'), ('amo', 'Amós'), ('oba', 'Obadias'), ('jon', 'Jonas'), ('mic', 'Miqueias'), ('nam', 'Naum'), ('hab', 'Habacuque'), ('zep', 'Sofonias'), ('hag', 'Ageu'), ('zec', 'Zacarias'), ('mal', 'Malaquias'), ('mat', 'Mateus'), ('mrk', 'Marcos'), ('luk', 'Lucas'), ('jhn', 'João'), ('act', 'Atos'), ('rom', 'Romanos'), ('1co', '1 Coríntios'), ('2co', '2 Coríntios'), ('gal', 'Gálatas'), ('eph', 'Efésios'), ('php', 'Filipenses'), ('col', 'Colossenses'), ('1th', '1 Tessalonicenses'), ('2th', '2 Tessalonicenses'), ('1ti', '1 Timóteo'), ('2ti', '2 Timóteo'), ('tit', 'Tito'), ('phm', 'Filemom'), ('heb', 'Hebreus'), ('jas', 'Tiago'), ('1pe', '1 Pedro'), ('2pe', '2 Pedro'), ('1jn', '1 João'), ('2jn', '2 João'), ('3jn', '3 João'), ('jud', 'Judas'), ('rev', 'Apocalipse')]
    >>> ();data = resource_lookup.book_codes_for_lang("es-419");() # doctest: +ELLIPSIS
    (...)
    >>> list(data)
    [('gen', 'Génesis'), ('exo', 'Éxodo'), ('lev', 'Levítico'), ('num', 'Números'), ('deu', 'Deuteronomio'), ('jos', 'Josué'), ('jdg', 'Jueces'), ('rut', 'Ruth'), ('1sa', '1 Samuel'), ('2sa', '2 Samuel'), ('1ki', '1 Reyes'), ('2ki', '2 Reyes'), ('1ch', '1 Crónicas'), ('2ch', '2 Crónicas'), ('ezr', 'Esdras'), ('neh', 'Nehemías'), ('est', 'Ester'), ('job', 'Job'), ('psa', 'Salmos'), ('pro', 'Proverbios'), ('ecc', 'Eclesiastés'), ('sng', 'Cántico de salomón'), ('isa', 'Isaías'), ('jer', 'Jeremías'), ('lam', 'Lamentaciones'), ('ezk', 'Ezequiel'), ('dan', 'Daniel'), ('hos', 'Oseas'), ('jol', 'Joel'), ('amo', 'Amós'), ('oba', 'Abdías'), ('jon', 'Jonás'), ('mic', 'Miqueas'), ('nam', 'Nahúm'), ('hab', 'Habacuc'), ('zep', 'Sofonías'), ('hag', 'Hageo'), ('zec', 'Zacarías'), ('mal', 'Malaquías'), ('mat', 'Mateo'), ('mrk', 'Marcos'), ('luk', 'Lucas'), ('jhn', 'Juan'), ('act', 'Hechos'), ('rom', 'Romanos'), ('1co', '1 Corintios'), ('2co', '2 Corintios'), ('gal', 'Gálatas'), ('eph', 'Efesios'), ('php', 'Filipenses'), ('col', 'Colosenses'), ('1th', '1 Tesalonicenses'), ('2th', '2 Tesalonicenses'), ('1ti', '1 Timoteo'), ('2ti', '2 Timoteo'), ('tit', 'Tito'), ('phm', 'Filemón'), ('heb', 'Hebreos'), ('jas', 'Santiago'), ('1pe', '1 Pedro'), ('2pe', '2 Pedro'), ('1jn', '1 Juan'), ('2jn', '2 Juan'), ('3jn', '3 Juan'), ('jud', 'Judas'), ('rev', 'Apocalipsis')]
    >>> ();data = resource_lookup.shared_book_codes("pt-br", "es-419");() # doctest: +ELLIPSIS
    (...)
    >>> list(data)
    [('gen', 'Gênesis'), ('exo', 'Êxodo'), ('lev', 'Levíticos'), ('num', 'Números'), ('deu', 'Deuteronômio'), ('jos', 'Josué'), ('jdg', 'Juízes'), ('rut', 'Rute'), ('1sa', '1 Samuel'), ('2sa', '2 Samuel'), ('1ki', '1 Reis'), ('2ki', '2 Reis'), ('1ch', '1 Crônicas'), ('2ch', '2 Crônicas'), ('ezr', 'Esdras'), ('neh', 'Neemias'), ('est', 'Ester'), ('job', 'Jó'), ('psa', 'Salmos'), ('pro', 'Provérbios'), ('ecc', 'Eclesiastes'), ('sng', 'Cantares de salomão'), ('isa', 'Isaías'), ('jer', 'Jeremias'), ('lam', 'Lamentações'), ('ezk', 'Ezequiel'), ('dan', 'Daniel'), ('hos', 'Oseias'), ('jol', 'Joel'), ('amo', 'Amós'), ('oba', 'Obadias'), ('jon', 'Jonas'), ('mic', 'Miqueias'), ('nam', 'Naum'), ('hab', 'Habacuque'), ('zep', 'Sofonias'), ('hag', 'Ageu'), ('zec', 'Zacarias'), ('mal', 'Malaquias'), ('mat', 'Mateus'), ('mrk', 'Marcos'), ('luk', 'Lucas'), ('jhn', 'João'), ('act', 'Atos'), ('rom', 'Romanos'), ('1co', '1 Coríntios'), ('2co', '2 Coríntios'), ('gal', 'Gálatas'), ('eph', 'Efésios'), ('php', 'Filipenses'), ('col', 'Colossenses'), ('1th', '1 Tessalonicenses'), ('2th', '2 Tessalonicenses'), ('1ti', '1 Timóteo'), ('2ti', '2 Timóteo'), ('tit', 'Tito'), ('phm', 'Filemom'), ('heb', 'Hebreus'), ('jas', 'Tiago'), ('1pe', '1 Pedro'), ('2pe', '2 Pedro'), ('1jn', '1 João'), ('2jn', '2 João'), ('3jn', '3 João'), ('jud', 'Judas'), ('rev', 'Apocalipse')]

    """
    lang0_book_codes = book_codes_for_lang(lang0_code)
    lang1_book_codes = book_codes_for_lang(lang1_code)
    # Find intersection of book codes:
    return [
        (x, y) for x, y in lang0_book_codes if x in [s for s, t in lang1_book_codes]
    ]


def update_repo_components(
    repo_components: list[str],
    usfm_resource_types: Sequence[str] = USFM_RESOURCE_TYPES,
    non_usfm_resource_types: Sequence[str] = NON_USFM_RESOURCE_TYPES,
    resource_type_codes_and_names: Mapping[str, str] = RESOURCE_TYPE_CODES_AND_NAMES,
) -> list[str]:
    last_component = repo_components[-1]
    # Some DCS-Mirror URLs have an unusual pattern wherein a non resource type is the last component
    # in the URL, e.g., https://content.bibletranslationtools.org/DCS-Mirror/danjuma_alfred_h_kgo_phm_text_ulb_l1,
    # repo_components: ['danjuma', 'alfred', 'h', 'kgo', 'phm', 'text', 'ulb', 'l1']
    if (
        last_component not in usfm_resource_types
        and last_component not in non_usfm_resource_types
        and last_component not in resource_type_codes_and_names
    ):
        repo_components = repo_components[0:-1]
    match len(repo_components):
        case 7:
            repo_components = repo_components[3:]
        case 6:
            repo_components = repo_components[2:]
        case 5:
            repo_components = repo_components[1:]
        case 3:
            # Handle en_tn_condensed last segment of URL case
            if repo_components[0] == "en" and repo_components[1] == "condensed":
                repo_components = ["en", "tn_condensed"]
    return repo_components


def add_data_not_supplied_by_data_api(repos_info: list[RepoEntry]) -> list[RepoEntry]:
    """
    DOC needs to support some resources which are not supplied by the
    data API so we augment the data returned from the data API to include
    them here. If a (language code, resource type) pair already exists in
    repos_info, do not add it again.
    """

    def make_entry(url: HttpUrl, resource_type: str, lang: Language) -> RepoEntry:
        return RepoEntry(
            repo_url=url, content=Content(resource_type=resource_type, language=lang)
        )

    bg_lang = Language(
        english_name="Bulgarian",
        ietf_code="bg",
        national_name="български език",
        direction=LangDirEnum.LTR,
    )
    id_lang = Language(
        english_name="Indonesian",
        ietf_code="id",
        national_name="Bahasa Indonesian",
        direction=LangDirEnum.LTR,
    )
    en_lang = Language(
        english_name="English",
        ietf_code="en",
        national_name="English",
        direction=LangDirEnum.LTR,
    )
    extra_entries = [
        make_entry(
            HttpUrl("https://content.bibletranslationtools.org/WA-Catalog/bg_bpb"),
            "bpb",
            bg_lang,
        ),
        make_entry(
            HttpUrl(
                "https://content.bibletranslationtools.org/WycliffeAssociates/en_tn_condensed"
            ),
            "tn-condensed",
            en_lang,
        ),
        make_entry(
            HttpUrl("https://content.bibletranslationtools.org/WA-Catalog/id_tbi"),
            "tbi",
            id_lang,
        ),
        make_entry(
            HttpUrl("https://content.bibletranslationtools.org/WA-Catalog/id_ayt"),
            "ayt",
            id_lang,
        ),
        make_entry(
            HttpUrl("https://content.bibletranslationtools.org/WA-Catalog/id_tq"),
            "tq",
            id_lang,
        ),
        make_entry(
            HttpUrl("https://content.bibletranslationtools.org/WA-Catalog/id_tw"),
            "tw",
            id_lang,
        ),
    ]
    existing_pairs = {
        (entry.content.language.ietf_code, entry.content.resource_type)
        for entry in repos_info
    }
    for entry in extra_entries:
        key = (entry.content.language.ietf_code, entry.content.resource_type)
        if key not in existing_pairs:
            repos_info.append(entry)
            existing_pairs.add(key)
    return repos_info


def get_book_codes_for_lang(
    lang_code: str,
    usfm_only: bool = False,
    download_assets: bool = settings.DOWNLOAD_ASSETS,
) -> Sequence[tuple[str, str]]:
    data = fetch_source_data()
    if data is None:
        return []
    repo_clone_list: list[tuple[HttpUrl, str, str]] = []
    book_codes_and_names: list[tuple[str, str]] = []
    try:
        repos_info = data.git_repo
        augmented_repos_info = add_data_not_supplied_by_data_api(repos_info)
        repo_clone_list = repos_to_clone(lang_code, augmented_repos_info)
        repos_to_clone_ = [
            (url, path)
            for url, path, resource_type in repo_clone_list
            if "rg" != resource_type
        ]
        if download_assets:
            batch_download_repos(repos_to_clone_)
        else:
            clone_git_repos_until_complete(repos_to_clone_)
        book_codes_and_names = get_book_codes_for_lang_(
            repo_clone_list,
            lang_code,
            usfm_only,
        )
    except Exception:
        logger.exception("Error during get_book_codes_for_lang")
    return book_codes_and_names


def get_book_codes_for_lang_(
    repo_clone_list: list[tuple[HttpUrl, str, str]],
    lang_code: str,
    usfm_only: bool,
    book_names: Mapping[str, str] = BOOK_NAMES,
    usfm_resource_types: Sequence[str] = USFM_RESOURCE_TYPES,
    use_localized_book_name: bool = settings.USE_LOCALIZED_BOOK_NAME,
    book_id_map: dict[str, int] = BOOK_ID_MAP,
) -> list[tuple[str, str]]:
    book_codes_and_names_localized: list[tuple[str, str]] = []
    book_codes_and_names: list[tuple[str, str]] = []
    for url, resource_filepath, resource_type in repo_clone_list:
        last_segment = get_last_segment(url, lang_code)
        repo_components = last_segment.split("_")
        if (
            use_localized_book_name
            and len(repo_components) == 2
            and resource_type in usfm_resource_types
        ):
            book_codes_and_names_localized_from_metadata = (
                get_book_names_from_usfm_metadata(
                    resource_filepath,
                    lang_code,
                    resource_type,
                )
            )
            book_codes_and_names_localized_from_manifest = (
                book_codes_and_names_from_manifest(resource_filepath)
            )
            logger.debug(
                "book_codes_and_names_localized_from_metadata: %s",
                book_codes_and_names_localized_from_metadata,
            )
            logger.debug(
                "book_codes_and_names_localized_from_manifest: %s",
                book_codes_and_names_localized_from_manifest,
            )
            for code, name in book_codes_and_names_localized_from_metadata.items():
                manifest_name = book_codes_and_names_localized_from_manifest.get(
                    code, ""
                )
                chosen_name = name or manifest_name
                book_codes_and_names_localized.append(
                    (
                        code,
                        maybe_correct_book_name(
                            lang_code,
                            normalize_localized_book_name(chosen_name),
                        ),
                    )
                )
        elif (
            use_localized_book_name
            and len(repo_components) > 2
            and resource_type in usfm_resource_types
        ):
            book_name_ = get_book_name_from_title_file(
                resource_filepath,
                lang_code,
                repo_components,
            )
            logger.debug(
                "book_codes_and_names_localized_from_title_file: %s",
                book_name_,
            )
            logger.debug("book_code: %s", repo_components[1])
            logger.debug(
                "normalize_localized_book_name(book_name_): %s",
                normalize_localized_book_name(book_name_),
            )
            book_codes_and_names_localized.append(
                (
                    repo_components[1],
                    maybe_correct_book_name(
                        lang_code,
                        normalize_localized_book_name(book_name_),
                    ),
                )
            )
        if (
            not usfm_only
            or not book_codes_and_names_localized
            or any(name == "" for _, name in book_codes_and_names_localized)
        ):  # No localized book name sources were found, so use other alternatives for book name lookup
            book_codes_and_names.extend(
                get_non_localized_book_names(
                    repo_components,
                    book_names,
                    resource_type,
                    usfm_resource_types,
                    resource_filepath,
                )
            )
    logger.debug("book_codes_and_names: %s", book_codes_and_names)
    logger.debug("book_codes_and_names_localized: %s", book_codes_and_names_localized)
    localized_map: dict[str, str] = {
        code: name for code, name in book_codes_and_names_localized
    }
    non_localized_map: dict[str, str] = {
        code: name for code, name in book_codes_and_names
    }
    merged: list[tuple[str, str]] = []
    for code in set(localized_map) | set(non_localized_map):
        name = localized_map.get(code, "")
        if not name:
            name = non_localized_map.get(code, "")
        merged.append((code, name))
    unique_values = unique_book_codes(merged)
    return sorted(
        unique_values,
        key=lambda book_code_and_name: book_id_map[book_code_and_name[0]],
    )


def get_non_localized_book_names(
    repo_components: list[str],
    book_names: Mapping[str, str],
    resource_type: str,
    usfm_resource_types: Sequence[str],
    resource_filepath: str,
) -> list[tuple[str, str]]:
    """
    Get English book names
    """
    book_codes_and_names: list[tuple[str, str]] = []
    if len(repo_components) > 2:
        # Get book code from repo URL components and then lookup in English book names
        book_code = repo_components[1]
        if book_code in book_names:
            book_codes_and_names.append((book_code, book_names[book_code]))
    elif len(repo_components) == 2:
        # if resource_type in usfm_resource_types:
        #     logger.debug("FUBAR")  # DEBUG This case happened
        #     # Get book code from USFM file name and then lookup name in English book names
        #     usfm_files = find_usfm_files(resource_filepath)
        #     for usfm_file in usfm_files:
        #         book_code = Path(usfm_file).stem.lower().split("-")[1]
        #         book_codes_and_names.append((book_code, book_names[book_code]))
        if resource_type in ["tn", "tq"]:
            # Get book code from TN and TQ repo book sub-directory
            # names and use to lookup in English book names
            subdirs = [
                file
                for file in scandir(resource_filepath)
                if file.is_dir() and file.name in book_names
            ]
            for subdir in subdirs:
                book_codes_and_names.append(
                    (
                        subdir.name.lower(),
                        book_names[subdir.name.lower()],
                    )
                )
    return book_codes_and_names


def get_book_names_from_usfm_metadata(
    resource_filepath: str,
    lang_code: str,
    resource_type: str,
) -> dict[str, str]:
    """
    Book names obtained from USFM frontmatter/metadata may or may not
    be localized, it depends on the translation work done for language
    lang_code.
    """
    from doc.domain.parsing import (
        find_usfm_files,
        split_usfm_by_chapters,
        maybe_localized_book_name,
    )

    book_codes_and_names_localized: dict[str, str] = {}
    usfm_files = find_usfm_files(resource_filepath)
    for usfm_file in usfm_files:
        usfm = ""
        usfm_file_components = Path(usfm_file).stem.lower().split("-")
        book_code = usfm_file_components[1]
        with open(usfm_file, "r") as f:
            usfm = f.read()
        frontmatter, _, _ = split_usfm_by_chapters(
            lang_code, resource_type, book_code, usfm
        )
        localized_book_name = maybe_localized_book_name(
            frontmatter, lang_code, resource_type
        )
        # localized_book_name = maybe_correct_book_name(lang_code, localized_book_name)
        book_codes_and_names_localized[book_code] = localized_book_name
    logger.debug("book_codes_and_names_localized: %s", book_codes_and_names_localized)
    return book_codes_and_names_localized


@worker.app.task
def book_codes_for_lang(
    lang_code: str,
) -> Sequence[tuple[str, str]]:
    """
    >>> from doc.domain.resource_lookup import book_codes_for_lang
    >>> book_codes_for_lang("zh") # zh doesn't have USFM resource available, get books from non-USFM resources
    [('gen', 'Genesis'), ('exo', 'Exodus'), ('lev', 'Leviticus'), ('num', 'Numbers'), ('deu', 'Deuteronomy'), ('jos', 'Joshua'), ('jdg', 'Judges'), ('rut', 'Ruth'), ('1sa', '1 Samuel'), ('2sa', '2 Samuel'), ('1ki', '1 Kings'), ('2ki', '2 Kings'), ('1ch', '1 Chronicles'), ('2ch', '2 Chronicles'), ('ezr', 'Ezra'), ('neh', 'Nehemiah'), ('est', 'Esther'), ('job', 'Job'), ('psa', 'Psalms'), ('pro', 'Proverbs'), ('ecc', 'Ecclesiastes'), ('sng', 'Song of Solomon'), ('isa', 'Isaiah'), ('jer', 'Jeremiah'), ('lam', 'Lamentations'), ('ezk', 'Ezekiel'), ('dan', 'Daniel'), ('hos', 'Hosea'), ('jol', 'Joel'), ('amo', 'Amos'), ('oba', 'Obadiah'), ('jon', 'Jonah'), ('mic', 'Micah'), ('nam', 'Nahum'), ('hab', 'Habakkuk'), ('zep', 'Zephaniah'), ('hag', 'Haggai'), ('zec', 'Zechariah'), ('mal', 'Malachi'), ('mat', 'Matthew'), ('mrk', 'Mark'), ('luk', 'Luke'), ('jhn', 'John'), ('act', 'Acts'), ('rom', 'Romans'), ('1co', '1 Corinthians'), ('2co', '2 Corinthians'), ('gal', 'Galatians'), ('eph', 'Ephesians'), ('php', 'Philippians'), ('col', 'Colossians'), ('1th', '1 Thessalonians'), ('2th', '2 Thessalonians'), ('1ti', '1 Timothy'), ('2ti', '2 Timothy'), ('tit', 'Titus'), ('phm', 'Philemon'), ('heb', 'Hebrews'), ('jas', 'James'), ('1pe', '1 Peter'), ('2pe', '2 Peter'), ('1jn', '1 John'), ('2jn', '2 John'), ('3jn', '3 John'), ('jud', 'Jude'), ('rev', 'Revelation')]
    >>> book_codes_for_lang("pt-br") # pt-br has, for example, two book names for lev
    [('gen', 'Gênesis'), ('exo', 'Êxodo'), ('lev', 'Levítico'), ('num', 'Números'), ('deu', 'Deuteronômio'), ('jos', 'Josué'), ('jdg', 'Juízes'), ('rut', 'Rute'), ('1sa', '1 Samuel'), ('2sa', '2 Samuel'), ('1ki', '1 Reis'), ('2ki', '2 Reis'), ('1ch', '1 Crônicas'), ('2ch', '2 Crônicas'), ('ezr', 'Esdras'), ('neh', 'Neemias'), ('est', 'Ester'), ('job', 'Jó'), ('psa', 'Salmos'), ('pro', 'Provérbios'), ('ecc', 'Eclesiastes'), ('sng', 'Cantares'), ('isa', 'Isaías'), ('jer', 'Jeremias'), ('lam', 'Lamentações'), ('ezk', 'Ezequiel'), ('dan', 'Daniel'), ('hos', 'Oseias'), ('jol', 'Joel'), ('amo', 'Amós'), ('oba', 'Obadias'), ('jon', 'Jonas'), ('mic', 'Miqueias'), ('nam', 'Naum'), ('hab', 'Habacuque'), ('zep', 'Sofonias'), ('hag', 'Ageu'), ('zec', 'Zacarias'), ('mal', 'Malaquias'), ('mat', 'Mateus'), ('mrk', 'Marcos'), ('luk', 'Lucas'), ('jhn', 'João'), ('act', 'Atos'), ('rom', 'Romanos'), ('1co', '1 Coríntios'), ('2co', '2 Coríntios'), ('gal', 'Gálatas'), ('eph', 'Efésios'), ('php', 'Filipenses'), ('col', 'Colossenses'), ('1th', '1 Tessalonicenses'), ('2th', '2 Tessalonicenses'), ('1ti', '1 Timóteo'), ('2ti', '2 Timóteo'), ('tit', 'Tito'), ('phm', 'Filemom'), ('heb', 'Hebreus'), ('jas', 'Tiago'), ('1pe', '1 Pedro'), ('2pe', '2 Pedro'), ('1jn', '1 João'), ('2jn', '2 João'), ('3jn', '3 João'), ('jud', 'Judas'), ('rev', 'Apocalipse')]
    >>> book_codes_for_lang("ta")
    """
    return get_book_codes_for_lang(
        lang_code,
        usfm_only=False,
    )


@worker.app.task
def book_codes_for_lang_from_usfm_only(
    lang_code: str,
) -> Sequence[tuple[str, str]]:
    """
    >>> from doc.domain import resource_lookup
    >>> ();result = resource_lookup.book_codes_for_lang_from_usfm_only("pt-br");() # doctest: +ELLIPSIS
    (...)
    >>> result[0]
    ('gen', 'Gênesis')
    """
    return get_book_codes_for_lang(
        lang_code,
        usfm_only=True,
    )


def chapters_in_books(
    book_chapters: Mapping[str, int] = BOOK_CHAPTERS,
) -> dict[str, list[int]]:
    chapters_in_book: dict[str, list[int]] = {
        book_code: list(range(1, num_of_chapters + 1))
        for book_code, num_of_chapters in book_chapters.items()
    }
    return chapters_in_book


def resource_lookup_dto(
    lang_code: str,
    resource_type: str,
    book_code: str,
    dcs_mirror_git_username: str = "DCS-Mirror",
    zmq_git_username: str = "faustin_azaza",
    resource_type_codes_and_names: Mapping[str, str] = RESOURCE_TYPE_CODES_AND_NAMES,
) -> Optional[ResourceLookupDto]:
    """
    >>> from doc.domain import resource_lookup
    >>> ();data = resource_lookup.resource_lookup_dto("pt-br", "ulb", "mat");() # doctest: +ELLIPSIS
    (...)
    >>> data
    ResourceLookupDto(lang_code='pt-br', lang_name='Brazilian Portuguese', localized_lang_name='Português Brasileiro', resource_type='ulb', resource_type_name='Unlocked Literal Bible', book_code='mat', lang_direction=<LangDirEnum.LTR: 'ltr'>, url=HttpUrl('https://content.bibletranslationtools.org/WA-Catalog/pt-br_ulb'))
    """
    data = fetch_source_data()  # Fetch source data
    if data is None:
        return None
    resource_lookup_dto: Optional[ResourceLookupDto] = None
    rg_resource_lookup_dtos: list[ResourceLookupDto] = []
    two_component_url_resource_lookup_dtos: list[ResourceLookupDto] = []
    more_than_two_component_url_resource_lookup_dtos: list[ResourceLookupDto] = []
    try:
        repos_info = data.git_repo
        augmented_repos_info = add_data_not_supplied_by_data_api(repos_info)
        for repo_info in augmented_repos_info:
            content = repo_info.content
            language_info = content.language
            resource_type_ = content.resource_type
            url = repo_info.repo_url
            if language_info.ietf_code == lang_code:
                last_segment = get_last_segment(url, lang_code)
                if last_segment[-4:] == "docx":
                    resource_lookup_dto = ResourceLookupDto(
                        lang_code=lang_code,
                        lang_name=language_info.english_name,
                        localized_lang_name=language_info.national_name,
                        resource_type=resource_type,
                        resource_type_name=resource_type_codes_and_names[resource_type],
                        book_code=book_code,
                        lang_direction=language_info.direction,
                        url=url,
                    )
                    rg_resource_lookup_dtos.append(resource_lookup_dto)
                else:
                    repo_components = last_segment.split("_")
                    repo_components = update_repo_components(repo_components)
                    if len(repo_components) > 2:
                        book_code_ = repo_components[1]
                        if (
                            (book_code_ in str(url) or zmq_git_username in str(url))
                            and resource_type == resource_type_
                            and resource_type_ in resource_type_codes_and_names
                            and book_code_ == book_code
                        ):
                            resource_lookup_dto = ResourceLookupDto(
                                lang_code=lang_code,
                                lang_name=language_info.english_name,
                                localized_lang_name=language_info.national_name,
                                resource_type=resource_type,
                                resource_type_name=resource_type_codes_and_names[
                                    resource_type
                                ],
                                book_code=book_code,
                                lang_direction=language_info.direction,
                                url=url,
                            )
                            more_than_two_component_url_resource_lookup_dtos.append(
                                resource_lookup_dto
                            )
                    elif len(repo_components) == 2 and resource_type == resource_type_:
                        # Handle cases like es-419_ulb, es-419_tn, en_ulb, etc.
                        resource_lookup_dto = ResourceLookupDto(
                            lang_code=lang_code,
                            lang_name=language_info.english_name,
                            localized_lang_name=language_info.national_name,
                            resource_type=resource_type,
                            resource_type_name=resource_type_codes_and_names[
                                resource_type
                            ],
                            book_code=book_code,
                            lang_direction=language_info.direction,
                            url=url,
                        )
                        two_component_url_resource_lookup_dtos.append(
                            resource_lookup_dto
                        )
    except Exception:
        logger.info(
            "Problem creating ResourceLookupDto instance for %s, %s, %s, likely a data problem",
            lang_code,
            resource_type,
            book_code,
        )
    if rg_resource_lookup_dtos:
        resource_lookup_dto = rg_resource_lookup_dtos[0]
    elif more_than_two_component_url_resource_lookup_dtos:
        resource_lookup_dto = more_than_two_component_url_resource_lookup_dtos[0]
    elif two_component_url_resource_lookup_dtos:
        resource_lookup_dto = two_component_url_resource_lookup_dtos[0]
    return resource_lookup_dto


def provision_asset_files(
    url: Optional[HttpUrl],
    resource_filepath: str,
) -> None:
    if url is not None:
        if str(url)[-4:] != "docx":
            clone_git_repo(url, resource_filepath)
        elif str(url)[-4:] == "docx":
            download_rg_file(url, resource_filepath)


def prepare_resource_filepath(
    resource_lookup_dto: ResourceLookupDto,
    working_dir: str = settings.RESOURCE_ASSETS_DIR,
) -> str:
    resource_filepath = ""
    if resource_lookup_dto.url is not None:
        resource_filepath = join(
            working_dir,
            get_last_segment(resource_lookup_dto.url, resource_lookup_dto.lang_code),
        )
    return resource_filepath


def clone_git_repo(
    url: HttpUrl,
    resource_filepath: str,
    branch: Optional[str] = None,
) -> None:
    if branch:  # CLient specified a particular branch
        command = "git clone --depth=1 --branch '{}' '{}' '{}'".format(
            branch, url, resource_filepath
        )
    else:
        command = "git clone --depth=1 '{}' '{}'".format(url, resource_filepath)
    if not isdir(resource_filepath):
        logger.info("Attempting to clone into %s ...", resource_filepath)
        try:
            subprocess.call(command, shell=True)
            logger.info("git command: %s", command)
            logger.info("git clone succeeded.")
        except subprocess.SubprocessError:
            logger.info("git command: %s", command)
            logger.info("git clone failed!")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="git clone failed",
            )


def download_rg_file(
    url: HttpUrl,
    resource_filepath: str,
) -> None:
    # TODO Until data API provides reviewer's guide URL that is
    # downloadable, we provide the reviewer's guide in our build process
    # using directives in our Dockerfile. Downloading the file using curl
    # doesn't work as it is below. There is a way to authenticate to github
    # using curl and download the file, but this requires using an
    # authentication token which would need to be shared via an env var that
    # is not committed to git.
    pass
    # logger.debug("About to download rg file: %s to: %s", url, resource_filepath)
    # make_dir(resource_filepath)
    # command = "curl -L -o '{}/en_rg_nt_survey.docx' '{}'".format(resource_filepath, url)
    # if exists(resource_filepath):
    #     logger.info(
    #         "No need to download file as it already exists: %s", resource_filepath
    #     )
    # else:
    #     logger.debug("Attempting to download file into %s ...", resource_filepath)
    #     try:
    #         subprocess.call(command, shell=True)
    #         logger.debug("curl command: %s", command)
    #         logger.debug("download file succeeded.")
    #     except subprocess.SubprocessError:
    #         logger.debug("curl command: %s", command)
    #         logger.debug("download file failed!")
    #         raise HTTPException(
    #             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    #             detail="download file failed",
    #         )


if __name__ == "__main__":

    # To run the doctests in this module, in the root of the project do:
    # python backend/document/domain/resource_lookup.py
    # or
    # python backend/document/domain/resource_lookup.py -v
    # See https://docs.python.org/3/library/doctest.html
    # for more details.
    import doctest

    doctest.testmod()
