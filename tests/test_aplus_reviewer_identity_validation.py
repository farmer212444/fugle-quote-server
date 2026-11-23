"""Regression tests for formal A+ reviewer identity validation."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from tw_model_v880.evidence import verify_certificate_archives


class ReviewerIdentityValidationTests(unittest.TestCase):
    def test_rejects_missing_blank_or_invalid_reviewer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "original.pdf").write_bytes(b"official-source-fixture")
            source = {
                "archive_path": "original.pdf",
                "sha256": hashlib.sha256(b"official-source-fixture").hexdigest(),
            }
            gate = {
                "status": "PASS",
                "issuer": "2330",
                "original_archive_sha256_recomputed": True,
                "human_source_identity_review_documented": True,
                "sources": [source],
            }
            for reviewer in (None, "", " ", "AB", 123, [], {}):
                with self.subTest(reviewer=reviewer):
                    gate["reviewed_by"] = reviewer
                    with self.assertRaisesRegex(ValueError, "CERTIFICATE_REVIEWER_OR_ISSUER_INVALID"):
                        verify_certificate_archives({
                            "code": "2330",
                            "gates": {"original_eight_quarter_statements": gate},
                        }, root)

    def test_valid_reviewer_and_original_hash_are_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = b"official-source-fixture"
            (root / "original.pdf").write_bytes(payload)
            self.assertTrue(verify_certificate_archives({
                "code": "2330",
                "gates": {
                    "original_eight_quarter_statements": {
                        "status": "PASS",
                        "issuer": "2330",
                        "reviewed_by": "auditor-001",
                        "original_archive_sha256_recomputed": True,
                        "human_source_identity_review_documented": True,
                        "sources": [{
                            "archive_path": "original.pdf",
                            "sha256": hashlib.sha256(payload).hexdigest(),
                        }],
                    },
                },
            }, root))


if __name__ == "__main__":
    unittest.main()
