from datetime import date, datetime, time, timezone
from io import BytesIO
from unittest.mock import Mock, patch

import numpy as np
from botocore.exceptions import ClientError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import RadiosondeProfile, RadiosondeReport
from .services.radiosonde_normalizer import normalize_radiosonde
from .services.radiosonde_source import inspect_radiosonde_source
from .services.radiosonde_skewt import (
    calculate_skewt_diagnostics,
    render_skewt_png,
)
from .services.radiosonde_hodograph import render_hodograph_png
from .services.radiosonde_thermodynamics import (
    analyze_normalized_thermodynamics,
    calculate_thermodynamics,
)
from .services.radiosonde_wind import analyze_normalized_wind
from .services.radiosonde_stability import (
    _convective_potential_axis,
    _parcel_stability_axis,
    _static_stability_axis,
)
from .services.radiosonde_report import _aggregate_summary, generate_report_pdf


VALID_UPLOAD_TSV = b"""Station: 85201 LaPaz
Launch time: 2018-02-01 11:58:49 UTC

time P T TD Height u v
0 626.6 279.20 278.20 4200.0 1.0 2.0
1 620.0 278.50 277.50 4300.0 1.5 2.5
"""


class RadiosondeUploadViewTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=Mock(is_authenticated=True))

    @patch("feature.services.radiosonde_upload.get_r2_client")
    def test_uploads_tsv_and_creates_catalog_record(self, get_client):
        r2 = Mock()
        r2.head_object.side_effect = ClientError(
            {
                "Error": {"Code": "404"},
                "ResponseMetadata": {"HTTPStatusCode": 404},
            },
            "HeadObject",
        )
        r2.put_object.return_value = {"ETag": '"upload-etag"'}
        get_client.return_value = r2
        uploaded = SimpleUploadedFile(
            "01022018EDT.tsv",
            VALID_UPLOAD_TSV,
            content_type="text/tab-separated-values",
        )

        response = self.client.post(
            reverse("radiosonde-upload"),
            {"file": uploaded},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        record = RadiosondeProfile.objects.get()
        self.assertEqual(record.date, date(2018, 2, 1))
        self.assertEqual(record.time, time(12, 0))
        self.assertEqual(
            record.observed_at,
            datetime(2018, 2, 1, 11, 58, 49, tzinfo=timezone.utc),
        )
        self.assertEqual(record.bucket, "radiosondes")
        self.assertEqual(record.object_key, "01022018EDT.tsv")
        self.assertEqual(response.data["profile"]["profile_id"], record.pk)
        self.assertEqual(response.data["profile"]["time"], "12:00Z")
        self.assertEqual(response.data["storage"]["etag"], "upload-etag")
        self.assertTrue(response.data["created"])
        put = r2.put_object.call_args.kwargs
        self.assertEqual(put["Bucket"], "radiosondes")
        self.assertEqual(put["Key"], "01022018EDT.tsv")
        self.assertEqual(put["Body"], VALID_UPLOAD_TSV)

    @patch("feature.services.radiosonde_upload.get_r2_client")
    def test_rejects_duplicate_object_key_without_contacting_r2(self, get_client):
        RadiosondeProfile.objects.create(
            date=date(2018, 2, 1),
            time=time(12, 0),
            bucket="radiosondes",
            object_key="01022018EDT.tsv",
        )
        uploaded = SimpleUploadedFile("01022018EDT.tsv", VALID_UPLOAD_TSV)

        response = self.client.post(
            reverse("radiosonde-upload"),
            {"file": uploaded},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(RadiosondeProfile.objects.count(), 1)
        get_client.assert_not_called()

    @patch("feature.services.radiosonde_upload.get_r2_client")
    def test_rejects_a_different_station_before_contacting_r2(self, get_client):
        uploaded = SimpleUploadedFile(
            "otro.tsv",
            VALID_UPLOAD_TSV.replace(b"85201 LaPaz", b"12345 SantaCruz"),
        )

        response = self.client.post(
            reverse("radiosonde-upload"),
            {"file": uploaded},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(RadiosondeProfile.objects.count(), 0)
        get_client.assert_not_called()

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        uploaded = SimpleUploadedFile("01022018EDT.tsv", VALID_UPLOAD_TSV)

        response = self.client.post(
            reverse("radiosonde-upload"),
            {"file": uploaded},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


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
        self.assertEqual(response.data["count"], 1)
        profile_ids = [
            item["profile_id"] for item in response.data["radiosondes"]
        ]
        self.assertTrue(all(isinstance(profile_id, int) for profile_id in profile_ids))
        self.assertEqual(
            [item["date"] for item in response.data["radiosondes"]],
            ["2018-05-14"],
        )
        self.assertEqual(
            [item["time"] for item in response.data["radiosondes"]],
            ["00:00Z"],
        )
        self.assertEqual(
            [item["observed_at"] for item in response.data["radiosondes"]],
            ["2018-05-14T00:00:00Z"],
        )
        self.assertEqual(
            set(response.data["radiosondes"][0]),
            {"profile_id", "date", "time", "observed_at"},
        )

    def test_searches_requested_time_when_provided(self):
        response = self.client.get(
            reverse("radiosonde-search"),
            {"date": "2018-05-14", "time": "12:00Z"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["radiosondes"][0]["time"], "12:00Z")

    def test_returns_empty_result_when_date_does_not_exist(self):
        response = self.client.get(
            reverse("radiosonde-search"),
            {"date": "2019-01-01"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data,
            {
                "count": 0,
                "radiosondes": [],
            },
        )

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

    def test_rejects_interval_parameters_without_date(self):
        response = self.client.get(
            reverse("radiosonde-search"),
            {"start_date": "2018-05-15", "end_date": "2018-05-14"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class RadiosondeReportTests(APITestCase):
    def setUp(self):
        self.report = RadiosondeReport.objects.create(
            start_date=date(2018, 1, 1),
            end_date=date(2018, 1, 2),
            status=RadiosondeReport.Status.PROCESSING,
            fingerprint="a" * 64,
            report_version="v1",
            bucket="radiosondes",
            filename="informe-prueba.pdf",
            profile_count=2,
        )
        self.rows = [
            {
                "profile_id": 1,
                "date": "2018-01-01",
                "time": "12:00Z",
                "status": "ok",
                "warnings": [],
                "surface_temperature_c": 8.2,
                "surface_relative_humidity_pct": 70.0,
                "sb_cape_j_kg": 25.0,
                "ml_cape_j_kg": 110.0,
                "precipitable_water_mm": 14.0,
                "maximum_wind_ms": 24.0,
                "bulk_shear_0_6km_ms": 12.0,
                "stability_label": "Perfil mixto",
            },
            {
                "profile_id": 2,
                "date": "2018-01-02",
                "time": "12:00Z",
                "status": "partial",
                "warnings": ["Viento no disponible"],
                "surface_temperature_c": 6.0,
                "surface_relative_humidity_pct": 82.0,
                "sb_cape_j_kg": 0.0,
                "ml_cape_j_kg": 0.0,
                "precipitable_water_mm": 12.0,
                "maximum_wind_ms": None,
                "bulk_shear_0_6km_ms": None,
                "stability_label": "Estable",
            },
        ]

    def test_generates_a_valid_pdf_in_memory(self):
        summary = _aggregate_summary(self.rows)
        pdf = generate_report_pdf(self.report, self.rows, summary)

        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 10_000)

    @patch("feature.views.create_radiosonde_report")
    def test_create_endpoint_returns_processing_descriptor(self, create):
        create.return_value = (self.report, False)

        response = self.client.post(
            reverse("radiosonde-report-create"),
            {
                "start_date": "2018-01-01",
                "end_date": "2018-01-02",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["type"], "radiosonde_report")
        self.assertEqual(response.data["status"], "processing")
        self.assertEqual(response.data["report_id"], self.report.pk)
        self.assertIsNone(response.data["view_path"])

    @patch("feature.views.load_report_pdf")
    def test_file_endpoint_serves_ready_pdf_as_download(self, load):
        self.report.status = RadiosondeReport.Status.READY
        self.report.object_key = "derived/reports/v1/test.pdf"
        self.report.size_bytes = 9
        self.report.save()
        load.return_value = (self.report, b"%PDF-test")

        response = self.client.get(
            reverse("radiosonde-report-file", args=[self.report.pk]),
            {"download": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))


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

    @patch("feature.services.radiosonde_source.get_r2_client")
    def test_common_thermodynamic_engine_handles_shallow_profile(self, get_client):
        get_client.return_value.get_object.return_value = {
            "Body": BytesIO(self.tsv),
            "ContentLength": len(self.tsv),
            "ETag": '"test-etag"',
        }
        normalized = normalize_radiosonde(self.profile.pk)

        result = analyze_normalized_thermodynamics(normalized)
        common = calculate_thermodynamics(normalized)

        self.assertEqual(
            result["parcels"]["surface_based"]["origin"]["pressure_hpa"],
            627.5,
        )
        self.assertIsNone(result["parcels"]["surface_based"]["cape_j_kg"])
        self.assertIn("lcl", result["levels"])
        self.assertFalse(result["downdraft"]["available"])
        self.assertEqual(
            common.diagram_diagnostics()["surface_based"]["cape_j_kg"],
            result["parcels"]["surface_based"]["cape_j_kg"],
        )

    @patch("feature.views.analyze_radiosonde_thermodynamics")
    def test_thermodynamics_endpoint_returns_common_diagnostics(self, analyze):
        analyze.return_value = {
            "profile": {"profile_id": self.profile.pk},
            "parcels": {"surface_based": {"cape_j_kg": 0.0}},
            "levels": {"lcl": {"pressure_hpa": 618.0}},
            "indices": {"precipitable_water_mm": 15.7},
            "quality": {"warnings": []},
            "methodology": {"metpy_version": "1.7.1"},
        }

        response = self.client.get(
            reverse(
                "radiosonde-thermodynamics",
                kwargs={"profile_id": self.profile.pk},
            )
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["levels"]["lcl"]["pressure_hpa"],
            618.0,
        )
        analyze.assert_called_once_with(self.profile.pk)

    @patch("feature.views.classify_radiosonde_stability")
    def test_stability_endpoint_returns_explainable_classification(self, classify):
        classify.return_value = {
            "profile": {"profile_id": self.profile.pk},
            "classification": {
                "code": "unstable",
                "label": "Inestable",
                "method": "deterministic_metpy_rules_v1",
                "primary_rule": "convective_energy",
            },
            "metrics": {},
            "rules": {"convective_energy": True},
            "quality": {},
            "methodology": {},
        }

        response = self.client.get(
            reverse("radiosonde-stability", kwargs={"profile_id": self.profile.pk})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["classification"]["code"], "unstable")
        self.assertTrue(response.data["rules"]["convective_energy"])
        classify.assert_called_once_with(self.profile.pk)

    @patch("feature.services.radiosonde_source.get_r2_client")
    def test_renders_skew_t_as_png_in_memory(self, get_client):
        get_client.return_value.get_object.return_value = {
            "Body": BytesIO(self.tsv),
            "ContentLength": len(self.tsv),
            "ETag": '"test-etag"',
        }
        normalized = normalize_radiosonde(self.profile.pk)

        png = render_skewt_png(normalized)

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 1000)

    @patch("feature.services.radiosonde_source.get_r2_client")
    def test_skew_t_diagnostics_expose_energy_levels_and_indices(self, get_client):
        get_client.return_value.get_object.return_value = {
            "Body": BytesIO(self.tsv),
            "ContentLength": len(self.tsv),
            "ETag": '"test-etag"',
        }
        normalized = normalize_radiosonde(self.profile.pk)

        diagnostics = calculate_skewt_diagnostics(normalized)

        self.assertIn("cape_j_kg", diagnostics["surface_based"])
        self.assertIn("cin_j_kg", diagnostics["surface_based"])
        self.assertIn("mixed_layer_50hpa", diagnostics)
        self.assertIn("most_unstable_300hpa", diagnostics)
        self.assertIn("lcl_pressure_hpa", diagnostics["levels"])
        self.assertIn("precipitable_water_mm", diagnostics["indices"])

    @patch("feature.views.get_or_create_skewt")
    def test_skew_t_descriptor_endpoint_returns_relative_paths(self, create_skewt):
        artifact = Mock()
        artifact.descriptor.return_value = {
            "type": "skew_t_diagram",
            "profile": {"profile_id": self.profile.pk},
            "image_path": f"/api/radiosondes/{self.profile.pk}/skew-t/image",
            "download_path": (
                f"/api/radiosondes/{self.profile.pk}/skew-t/image?download=true"
            ),
            "filename": "skew-t-LPZ-2018-02-01-1200Z.png",
        }
        create_skewt.return_value = (artifact, Mock())

        response = self.client.get(
            reverse("radiosonde-skew-t", kwargs={"profile_id": self.profile.pk})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["type"], "skew_t_diagram")
        self.assertTrue(response.data["image_path"].startswith("/api/"))
        self.assertNotIn("image_base64", response.data)

    @patch("feature.views.load_skewt_png")
    def test_skew_t_image_endpoint_supports_download(self, load_png):
        artifact = Mock(
            filename="skew-t-LPZ-2018-02-01-1200Z.png",
            source_sha256="a" * 64,
        )
        load_png.return_value = (artifact, b"\x89PNG\r\n\x1a\ncontent")

        response = self.client.get(
            reverse(
                "radiosonde-skew-t-image",
                kwargs={"profile_id": self.profile.pk},
            ),
            {"download": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    @patch("feature.services.radiosonde_source.get_r2_client")
    def test_renders_hodograph_as_png_in_memory(self, get_client):
        get_client.return_value.get_object.return_value = {
            "Body": BytesIO(self.tsv),
            "ContentLength": len(self.tsv),
            "ETag": '"test-etag"',
        }
        normalized = normalize_radiosonde(self.profile.pk)

        png = render_hodograph_png(normalized)

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 1000)

    @patch("feature.views.get_or_create_hodograph")
    def test_hodograph_descriptor_endpoint_returns_relative_paths(self, create):
        artifact = Mock()
        artifact.descriptor.return_value = {
            "type": "hodograph_diagram",
            "profile": {"profile_id": self.profile.pk},
            "image_path": (
                f"/api/radiosondes/{self.profile.pk}/hodograph/image"
            ),
            "download_path": (
                f"/api/radiosondes/{self.profile.pk}/hodograph/image?download=true"
            ),
            "filename": "hodografo-LPZ-2018-02-01-1200Z.png",
        }
        create.return_value = (artifact, Mock())

        response = self.client.get(
            reverse("radiosonde-hodograph", kwargs={"profile_id": self.profile.pk})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["type"], "hodograph_diagram")
        self.assertTrue(response.data["image_path"].startswith("/api/"))
        self.assertNotIn("image_base64", response.data)

    @patch("feature.views.load_hodograph_png")
    def test_hodograph_image_endpoint_supports_download(self, load_png):
        artifact = Mock(
            filename="hodografo-LPZ-2018-02-01-1200Z.png",
            source_sha256="b" * 64,
        )
        load_png.return_value = (artifact, b"\x89PNG\r\n\x1a\ncontent")

        response = self.client.get(
            reverse(
                "radiosonde-hodograph-image",
                kwargs={"profile_id": self.profile.pk},
            ),
            {"download": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response["Content-Disposition"].startswith("attachment"))
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    @patch("feature.services.radiosonde_source.get_r2_client")
    def test_wind_analysis_handles_a_shallow_profile_transparently(self, get_client):
        get_client.return_value.get_object.return_value = {
            "Body": BytesIO(self.tsv),
            "ContentLength": len(self.tsv),
            "ETag": '"test-etag"',
        }
        normalized = normalize_radiosonde(self.profile.pk)

        result = analyze_normalized_wind(normalized)

        self.assertEqual(result["surface_wind"]["speed_ms"], 2.0)
        self.assertIn("direction_from_deg", result["surface_wind"])
        self.assertFalse(result["layers"]["0_1km"]["available"])
        self.assertFalse(result["storm_motion"]["available"])
        self.assertEqual(result["methodology"]["metpy_version"], "1.7.1")

    @patch("feature.views.analyze_radiosonde_wind")
    def test_wind_endpoint_returns_metpy_diagnostics(self, analyze):
        analyze.return_value = {
            "profile": {"profile_id": self.profile.pk},
            "surface_wind": {
                "speed_ms": 3.0,
                "direction_from_deg": 80.0,
            },
            "layers": {"0_1km": {"available": True}},
            "quality": {"warnings": []},
            "methodology": {"metpy_version": "1.7.1"},
        }

        response = self.client.get(
            reverse("radiosonde-wind", kwargs={"profile_id": self.profile.pk})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["surface_wind"]["speed_ms"], 3.0)
        analyze.assert_called_once_with(self.profile.pk)


class RadiosondeStabilityRulesTests(APITestCase):
    def test_static_stability_reports_mixed_layers_from_n2_sign(self):
        result = _static_stability_axis(np.array([0.0001, -0.0001]))

        self.assertEqual(result["code"], "mixed")
        self.assertEqual(result["stable_fraction"], 0.5)
        self.assertEqual(result["unstable_fraction"], 0.5)

    def test_parcel_stability_uses_consensus_lapse_rate_categories(self):
        result = _parcel_stability_axis(
            np.array([4.0, 7.0, 10.5, 9.8]),
            np.array([5.0, 5.0, 5.0, 5.0]),
        )

        self.assertEqual(result["code"], "mixed")
        self.assertEqual(result["absolutely_stable_fraction"], 0.25)
        self.assertEqual(result["conditionally_unstable_fraction"], 0.25)
        self.assertEqual(result["absolutely_unstable_fraction"], 0.25)
        self.assertEqual(result["neutral_fraction"], 0.25)

    def test_convective_potential_marks_low_positive_cape_as_marginal(self):
        result = _convective_potential_axis(
            {
                "surface_based": {"cape_j_kg": 0.0, "cin_j_kg": 0.0},
                "mixed_layer_50hpa": {
                    "cape_j_kg": 159.569,
                    "cin_j_kg": -8.015,
                },
            }
        )

        self.assertEqual(result["code"], "marginal")
        self.assertTrue(result["cape_positive"])

# Create your tests here.
