import unittest
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from jobspy.bdjobs import BDJobs
from jobspy.model import ScraperInput, Site


class TestBDJobsJobDetails(unittest.TestCase):
    def test_jobcontent_without_responsibilities_heading_does_not_raise(self):
        scraper = BDJobs()
        scraper.scraper_input = ScraperInput(site_type=[Site.BDJOBS])
        html = """
        <div class="jobcontent">
            <h4 id="other">Requirements</h4>
            <p>Some requirement text</p>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")

        with patch.object(scraper.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, text=html)
            details = scraper._get_job_details("https://jobs.bdjobs.com/jobdetail.asp?jobid=1")

        self.assertIsInstance(details, dict)
        self.assertIn("description", details)


if __name__ == "__main__":
    unittest.main()
