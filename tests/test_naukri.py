import unittest

from jobspy.model import DescriptionFormat, ScraperInput, Site
from jobspy.naukri import Naukri


class TestNaukriDescription(unittest.TestCase):
    def test_description_falls_back_to_legacy_field(self):
        scraper = Naukri()
        scraper.scraper_input = ScraperInput(
            site_type=[Site.NAUKRI], description_format=DescriptionFormat.HTML
        )

        job = {
            "title": "Software Engineer",
            "companyName": "Acme",
            "description": "<p>Legacy description body</p>",
            "placeholders": [],
            "jdURL": "/job-listings-software-engineer",
        }

        job_post = scraper._process_job(job, "12345")

        self.assertIsNotNone(job_post)
        self.assertEqual(job_post.description, "<p>Legacy description body</p>")

    def test_job_description_field_takes_precedence(self):
        scraper = Naukri()
        scraper.scraper_input = ScraperInput(
            site_type=[Site.NAUKRI], description_format=DescriptionFormat.HTML
        )

        job = {
            "title": "Software Engineer",
            "companyName": "Acme",
            "jobDescription": "<p>Primary description</p>",
            "description": "<p>Legacy description</p>",
            "placeholders": [],
            "jdURL": "/job-listings-software-engineer",
        }

        job_post = scraper._process_job(job, "12345")

        self.assertEqual(job_post.description, "<p>Primary description</p>")


if __name__ == "__main__":
    unittest.main()
