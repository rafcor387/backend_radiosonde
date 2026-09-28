from datetime import date, datetime, time, timezone

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import RadiosondeProfile


class RadiosondeSearchViewTests(APITestCase):
    def setUp(self):
        RadiosondeProfile.objects.create(
            date=date(2018, 5, 14),
            time=time(0, 0),
            observed_at=datetime(2018, 5, 14, 0, 0, tzinfo=timezone.utc),
            bucket="radiosondeos",
            object_key="raw/LPZ/2018/05/14052018-00Z.tsv",
        )
        RadiosondeProfile.objects.create(
            date=date(2018, 5, 14),
            time=time(12, 0),
            observed_at=None,
            bucket="radiosondeos",
            object_key="raw/LPZ/2018/05/14052018-12Z.tsv",
        )
        RadiosondeProfile.objects.create(
            date=date(2018, 5, 15),
            time=None,
            observed_at=None,
            bucket="radiosondeos",
            object_key="raw/LPZ/2018/05/15052018EDT.tsv",
        )

    def test_searches_only_by_requested_date(self):
        response = self.client.get(
            reverse("radiosonde-search"),
            {"date": "2018-05-14"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            [item["profile_id"] for item in response.data["radiosondes"]],
            [1, 2],
        )
        self.assertEqual(
            [item["date"] for item in response.data["radiosondes"]],
            ["2018-05-14", "2018-05-14"],
        )
        self.assertEqual(
            [item["time"] for item in response.data["radiosondes"]],
            ["00:00Z", "12:00Z"],
        )
        self.assertEqual(
            [item["observed_at"] for item in response.data["radiosondes"]],
            ["2018-05-14T00:00:00Z", "2018-05-14T12:00:00Z"],
        )
        self.assertEqual(
            set(response.data["radiosondes"][0]),
            {"profile_id", "date", "time", "observed_at"},
        )

    def test_returns_empty_result_when_date_does_not_exist(self):
        response = self.client.get(
            reverse("radiosonde-search"),
            {"date": "2019-01-01"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"count": 0, "radiosondes": []})

    def test_returns_null_time_and_observed_at_when_both_are_missing(self):
        response = self.client.get(
            reverse("radiosonde-search"),
            {"date": "2018-05-15"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["radiosondes"][0]["date"], "2018-05-15")
        self.assertIsNone(response.data["radiosondes"][0]["time"])
        self.assertIsNone(response.data["radiosondes"][0]["observed_at"])

    def test_rejects_missing_or_invalid_date(self):
        missing = self.client.get(reverse("radiosonde-search"))
        invalid = self.client.get(
            reverse("radiosonde-search"),
            {"date": "14-05-2018"},
        )

        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(invalid.status_code, status.HTTP_400_BAD_REQUEST)

# Create your tests here.
