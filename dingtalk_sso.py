"""DingTalk web SSO via OAuth2 authorization-code flow.

Flow
----
1. Browser opens ``/auth/dingtalk/login`` -> we redirect to the DingTalk
   authorization page (user scans the QR code and consents).
2. DingTalk redirects back to ``/auth/dingtalk/callback?code=...&state=...``.
3. We exchange the code for a userAccessToken and then fetch the user profile
   (openId is stable and unique per application and is used as the identity).

Reference: https://open.dingtalk.com/document/ (login / OAuth2 / user info).
"""
import logging
import urllib.parse

import aiohttp

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://login.dingtalk.com/oauth2/auth"
TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"
USERINFO_URL = "https://api.dingtalk.com/v1.0/contact/users/me"


class DingTalkSSOError(Exception):
    """Raised when the OAuth handshake fails."""


class DingTalkSSO:
    def __init__(self, client_id, client_secret, timeout=15):
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout

    def build_authorize_url(self, redirect_uri, state):
        """The URL the user is redirected to in order to scan & consent."""
        params = {
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "prompt": "consent",
        }
        return AUTHORIZE_URL + "?" + urllib.parse.urlencode(params)

    async def exchange_profile(self, code):
        """Exchange an authorization code for a normalized profile dict.

        Returns keys: open_id, union_id, nick, avatar, email.
        """
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        # trust_env=True honors HTTP(S)_PROXY env vars.
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            try:
                async with session.post(
                    TOKEN_URL,
                    json={
                        "clientId": self.client_id,
                        "clientSecret": self.client_secret,
                        "code": code,
                        "grantType": "authorization_code",
                    },
                ) as resp:
                    token_body = await resp.json(content_type=None)
                    if resp.status != 200 or not token_body.get("accessToken"):
                        raise DingTalkSSOError(
                            f"token exchange failed: http={resp.status} "
                            f"body={token_body}"
                        )
                    access_token = token_body["accessToken"]

                async with session.get(
                    USERINFO_URL,
                    headers={"x-acs-dingtalk-access-token": access_token},
                ) as resp:
                    info = await resp.json(content_type=None)
                    if resp.status != 200 or not info.get("openId"):
                        raise DingTalkSSOError(
                            f"userinfo failed: http={resp.status} body={info}"
                        )
            except aiohttp.ClientError as e:
                raise DingTalkSSOError(f"network error during DingTalk SSO: {e}") from e

        profile = {
            "open_id": info.get("openId", ""),
            "union_id": info.get("unionId", ""),
            "nick": info.get("nick", "") or "钉钉用户",
            "avatar": info.get("avatarUrl", "") or "",
            "email": info.get("email", "") or "",
        }
        logger.info("DingTalk SSO profile resolved: open_id=%s nick=%s",
                    profile["open_id"], profile["nick"])
        return profile
