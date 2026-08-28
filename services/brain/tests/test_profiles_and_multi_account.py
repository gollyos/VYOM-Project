"""Chrome profile listing + multi-account Gmail attach.

Owner ask (2026-08-28): "chrome profile find and multiple account attach
gmail facebook instagram". Profiles are answered from Chrome's own Local
State (no model); Gmail app-password now holds MULTIPLE attached accounts
with an active sender; a failed connect evicts only the failed account.
"""

import json

from app.email.provider import GmailAppPasswordProvider
from app.runtime.task_classifier import TaskClassifier


class FakeVault:
    def __init__(self):
        self.items: dict[str, bytes] = {}

    def set(self, key, payload):
        self.items[key] = payload

    def get(self, key):
        return self.items.get(key)

    def delete(self, key):
        self.items.pop(key, None)


def test_gmail_multi_account_attach_switch_remove():
    vault = FakeVault()
    provider = GmailAppPasswordProvider(vault)

    provider.store_credentials("one@gmail.com", "abcdefghijklmnop")
    provider.store_credentials("two@gmail.com", "qrstuvwxyz123456")

    accounts = provider.list_accounts()
    assert accounts == [
        {"address": "one@gmail.com", "active": False},
        {"address": "two@gmail.com", "active": True},
    ], "attaching a second account keeps the first; newest is active"

    provider.switch_active("one@gmail.com")
    assert provider.list_accounts()[0]["active"] is True

    creds = provider._load_credentials()
    assert creds["address"] == "one@gmail.com"

    provider.remove_account("one@gmail.com")
    accounts = provider.list_accounts()
    assert [a["address"] for a in accounts] == ["two@gmail.com"]
    assert accounts[0]["active"] is True, "removing the active account falls back to a remaining one"


def test_gmail_legacy_single_account_migrates():
    vault = FakeVault()
    vault.set("app_password:gmail", json.dumps(
        {"address": "old@gmail.com", "app_password": "abcdefghijklmnop"}).encode("utf-8"))
    provider = GmailAppPasswordProvider(vault)

    accounts = provider.list_accounts()
    assert accounts == [{"address": "old@gmail.com", "active": True}]
    assert vault.get("app_password:gmail") is None, "legacy key migrated away"
    assert vault.get("app_password:gmail:accounts") is not None


def test_switch_unknown_address_is_refused():
    vault = FakeVault()
    provider = GmailAppPasswordProvider(vault)
    provider.store_credentials("one@gmail.com", "abcdefghijklmnop")
    try:
        provider.switch_active("nobody@gmail.com")
        raise AssertionError("switching to an unattached account must fail")
    except ValueError:
        pass


def test_profile_listing_routes_deterministically():
    classifier = TaskClassifier()
    for phrase in (
        "chrome profiles kaunsi hain",
        "chrome profile list dikhao",
        "mere chrome ke profiles batao",
    ):
        profile = classifier.classify(phrase)
        assert profile.deterministic, phrase
        assert profile.intent == "browser_profile_list", f"{phrase} -> {profile.intent}"


def test_profile_open_commands_are_not_listed():
    classifier = TaskClassifier()
    for phrase in ("chrome me goli profile kholo", "work profile open karo"):
        profile = classifier.classify(phrase)
        assert profile.intent != "browser_profile_list", phrase
