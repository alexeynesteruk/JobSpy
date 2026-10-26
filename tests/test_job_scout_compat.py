"""Offline semantic carry-forward checks for Job Scout's two fork commits."""

import logging
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import jobspy
from jobspy import scrape_jobs
from jobspy.bdjobs import BDJobs
from jobspy.bdjobs.model import Details
from jobspy.glassdoor.constant import headers as glassdoor_headers
from jobspy.indeed import Indeed
from jobspy.linkedin import LinkedIn
from jobspy.model import (
    Compensation,
    CompensationInterval,
    Country,
    DescriptionFormat,
    JobPost,
    JobType,
    Location,
    Scraper,
    ScraperInput,
    Site,
)
from jobspy.naukri import Naukri
from jobspy.util import RequestsRotating, create_session, plain_converter


class OfflineTests(unittest.TestCase):
    def setUp(self):
        # A fixture mistake must fail rather than use a real board or proxy.
        for target in (
            "requests.Session.request",
            "curl_cffi.requests.Session.request",
        ):
            guard = patch(
                target, side_effect=AssertionError("Live networking forbidden")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def scrape_with_capture(self, **kwargs):
        inputs = []

        class Empty(Scraper):
            def scrape(self, scraper_input):
                inputs.append(scraper_input)
                return []

        with patch.dict(jobspy.SCRAPER_MAPPING, {site: Empty for site in Site}):
            frame = scrape_jobs(**kwargs)
        return frame, inputs

    def test_country_fallback_is_retained_without_logging_untrusted_value(self):
        with self.assertLogs("jobspy", logging.WARNING) as capture:
            _, inputs = self.scrape_with_capture(
                site_name="indeed", country_indeed="invalid CANARY_PROXY_PASSWORD"
            )
        self.assertEqual(inputs[0].country_indeed, Country.USA)
        self.assertIn("Defaulting to USA", " ".join(capture.output))
        self.assertNotIn("CANARY_PROXY_PASSWORD", " ".join(capture.output))

    def test_site_and_description_format_normalization_is_preserved(self):
        _, inputs = self.scrape_with_capture(
            site_name=" ZIP-RECRUITER ", description_format="HTML"
        )
        self.assertEqual(inputs[0].site_name, [Site.ZIP_RECRUITER])
        self.assertEqual(inputs[0].description_format, DescriptionFormat.HTML)
        _, inputs = self.scrape_with_capture(site_name=[" LINKEDIN ", "zip-recruiter"])
        self.assertEqual(len(inputs), 2)

    def test_site_helper_and_public_exports_are_retained(self):
        from jobspy.util import map_str_to_site

        self.assertEqual(map_str_to_site(" Zip-Recruiter "), Site.ZIP_RECRUITER)
        self.assertIs(jobspy.BaytScraper, jobspy.Bayt)
        self.assertTrue(
            {"scrape_jobs", "BDJobs", "BaytScraper", "LinkedIn", "Naukri"}.issubset(
                jobspy.__all__
            )
        )

    def test_invalid_other_arguments_keep_upstream_validation(self):
        for args in (
            {"results_wanted": -1},
            {"site_name": 42},
            {"description_format": "invalid"},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.scrape_with_capture(**args)

    def test_description_format_and_linkedin_legacy_fetch_flag_remain_compatible(self):
        with self.assertWarns(DeprecationWarning):
            _, inputs = self.scrape_with_capture(
                site_name="linkedin", linkedin_fetch_description=True
            )
        self.assertTrue(inputs[0].fetch_description)
        self.assertEqual(plain_converter("<p>Hello <b>world</b></p>"), "Hello world")
        self.assertIsNone(plain_converter(None))

    def test_indeed_filters_are_combined_instead_of_silently_ignored(self):
        board = Indeed()
        board.scraper_input = ScraperInput(
            site_name=[Site.INDEED],
            hours_old=24,
            is_remote=True,
            job_type=JobType.FULL_TIME,
            easy_apply=True,
        )
        filters = board._build_filters()
        for token in ("24h", "DESKTOP", "attributes"):
            self.assertIn(token, filters)
        self.assertEqual(board.warnings, [])

    def test_linkedin_filter_combination_warning_is_retained(self):
        board = LinkedIn()
        board.scraper_input = ScraperInput(
            site_name=[Site.LINKEDIN], hours_old=24, easy_apply=True
        )
        with self.assertLogs("jobspy.linkedin", logging.WARNING):
            params = board._search_params()
        self.assertEqual(params["f_TPR"], "r86400")
        self.assertEqual(params["f_AL"], "true")
        self.assertIn("easy_apply", board.warnings[0])

    def test_single_linkedin_salary_is_retained_and_malformed_text_never_crashes(self):
        for text in ("$120,000+", "$120,000.00/yr"):
            with self.subTest(text=text):
                pay = LinkedIn._parse_salary(text)
                self.assertEqual(
                    (pay.min_amount, pay.max_amount, pay.currency, pay.interval),
                    (120000, 120000, "USD", CompensationInterval.YEARLY),
                )
        for text in ("Negotiable", "Competitive", "", "$", "$,,,+"):
            self.assertEqual(LinkedIn._parse_salary(text), Compensation())
        pay = LinkedIn._parse_salary("$117,000.35/yr - $234,000.95/yr")
        self.assertEqual((pay.min_amount, pay.max_amount), (117000.35, 234000.95))

    def test_user_agent_and_glassdoor_header_isolation_under_concurrency(self):
        original = dict(glassdoor_headers)

        def session_for(index):
            user_agent = f"JobScout fixture {index}"
            session = create_session(
                RequestsRotating(),
                ScraperInput(user_agent=user_agent),
                glassdoor_headers,
            )
            session.headers["gd-csrf-token"] = f"session-{index}"
            return session.headers["user-agent"], session.headers["gd-csrf-token"]

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(session_for, range(20)))
        self.assertEqual(glassdoor_headers, original)
        self.assertEqual(
            results,
            [(f"JobScout fixture {index}", f"session-{index}") for index in range(20)],
        )

    def naukri_job(self, **changes):
        return {
            "jobId": "123",
            "createdDate": 0,
            "companyApplyJob": False,
            "title": "Software Engineer",
            "companyName": "Acme",
            "staticUrl": None,
            "jdURL": "/job/123",
            "logoPathV3": None,
            "placeholders": [
                {"type": "location", "label": "Remote"},
                {"type": "salary", "label": "Not disclosed"},
            ],
            "salaryDetail": {
                "hideSalary": True,
                "minimumSalary": None,
                "maximumSalary": None,
                "currency": None,
            },
            "employmentType": "Full Time",
            **changes,
        }

    def test_naukri_inline_description_precedence_and_legacy_fallback_are_retained(
        self,
    ):
        board = Naukri()
        board.scraper_input = ScraperInput(
            site_name=[Site.NAUKRI], description_format=DescriptionFormat.HTML
        )
        for fields, expected in [
            ({"description": "<p>Legacy</p>"}, "<p>Legacy</p>"),
            (
                {"description": "<p>Legacy</p>", "jobDescription": "<p>Primary</p>"},
                "<p>Primary</p>",
            ),
        ]:
            with self.subTest(fields=fields):
                self.assertEqual(
                    board._process_job(self.naukri_job(**fields)).description, expected
                )

    def test_naukri_explicit_details_enrich_inline_description_and_preserve_it_on_failure(
        self,
    ):
        board = Naukri()
        board.scraper_input = ScraperInput(
            site_name=[Site.NAUKRI],
            fetch_description=True,
            description_format=DescriptionFormat.HTML,
        )
        for details, expected in [
            ((0, {"description": "<p>Full</p>"}), "<p>Full</p>"),
            (None, "<p>Inline</p>"),
        ]:
            with (
                self.subTest(details=details),
                patch.object(board, "_fetch_details", return_value=details),
            ):
                self.assertEqual(
                    board._process_job(
                        self.naukri_job(jobDescription="<p>Inline</p>")
                    ).description,
                    expected,
                )

    def test_bdjobs_missing_description_sections_is_safe_in_upstream_json_parser(self):
        board = BDJobs()
        board.scraper_input = ScraperInput(site_name=[Site.BDJOBS])
        details = {name: None for name in Details.model_fields}
        details.update(CompanyWeb="", ApplyURL="", CompanyID="0")
        board.session = MagicMock()
        board.session.get.return_value = MagicMock(status_code=200)
        board.session.get.return_value.json.return_value = {"data": [details]}
        result = board._fetch_details("123")
        self.assertIn("description", result)
        self.assertIsNone(result["description"])

    def test_dataframe_contract_and_structured_failure_metadata_survive(self):
        class Working(Scraper):
            def scrape(self, scraper_input):
                return [
                    JobPost(
                        job_url="https://example.com/job/1",
                        title="Engineer",
                        company="Acme",
                        location=Location(city="Toronto", country=Country.CANADA),
                        min_amount=123.45,
                        max_amount=234.56,
                        interval=CompensationInterval.HOURLY,
                        currency="CAD",
                    )
                ]

        class Failed(Scraper):
            def scrape(self, scraper_input):
                self.fail("Fixture failure")
                return []

        with patch.dict(
            jobspy.SCRAPER_MAPPING, {Site.INDEED: Working, Site.LINKEDIN: Failed}
        ):
            frame = scrape_jobs(site_name=["indeed", "linkedin"], verbose=0)
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["company"], "Acme")
        self.assertEqual(frame.iloc[0]["location"], "Toronto, Canada")
        self.assertEqual(frame.iloc[0]["min_amount"], 123.45)
        self.assertEqual(frame.attrs["errors"], {"linkedin": "Fixture failure"})

    def test_process_control_exceptions_are_never_swallowed(self):
        board = LinkedIn()
        board.session = MagicMock()
        board.session.get.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            board._fetch_details("123")


if __name__ == "__main__":
    unittest.main()
