"""Export privacy must remove human contacts without changing technical traces."""
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from history_sources.common import contains_private_data, redact, sanitize


class HistoryPrivacyTests(unittest.TestCase):
    def test_email_plain_slack_mailto_unicode_and_encoded_urls(self):
        samples = [
            "Reply to developer+hackathon@example.com",
            "<mailto:person@example.org|person@example.org>",
            "mailto:person%40example%2Eorg",
            "josé@ejemplo.co",
            "https://host.test/invite?email=person%2Bhackathon%40example.org&ref=1234567890",
            "https://host.test/u/person%2540example%252Eorg?ref=abc",
            "person&#64;example&#46;org",
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                safe = redact(sample)
                self.assertNotIn("person", safe)
                self.assertNotIn("developer+hackathon", safe)
                self.assertNotIn("josé@", safe)
                self.assertIn("REDACTED", safe)
        self.assertEqual(redact(samples[4]), "https://host.test/invite?email=%5BREDACTED_EMAIL%5D&ref=1234567890")

    def test_international_colombian_and_us_telephone_formats(self):
        samples = ["+573001234567", "+57 300 123 4567", "(+57) 300-123-4567", "+1 (415) 555-2671", "(415) 555-2671", "415-555-2671", "300 123 4567", "300.123.4567", "+44 20 7946 0958", "+1 415 555 2671 ext. 32"]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(redact("Contact " + sample), "Contact [REDACTED PHONE]")

    def test_bare_digits_need_contact_context(self):
        self.assertEqual(redact("Please call 3001234567."), "Please call [REDACTED PHONE].")
        self.assertEqual(redact("teléfono 3001234567"), "teléfono [REDACTED PHONE]")
        self.assertEqual(redact("Run id 3001234567, local port 43420"), "Run id 3001234567, local port 43420")
        self.assertEqual(redact("phone: 3001234567, port: 43420"), 'phone: "[REDACTED PHONE]", port: 43420')
        self.assertEqual(redact("Call me at 555-2671"), "Call me at [REDACTED PHONE]")
        self.assertEqual(redact("Phone trace: call id 3001234567"), "Phone trace: call id 3001234567")

    def test_explicit_nested_contacts_and_ids_keep_record_shape(self):
        record = {"actor": "Mario", "threadId": "codex:1234567890", "contact": {"email": "person@example.org", "phoneNumber": 3001234567,
            "contact_enabled": True, "home_address": {"line1": "Calle 42 #17-80", "city": "Bogota"}},
            "national_id": "1234567890", "account_number": 1234567890123456, "email_verified": True,
            "address": "127.0.0.1:43420", "country": "Colombia"}
        safe = sanitize(record)
        self.assertEqual(safe["contact"]["email"], "[REDACTED EMAIL]")
        self.assertEqual(safe["contact"]["phoneNumber"], "[REDACTED PHONE]")
        self.assertEqual(safe["contact"]["home_address"], {"line1": "[REDACTED ADDRESS]", "city": "[REDACTED ADDRESS]"})
        self.assertEqual(safe["national_id"], "[REDACTED PERSONAL ID]")
        self.assertEqual(safe["account_number"], "[REDACTED PERSONAL ID]")
        self.assertEqual(safe["actor"], "Mario")
        self.assertEqual(safe["address"], "127.0.0.1:43420")
        self.assertEqual(safe["threadId"], record["threadId"])
        self.assertTrue(safe["email_verified"])
        self.assertEqual(sanitize({"ids": [{"id": "300-123-4567", "email": "person@example.org"}]}),
            {"ids": [{"id": "300-123-4567", "email": "[REDACTED EMAIL]"}]})

    def test_embedded_json_stays_parseable(self):
        text = json.dumps({"email": "person@example.org", "phone": 3001234567, "cedula": "1234567890", "port": 43420, "session_id": "1234567890"})
        safe = json.loads(redact(text))
        self.assertEqual(safe["email"], "[REDACTED EMAIL]")
        self.assertEqual(safe["phone"], "[REDACTED PHONE]")
        self.assertEqual(safe["cedula"], "[REDACTED PERSONAL ID]")
        self.assertEqual(safe["port"], 43420)
        self.assertEqual(safe["session_id"], "1234567890")
        trace = json.dumps({"output": json.dumps({"phone": 3001234567, "email": "person@example.org", "id": "300-123-4567"})})
        nested = json.loads(json.loads(redact(trace))["output"])
        self.assertEqual(nested["phone"], "[REDACTED PHONE]")
        self.assertEqual(nested["id"], "300-123-4567")
        self.assertEqual(nested["email"], "[REDACTED EMAIL]")
        schema = {"properties": {"phone": {"type": ["string", "null"]}, "email": {"type": "string", "format": "email"}}}
        self.assertEqual(sanitize(schema), schema)
        ordinary_json = '{"id":"300-123-4567", "ports": [43420]}'
        self.assertEqual(redact(ordinary_json), ordinary_json)

    def test_human_addresses_and_national_ids_require_explicit_meaning(self):
        text = 'home_address="123 Main Street Apt 4"; cedula=1234567890; machine_id="1234567890"'
        safe = redact(text)
        self.assertNotIn("123 Main Street", safe)
        self.assertNotIn("cedula=1234567890", safe)
        self.assertIn('machine_id="1234567890"', safe)
        self.assertEqual(redact("Mi cédula es 1.234.567.890"), "Mi cédula es [REDACTED PERSONAL ID]")
        self.assertEqual(sanitize({"address": {"street": "Main Street", "city": "Bogota", "postal_code": "12345"}}),
            {"address": {"street": "[REDACTED ADDRESS]", "city": "[REDACTED ADDRESS]", "postal_code": "[REDACTED ADDRESS]"}})

    def test_timestamp_sha_ports_versions_ips_and_program_symbols_are_unchanged(self):
        values = [
            "2026-10-02T08:00:00.123456789+00:00", "1790831126342", "1790831126.342", "127.0.0.1:43420", "192.168.100.100",
            "abc1234567890def1234567890abc1234567890def12", "01a0fa21-5f36-72d1-9395-b9385c1968d3", "v1.2.3+2026100200",
            "version 300.123.4567", "ref=1234567890&port=43420", "git@github.com:owner/repo.git",
            "const phone: string = process.env.CONTACT_PHONE;", "phone=$taskPhone; email=person.email; national_id=None",
            'machine_id="300-123-4567"; version="300.123.4567"',
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(redact(value), value)
        record = {"id": "300-123-4567", "timestamp": "2026-10-02T08:00:00Z", "evidenceEventIds": ["300-123-4567"], "metadata": {"phone": None, "mobile": True}}
        self.assertEqual(sanitize(record), record)

    def test_encoded_contact_query_fields_do_not_remove_other_parameters(self):
        value = "https://host.test/r?phone=%2B573001234567&document_number=1234567890&commit=abc123&email_verified=true"
        safe = redact(value)
        self.assertEqual(safe, "https://host.test/r?phone=%5BREDACTED_PHONE%5D&document_number=%5BREDACTED_PERSONAL_ID%5D&commit=abc123&email_verified=true")

    def test_redaction_is_idempotent_and_credentials_still_removed(self):
        value = {"body": "Reach person@example.org or +573001234567", "api_key": "synthetic-secret", "password": "synthetic-password", "actor": "Mario"}
        once = sanitize(value)
        self.assertEqual(sanitize(once), once)
        self.assertEqual(once["api_key"], "[REDACTED]")
        self.assertEqual(once["password"], "[REDACTED]")
        self.assertEqual(once["actor"], "Mario")

    def test_phone_uris_and_ocr_detection_share_the_same_rules(self):
        for value in ("tel:%2B573001234567", "tel:+573001234567", "sms:%252B573001234567", "https://wa.me/573001234567"):
            with self.subTest(value=value):
                self.assertTrue(contains_private_data(value))
                self.assertNotIn("573001234567", redact(value))
        self.assertFalse(contains_private_data("Mario · GitHub · 127.0.0.1:43420 · 2026-10-02T08:00:00Z"))
        self.assertTrue(contains_private_data("person@example.org"))
        self.assertIn("REDACTED PERSONAL ID", redact("passport: A123456789"))


if __name__ == "__main__":
    unittest.main()
