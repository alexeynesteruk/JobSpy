"""Offline end-to-end parser regressions for the 1.4.1 migration."""

import json
import unittest
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from jobspy.hellowork import HelloWork
from jobspy.linkedin import LinkedIn
from jobspy.model import Compensation, CompensationInterval, ScraperInput, Site
from jobspy.ziprecruiter import ZipRecruiter


class Release141Tests(unittest.TestCase):
    def setUp(self):
        for target in (
            "requests.Session.request",
            "curl_cffi.requests.Session.request",
            "socket.create_connection",
        ):
            guard = patch(
                target, side_effect=AssertionError("Live networking forbidden")
            )
            guard.start()
            self.addCleanup(guard.stop)

    def test_linkedin_description_salary_preserves_cents_and_mixed_k_ranges(self):
        for text, low, high, interval in (
            ("Pay: $23.35 - $35.95", 23.35, 35.95, CompensationInterval.HOURLY),
            (
                "Pay: $117,000.35 - $234,000.95",
                117000.35,
                234000.95,
                CompensationInterval.YEARLY,
            ),
            (
                "Pay: $120k - $234,000.95",
                120000,
                234000.95,
                CompensationInterval.YEARLY,
            ),
            (
                "Pay: $117,000.35 - $234k",
                117000.35,
                234000,
                CompensationInterval.YEARLY,
            ),
            ("Pay: $117.35k - $234.95k", 117350, 234950, CompensationInterval.YEARLY),
        ):
            with self.subTest(text=text):
                salary = LinkedIn._guess_salary(text)
                self.assertEqual(
                    (salary.min_amount, salary.max_amount, salary.interval),
                    (low, high, interval),
                )
                self.assertEqual(salary.currency, "USD")

    def test_linkedin_description_salary_refuses_implausible_and_reversed_ranges(self):
        for text in ("$0.5 - $50", "$200k - $100k", "$500k - $900k", "Competitive", ""):
            with self.subTest(text=text):
                self.assertEqual(LinkedIn._guess_salary(text), Compensation())

    def test_hellowork_old_and_new_title_markup_produce_the_same_posting(self):
        board = HelloWork()
        board.scraper_input = ScraperInput(site_name=[Site.HELLOWORK], hours_old=24)
        postings = []
        for tag in ("p", "span"):
            markup = f"""<li data-id-storage-item-id="123">
                <div data-cy="serpCard" data-analytics-values-param="search"></div>
                <a data-cy="offerTitle" aria-label="Engineer temps plein" href="/fr-fr/emplois/123.html">
                <h3><{tag}>Engineer</{tag}><{tag}>Acme</{tag}></h3></a>
                <section><div data-cy="contractCard">CDI</div><div>45 000 - 60 000 € / an</div></section>
                <div data-cy="localisationCard">Paris - 75</div><div>il y a 3 heures</div></li>"""
            posting = board._process_job(BeautifulSoup(markup, "html.parser").li)
            self.assertIsNotNone(posting)
            postings.append(posting.model_dump())
        self.assertEqual(postings[0], postings[1])
        self.assertEqual(
            (postings[0]["title"], postings[0]["company"]), ("Engineer", "Acme")
        )
        self.assertEqual(
            (postings[0]["min_amount"], postings[0]["max_amount"]), (45000, 60000)
        )

    @staticmethod
    def card(second_layout=False, key="fixture-1"):
        return {
            "listingKey": key,
            "title": "Engineer",
            "status": {
                "postedAtUtc": {"seconds": 1792886400}
                if second_layout
                else "2026-10-25T00:00:00Z"
            },
            "employmentTypes": [
                {"name": 1 if second_layout else "EMPLOYMENT_TYPE_NAME_FULL_TIME"}
            ],
            "location": {"countryCode": "CA", "city": "Toronto", "stateCode": "ON"},
            "applyButtonConfig": {},
            "company": {"name": "Acme"},
            "companyUrl": None,
            "rawCanonicalZipJobPageUrl": f"/jobs/acme/{key}",
            "locationTypes": [
                {"name": 2 if second_layout else "LOCATION_TYPE_NAME_REMOTE"}
            ],
            "pay": {
                "metadata": {"visible": True},
                "interval": 5 if second_layout else "PAY_INTERVAL_YEAR",
                "currency": 2 if second_layout else "PAY_CURRENCY_CAD",
                "min": 120000.35,
                "max": 150000.95,
            },
        }

    @staticmethod
    def page(cards, second_layout=False, count=None):
        data = (
            {"jobCards": cards}
            if second_layout
            else {"jobKeysMap": {card["listingKey"]: card for card in cards}}
        )
        data["jobCount"] = len(cards) if count is None else count
        return f"<script>self.__next_f.push([1,{json.dumps('0:' + json.dumps(data, separators=(',', ':')) + chr(10))}])</script>"

    def scrape_zip(self, pages):
        session = MagicMock()
        session.get.side_effect = [
            MagicMock(status_code=200, text=page) for page in pages
        ]
        with (
            patch("jobspy.ziprecruiter.create_session", return_value=session),
            patch("jobspy.ziprecruiter.time.sleep"),
        ):
            board = ZipRecruiter()
            jobs = board.scrape(
                ScraperInput(site_name=[Site.ZIP_RECRUITER], results_wanted=10)
            )
        return jobs, board, session

    def test_ziprecruiter_both_page_layouts_keep_identity_salary_and_location(self):
        postings = []
        for second in (False, True):
            jobs, board, session = self.scrape_zip(
                [self.page([self.card(second)], second)]
            )
            self.assertEqual(len(jobs), 1)
            self.assertIsNone(board.error)
            self.assertEqual(session.get.call_count, 1)
            postings.append(jobs[0].model_dump())
        self.assertEqual(postings[0], postings[1])
        self.assertEqual(postings[0]["id"], "zr-fixture-1")
        self.assertEqual(postings[0]["currency"], "CAD")
        self.assertEqual(postings[0]["min_amount"], 120000.35)
        self.assertEqual(postings[0]["job_type"], "fulltime")
        self.assertTrue(postings[0]["is_remote"])
        self.assertEqual(str(postings[0]["date_posted"]), "2026-10-25")

    def test_ziprecruiter_paging_deduplicates_shared_keys_across_layouts(self):
        jobs, board, session = self.scrape_zip(
            [
                self.page([self.card()], count=21),
                self.page(
                    [self.card(True), self.card(True, "fixture-2")], True, count=21
                ),
            ]
        )
        self.assertEqual([job.id for job in jobs], ["zr-fixture-1", "zr-fixture-2"])
        self.assertEqual(session.get.call_count, 2)
        self.assertIsNone(board.error)

    def test_ziprecruiter_layout_failure_is_an_error_not_an_empty_success(self):
        jobs, board, _ = self.scrape_zip(["<html>unexpected layout</html>"])
        self.assertEqual(jobs, [])
        self.assertTrue(board.error)


if __name__ == "__main__":
    unittest.main()
