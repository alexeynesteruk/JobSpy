import unittest
import logging
from unittest.mock import patch

from jobspy.model import Country, DescriptionFormat, JobType, ScraperInput, Site
from jobspy.util import extract_salary, map_str_to_site


class TestMapStrToSite(unittest.TestCase):
    def test_underscore_site_names(self):
        self.assertEqual(map_str_to_site("zip_recruiter"), Site.ZIP_RECRUITER)
        self.assertEqual(map_str_to_site("linkedin"), Site.LINKEDIN)

    def test_hyphenated_site_names(self):
        self.assertEqual(map_str_to_site("zip-recruiter"), Site.ZIP_RECRUITER)


class TestExtractSalary(unittest.TestCase):
    def test_yearly_range(self):
        interval, min_amt, max_amt, currency = extract_salary("$100,000 - $150,000")
        self.assertEqual(interval, "yearly")
        self.assertEqual(min_amt, 100000)
        self.assertEqual(max_amt, 150000)
        self.assertEqual(currency, "USD")

    def test_k_suffix_range(self):
        interval, min_amt, max_amt, _ = extract_salary("$120k-$180k")
        self.assertEqual(interval, "yearly")
        self.assertEqual(min_amt, 120000)
        self.assertEqual(max_amt, 180000)

    def test_empty_string(self):
        self.assertEqual(extract_salary(""), (None, None, None, None))


class TestDescriptionFormat(unittest.TestCase):
    def test_scraper_input_accepts_string(self):
        scraper_input = ScraperInput(
            site_type=[Site.INDEED], description_format="markdown"
        )
        self.assertEqual(
            scraper_input.description_format, DescriptionFormat.MARKDOWN
        )


class TestIndeedFilterWarnings(unittest.TestCase):
    def test_hours_old_with_is_remote_logs_warning(self):
        from jobspy.indeed import Indeed

        indeed = Indeed()
        indeed.scraper_input = ScraperInput(
            site_type=[Site.INDEED],
            hours_old=24,
            is_remote=True,
            results_wanted=1,
        )
        with self.assertLogs("JobSpy:Indeed", level="WARNING") as log_ctx:
            indeed._build_filters()
        self.assertTrue(
            any("is_remote" in message for message in log_ctx.output),
            "Expected warning about ignored is_remote filter",
        )

    def test_hours_old_with_job_type_and_easy_apply_logs_warning(self):
        from jobspy.indeed import Indeed

        indeed = Indeed()
        indeed.scraper_input = ScraperInput(
            site_type=[Site.INDEED],
            hours_old=48,
            job_type=JobType.FULL_TIME,
            easy_apply=True,
            results_wanted=1,
        )
        with self.assertLogs("JobSpy:Indeed", level="WARNING") as log_ctx:
            indeed._build_filters()
        warning_text = " ".join(log_ctx.output)
        self.assertIn("job_type", warning_text)
        self.assertIn("easy_apply", warning_text)


class TestCountryFromString(unittest.TestCase):
    def test_unknown_country_raises_value_error(self):
        with self.assertRaises(ValueError):
            Country.from_string("jamaica")

    def test_scrape_jobs_invalid_country_falls_back_to_usa(self):
        from jobspy import scrape_jobs
        from jobspy.model import JobResponse

        captured_input = {}

        def mock_scrape(self, scraper_input):
            captured_input["country"] = scraper_input.country
            return JobResponse(jobs=[])

        with self.assertLogs("JobSpy:JobSpy", level="WARNING"):
            with patch("jobspy.indeed.Indeed.scrape", mock_scrape):
                scrape_jobs(
                    site_name="indeed",
                    country_indeed="jamaica",
                    results_wanted=1,
                    verbose=1,
                )

        self.assertEqual(captured_input["country"], Country.USA)


class TestGlassdoorHeaders(unittest.TestCase):
    def test_scrape_copies_module_headers(self):
        from unittest.mock import MagicMock, patch

        from jobspy.glassdoor import Glassdoor
        from jobspy.glassdoor import constant as glassdoor_constant
        from jobspy.model import Country, ScraperInput, Site

        original_token = glassdoor_constant.headers.get("gd-csrf-token")
        glassdoor_constant.headers["gd-csrf-token"] = "sentinel-token"

        scraper = Glassdoor()
        scraper_input = ScraperInput(
            site_type=[Site.GLASSDOOR],
            country=Country.USA,
            search_term="engineer",
            location="New York",
            results_wanted=1,
        )

        try:
            with patch.object(Glassdoor, "_get_csrf_token", return_value="fresh-token"):
                with patch.object(
                    Glassdoor, "_get_location", return_value=(123, "CITY")
                ):
                    with patch.object(
                        Glassdoor, "_fetch_jobs_page", return_value=([], None)
                    ):
                        scraper.scrape(scraper_input)
            self.assertEqual(
                glassdoor_constant.headers.get("gd-csrf-token"), "sentinel-token"
            )
        finally:
            if original_token is None:
                glassdoor_constant.headers.pop("gd-csrf-token", None)
            else:
                glassdoor_constant.headers["gd-csrf-token"] = original_token


if __name__ == "__main__":
    unittest.main()
