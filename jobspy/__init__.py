from __future__ import annotations

import logging
import warnings
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import get_args

import pandas as pd
from pydantic import ValidationError

from jobspy.bayt import Bayt
from jobspy.bdjobs import BDJobs
from jobspy.glassdoor import Glassdoor
from jobspy.google import Google
from jobspy.hellowork import HelloWork
from jobspy.indeed import Indeed
from jobspy.linkedin import LinkedIn
from jobspy.model import (
    Country,
    DescriptionFormat,
    JobPost,
    JobType,
    Scraper,
    ScraperInput,
    Site,
)
from jobspy.naukri import Naukri
from jobspy.util import (
    configure_logging,
)
from jobspy.ziprecruiter import ZipRecruiter

BaytScraper = Bayt
__all__ = [
    "scrape_jobs",
    "BDJobs",
    "BaytScraper",
    "Glassdoor",
    "Google",
    "Indeed",
    "LinkedIn",
    "Naukri",
    "ZipRecruiter",
]

SCRAPER_MAPPING: dict[Site, type[Scraper]] = {
    Site.LINKEDIN: LinkedIn,
    Site.INDEED: Indeed,
    Site.ZIP_RECRUITER: ZipRecruiter,
    Site.GLASSDOOR: Glassdoor,
    Site.GOOGLE: Google,
    Site.BAYT: Bayt,
    Site.NAUKRI: Naukri,
    Site.BDJOBS: BDJobs,
    Site.HELLOWORK: HelloWork,
}

column_types = {
    name: {
        str: "str",
        float: "float64",
        int: "int64",
        bool: "bool",
        date: "object",
    }.get((get_args(field.annotation) or (field.annotation,))[0], "str")
    for name, field in JobPost.model_fields.items()
}


def scrape_jobs(
    site_name: str | Site | Iterable[str | Site] | None = None,
    search_term: str | None = None,
    google_search_term: str | None = None,
    location: str | None = None,
    distance: int | None = 50,
    is_remote: bool | None = False,
    job_type: str | JobType | None = None,
    easy_apply: bool | None = None,
    results_wanted: int | None = 15,
    country_indeed: str | Country | None = "usa",
    proxies: str | Iterable[str] | None = None,
    ca_cert: str | Path | None = None,
    description_format: str | DescriptionFormat | None = "markdown",
    linkedin_fetch_description: bool | None = False,
    linkedin_company_ids: Iterable[int] | None = None,
    offset: int | None = 0,
    hours_old: int | None = None,
    enforce_annual_salary: bool | None = False,
    verbose: int | None = 1,
    user_agent: str | None = None,
    fetch_description: bool | None = False,
) -> pd.DataFrame:
    """
    Scrapes job data from job boards concurrently
    :param linkedin_fetch_description: Deprecated since 1.2.0: use fetch_description;
        will be removed in 2.0.
    :return: Pandas DataFrame containing job data
    :raises ValueError: an argument is invalid
    """
    arguments = dict(locals())
    # Carry forward the reviewed fork's string normalization and country
    # fallback while keeping upstream's validation for all other arguments.
    if isinstance(description_format, str):
        arguments["description_format"] = description_format.lower()
    if isinstance(site_name, str):
        arguments["site_name"] = site_name.strip().lower().replace("-", "_")
    elif isinstance(site_name, Iterable):
        arguments["site_name"] = [
            name.strip().lower().replace("-", "_") if isinstance(name, str) else name
            for name in site_name
        ]
    country_fallback = False
    if isinstance(country_indeed, str) and country_indeed:
        try:
            arguments["country_indeed"] = Country(country_indeed)
        except ValueError:
            arguments["country_indeed"] = Country.USA
            country_fallback = True
    try:
        scraper_input = ScraperInput.model_validate(
            {
                name: value
                for name, value in arguments.items()
                if not (value is None or isinstance(value, str) and not value)
            }
        )
    except ValidationError as e:
        messages = []
        for error in e.errors():
            name, value = error["loc"][0], error["input"]
            shown = type(value).__name__ if name == "proxies" else repr(value)
            messages.append(f"Invalid {name}: {shown}. {error['msg']}")
        raise ValueError("; ".join(messages)) from None
    if scraper_input.linkedin_fetch_description:
        warnings.warn(
            "linkedin_fetch_description is deprecated; use fetch_description",
            DeprecationWarning,
            stacklevel=2,
        )
    configure_logging(None if verbose is None else scraper_input.verbose)
    if country_fallback:
        logging.getLogger(__name__).warning(
            "Unsupported country_indeed. Defaulting to USA."
        )

    def scrape_site(site: Site) -> tuple[str, Scraper, list[JobPost]]:
        scraper = SCRAPER_MAPPING[site]()
        scraped_data = scraper.scrape(scraper_input)
        scraper.log.info("finished scraping")
        return site.value, scraper, scraped_data

    with ThreadPoolExecutor() as executor:
        results = list(
            executor.map(scrape_site, dict.fromkeys(scraper_input.site_name))
        )

    rows = [
        (job.annualised() if scraper_input.enforce_annual_salary else job).model_copy(
            update={"site": site}
        )
        for site, _, jobs in results
        for job in jobs
    ]

    jobs_df = pd.DataFrame(
        [job.model_dump() for job in rows], columns=list(JobPost.model_fields)
    )
    if rows:
        jobs_df = jobs_df.sort_values(
            by=["site", "date_posted"], ascending=[True, False]
        ).reset_index(drop=True)
    else:
        jobs_df = jobs_df.astype(column_types)
    jobs_df.attrs = {
        "errors": {site: s.error for site, s, _ in results if s.error},
        "warnings": {site: s.warnings for site, s, _ in results if s.warnings},
    }
    return jobs_df
