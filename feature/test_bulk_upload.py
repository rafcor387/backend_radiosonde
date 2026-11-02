from datetime import date, time
from io import BytesIO
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import RadiosondeProfile
from .tests import VALID_UPLOAD_TSV
from scripts.upload_radiosonde_folder import make_batches, multipart_body


class MemoryR2:
    """Cliente local de prueba: ninguna operación sale a Cloudflare."""

    def __init__(self):
        self.objects = {}
        self.fail_keys = set()
        self.get_calls = 0

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject")
        item = self.objects[Key]
        return {"Metadata": item.get("Metadata", {}), "ContentLength": len(item["Body"])}

    def put_object(self, **kwargs):
        if kwargs["Key"] in self.fail_keys:
            raise ClientError({"Error": {"Code": "InternalError"}}, "PutObject")
        self.objects[kwargs["Key"]] = kwargs
        return {"ETag": '"test-etag"'}

    def get_object(self, Bucket, Key):
        self.get_calls += 1
        item = self.objects[Key]
        return {"Body": BytesIO(item["Body"]), "ContentLength": len(item["Body"])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)


class RadiosondeFolderUploadTests(APITestCase):
    def setUp(self):
        self.client.force_authenticate(user=Mock(is_authenticated=True))
        self.r2 = MemoryR2()
        self.patch_client = patch("feature.services.radiosonde_upload.get_r2_client", return_value=self.r2)
        self.get_client = self.patch_client.start()
        self.addCleanup(self.patch_client.stop)

    def file(self, name, content=VALID_UPLOAD_TSV):
        return SimpleUploadedFile(name, content, content_type="text/tab-separated-values")

    def upload(self, files, year=2018):
        return self.client.post(reverse("radiosonde-folder-upload"), {"year": year, "files": files}, format="multipart")

    def test_uploads_files_with_year_prefix_and_can_read_them_back(self):
        other_day = VALID_UPLOAD_TSV.replace(b"2018-02-01", b"2018-02-02")
        response = self.upload([self.file("primero.tsv"), self.file("segundo.tsv", other_day)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["uploaded"], 2)
        self.assertEqual(response.data["failed"], 0)
        self.assertEqual(set(self.r2.objects), {"2018/primero.tsv", "2018/segundo.tsv"})
        self.assertEqual(RadiosondeProfile.objects.count(), 2)
        profile = RadiosondeProfile.objects.get(object_key="2018/primero.tsv")
        self.assertEqual(profile.bucket, "radiosondes")
        self.assertEqual(profile.date, date(2018, 2, 1))
        self.assertEqual(profile.time, time(12))
        search = self.client.get(reverse("radiosonde-search"), {"date": "2018-02-01"})
        self.assertEqual(search.data["radiosondes"][0]["profile_id"], profile.pk)
        with patch("feature.services.radiosonde_source.get_r2_client", return_value=self.r2):
            readback = self.client.get(reverse("radiosonde-profile", kwargs={"profile_id": profile.pk}))
        self.assertEqual(readback.status_code, 200, readback.data)

    def test_repeating_batch_skips_registered_key(self):
        self.upload([self.file("primero.tsv")])
        response = self.upload([self.file("primero.tsv")])
        self.assertEqual(response.data["uploaded"], 0)
        self.assertEqual(response.data["skipped"], 1)
        self.assertEqual(response.data["results"][0]["reason"], "already_registered")
        self.assertEqual(RadiosondeProfile.objects.count(), 1)

    def test_identical_content_with_another_name_is_not_uploaded_again(self):
        response = self.upload([self.file("a.tsv"), self.file("b.tsv")])
        self.assertEqual(response.data["uploaded"], 1)
        self.assertEqual(response.data["skipped"], 1)
        self.assertEqual(response.data["results"][1]["reason"], "duplicate_content")
        self.assertEqual(response.data["results"][1]["existing_object_key"], "2018/a.tsv")
        self.assertEqual(len(self.r2.objects), 1)

    def test_legacy_root_object_without_hash_is_deduplicated(self):
        profile = RadiosondeProfile.objects.create(
            date=date(2018, 2, 1), time=time(12), bucket="radiosondes", object_key="legacy.tsv",
        )
        self.r2.objects["legacy.tsv"] = {"Body": VALID_UPLOAD_TSV}
        response = self.upload([self.file("otra_copia.tsv")])
        self.assertEqual(response.data["skipped"], 1)
        self.assertEqual(response.data["results"][0]["existing_profile_id"], profile.pk)
        self.assertEqual(self.r2.get_calls, 1)
        self.assertEqual(RadiosondeProfile.objects.count(), 1)

    def test_wrong_year_fails_only_that_file(self):
        response = self.upload([
            self.file("otro_anio.tsv", VALID_UPLOAD_TSV.replace(b"2018-02-01", b"2019-02-01")),
            self.file("correcto.tsv"),
        ])
        self.assertEqual(response.data["uploaded"], 1)
        self.assertEqual(response.data["failed"], 1)
        self.assertEqual(response.data["status"], "completed_with_errors")
        self.assertNotIn("2018/otro_anio.tsv", self.r2.objects)

    def test_storage_failure_rolls_back_one_record_and_continues(self):
        self.r2.fail_keys.add("2018/falla.tsv")
        response = self.upload([
            self.file("falla.tsv"),
            self.file("correcto.tsv", VALID_UPLOAD_TSV.replace(b"2018-02-01", b"2018-02-02")),
        ])
        self.assertEqual(response.data["failed"], 1)
        self.assertEqual(response.data["uploaded"], 1)
        self.assertEqual(list(RadiosondeProfile.objects.values_list("object_key", flat=True)), ["2018/correcto.tsv"])

    def test_orphan_storage_object_is_not_overwritten_or_reported_as_registered(self):
        self.r2.objects["2018/existe.tsv"] = {"Body": b"contenido previo"}
        response = self.upload([self.file("existe.tsv")])
        self.assertEqual(response.data["failed"], 1)
        self.assertEqual(response.data["results"][0]["reason"], "storage_object_without_catalog")
        self.assertEqual(self.r2.objects["2018/existe.tsv"]["Body"], b"contenido previo")
        self.assertEqual(RadiosondeProfile.objects.count(), 0)

    def test_invalid_files_do_not_stop_valid_file(self):
        response = self.upload([
            self.file("incorrecto.txt"), self.file("vacio.tsv", b""),
            self.file("fecha_invalida.tsv", VALID_UPLOAD_TSV.replace(b"2018-02-01", b"2018-02-30")),
            self.file("correcto.tsv"),
        ])
        self.assertEqual(response.data["failed"], 3)
        self.assertEqual(response.data["uploaded"], 1)

    def test_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.upload([self.file("a.tsv")])
        self.assertEqual(response.status_code, 401)
        self.get_client.assert_not_called()

    def test_invalid_year_missing_files_and_batch_limit_are_rejected_before_upload(self):
        for data in [
            {"year": "../2018", "files": [self.file("a.tsv")]},
            {"year": 2018},
            {"year": 2018, "files": [self.file(f"{i}.tsv") for i in range(51)]},
        ]:
            response = self.client.post(reverse("radiosonde-folder-upload"), data, format="multipart")
            self.assertEqual(response.status_code, 400, response.data)
        self.get_client.assert_not_called()

    def test_accepts_another_year_without_specific_year_list(self):
        response = self.upload([self.file("a.tsv", VALID_UPLOAD_TSV.replace(b"2018-02-01", b"2020-02-01"))], year=2020)
        self.assertEqual(response.data["uploaded"], 1)
        self.assertIn("2020/a.tsv", self.r2.objects)

    @patch("feature.serializers.MAX_BULK_BYTES", 1)
    def test_total_batch_size_is_rejected_before_upload(self):
        response = self.upload([self.file("a.tsv")])
        self.assertEqual(response.status_code, 400)
        self.get_client.assert_not_called()

    def test_individual_size_limit_does_not_stop_the_next_file(self):
        with patch("feature.services.radiosonde_upload.MAX_RADIOSONDE_BYTES", len(VALID_UPLOAD_TSV)):
            response = self.upload([
                self.file("grande.tsv", b"x" * (len(VALID_UPLOAD_TSV) + 1)),
                self.file("correcto.tsv"),
            ])
        self.assertEqual(response.data["uploaded"], 1)
        self.assertEqual(response.data["failed"], 1)
        self.assertIn("límite", response.data["results"][0]["detail"])

    def test_folder_client_multipart_is_accepted_by_the_endpoint(self):
        root = Path(__file__).resolve().parents[1] / "output" / "test-tmp"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            path = Path(directory) / "a.tsv"
            path.write_bytes(VALID_UPLOAD_TSV)
            batches = make_batches([path], 20)
            body, content_type = multipart_body(2018, batches[0])
            response = self.client.generic("POST", reverse("radiosonde-folder-upload"), data=body, content_type=content_type)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["uploaded"], 1)
        self.assertIn("2018/a.tsv", self.r2.objects)

    def test_same_launch_with_different_content_is_not_a_hash_duplicate(self):
        response = self.upload([
            self.file("a.tsv"),
            self.file("b.tsv", VALID_UPLOAD_TSV.replace(b"279.20", b"280.20")),
        ])
        self.assertEqual(response.data["uploaded"], 2)
        self.assertEqual(response.data["skipped"], 0)
