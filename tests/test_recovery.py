"""تست بازیابی رمز (چالش–پاسخ)."""

import pytest

from nabz.recovery import make_challenge, response_for, verify_response


class TestChallenge:
    def test_challenge_length_and_alphabet(self):
        c = make_challenge()
        assert len(c) == 6
        assert all(ch in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" for ch in c)

    def test_challenges_are_random(self):
        codes = {make_challenge() for _ in range(50)}
        assert len(codes) > 40  # عملاً همه متفاوت

    def test_no_ambiguous_characters(self):
        # نباید I O 0 1 داشته باشد (برای خواندن تلفنی)
        for _ in range(50):
            c = make_challenge()
            assert not (set(c) & set("IO01"))


class TestResponse:
    def test_response_length(self):
        assert len(response_for("ABCDEF")) == 8

    def test_response_is_deterministic(self):
        assert response_for("ABCDEF") == response_for("ABCDEF")

    def test_case_insensitive(self):
        assert response_for("abcdef") == response_for("ABCDEF")

    def test_different_challenge_different_response(self):
        assert response_for("ABCDEF") != response_for("GHJKLM")


class TestVerify:
    def test_correct_response_verifies(self):
        c = make_challenge()
        assert verify_response(c, response_for(c))

    def test_wrong_response_rejected(self):
        c = make_challenge()
        assert not verify_response(c, "WRONGXYZ")

    def test_verify_tolerates_spaces_and_dashes(self):
        c = "ABCDEF"
        r = response_for(c)
        spaced = "-".join(r[i:i+2] for i in range(0, len(r), 2))
        assert verify_response(c, spaced)

    def test_verify_case_insensitive(self):
        c = "ABCDEF"
        assert verify_response(c, response_for(c).lower())

    def test_empty_response_rejected(self):
        assert not verify_response("ABCDEF", "")


class TestSecurity:
    def test_response_depends_on_secret(self):
        """اگر کلید عوض شود، پاسخ عوض می‌شود (تضمین اینکه فقط سازنده بسازد)."""
        import nabz.recovery as rec
        original = rec.RECOVERY_SECRET
        r1 = response_for("ABCDEF")
        try:
            rec.RECOVERY_SECRET = b"different-secret"
            r2 = response_for("ABCDEF")
        finally:
            rec.RECOVERY_SECRET = original
        assert r1 != r2
