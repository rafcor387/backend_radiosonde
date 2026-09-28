from datetime import date, datetime, time, timezone
from io import BytesIO
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import RadiosondeProfile
from .services.radiosonde_normalizer import normalize_radiosonde
from .services.radiosonde_source import inspect_radiosonde_source


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
        profile_ids = [
            item["profile_id"] for item in response.data["radiosondes"]
        ]
        self.assertTrue(all(isinstance(profile_id, int) for profile_id in profile_ids))
        self.assertEqual(profile_ids[1], profile_ids[0] + 1)
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


class RadiosondeSourceLoaderTests(APITestCase):
    def setUp(self):
        self.profile = RadiosondeProfile.objects.create(
            date=date(2018, 2, 1),
            time=time(12, 0),
            observed_at=None,
            bucket="radiosondes",
            object_key="01022018EDT.tsv",
        )
        self.tsv = b"""Information about sounding:
Station:                  85201 LaPaz
Launch time:              2018-02-01 11:58:49 UTC

     time       T      RH       v       u   Height       P      TD      MR
     0.00  279.20      88    0.00    2.00     4065  627.50  277.30    8.21
     2.00  278.60      97    1.72   -0.02     4161  620.20  278.10    8.76
"""

    @patch("feature.services.radiosonde_source.get_r2_client")
    def test_downloads_catalog_object_and_inspects_edt_header(self, get_client):
        get_client.return_value.get_object.return_value = {
            "Body": BytesIO(self.tsv),
            "ContentLength": len(self.tsv),
            "ETag": '"test-etag"',
        }

        result = inspect_radiosonde_source(self.profile.pk)

        get_client.return_value.get_object.assert_called_once_with(
            Bucket="radiosondes",
            Key="01022018EDT.tsv",
        )
        self.assertEqual(result["profile"]["profile_id"], self.profile.pk)
        self.assertEqual(result["source"]["station"], "85201 LaPaz")
        self.assertEqual(result["source"]["launch_time"], "2018-02-01T11:58:49Z")
        self.assertEqual(result["source"]["rows"], 2)
        self.assertEqual(result["source"]["surface_pressure_hpa"], 627.5)
        self.assertEqual(result["catalog_match"]["date"], True)
        self.assertEqual(result["catalog_match"]["synoptic_hour"], True)
        self.assertEqual(result["warnings"], [])

    @patch("feature.services.radiosonde_source.get_r2_client")
    def test_normalizes_profile_and_returns_general_response(self, get_client):
        get_client.return_value.get_object.return_value = {
            "Body": BytesIO(self.tsv),
            "ContentLength": len(self.tsv),
            "ETag": '"test-etag"',
        }

        normalized = normalize_radiosonde(self.profile.pk)
        result = normalized.general_response()

        self.assertEqual(result["profile"]["profile_id"], self.profile.pk)
        self.assertEqual(result["coverage"]["levels"], 2)
        self.assertEqual(result["coverage"]["surface_pressure_hpa"], 627.5)
        self.assertEqual(result["coverage"]["top_pressure_hpa"], 620.2)
        self.assertEqual(result["surface"]["temperature_c"], 6.05)
        self.assertTrue(result["quality"]["pressure_strictly_decreasing"])
        self.assertTrue(result["quality"]["height_strictly_increasing"])

    @patch("feature.services.radiosonde_source.get_r2_client")
    def test_profile_endpoint_returns_normalized_summary(self, get_client):
        get_client.return_value.get_object.return_value = {
            "Body": BytesIO(self.tsv),
            "ContentLength": len(self.tsv),
            "ETag": '"test-etag"',
        }

        response = self.client.get(
            reverse("radiosonde-profile", kwargs={"profile_id": self.profile.pk})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["profile"]["profile_id"], self.profile.pk)
        self.assertIn("quality", response.data)
        self.assertIn("coverage", response.data)
        self.assertIn("surface", response.data)
        self.assertIn("top", response.data)

# Create your tests here.
