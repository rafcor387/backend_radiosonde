import hashlib
import secrets


class InvitationTokenService:
    @staticmethod
    def create():
        raw_token = secrets.token_urlsafe(32)
        return raw_token, InvitationTokenService.hash(raw_token)

    @staticmethod
    def hash(raw_token):
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
