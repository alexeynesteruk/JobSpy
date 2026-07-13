import unittest
import logging

from jobspy.model import DescriptionFormat, ScraperInput, Site
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


if __name__ == "__main__":
    unittest.main()
