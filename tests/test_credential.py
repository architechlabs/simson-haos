import copy
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("credential", ROOT / "custom_components/simson/credential.py")
credential = importlib.util.module_from_spec(spec)
spec.loader.exec_module(credential)

FIXTURE = json.loads((ROOT / "tests/fixtures/credential_envelope.json").read_text())


def test_opens_an_envelope_sealed_by_the_go_server():
    key = credential.OneTimeKey.from_private_value(FIXTURE["private_key_d"])
    assert key.public_key == FIXTURE["public_key"]
    assert key.open(FIXTURE["result"], FIXTURE["context"]) == FIXTURE["password"]


def test_rejects_an_envelope_for_another_phone():
    key = credential.OneTimeKey.from_private_value(FIXTURE["private_key_d"])
    other = FIXTURE["context"].replace("33333333", "44444444")
    with pytest.raises(credential.CredentialError):
        key.open(FIXTURE["result"], other)


def test_rejects_tampering_and_wrong_keys():
    key = credential.OneTimeKey.from_private_value(FIXTURE["private_key_d"])
    tampered = copy.deepcopy(FIXTURE["result"])
    cipher = tampered["credential_envelope"]["ciphertext"]
    tampered["credential_envelope"]["ciphertext"] = ("A" if cipher[0] != "A" else "B") + cipher[1:]
    with pytest.raises(credential.CredentialError):
        key.open(tampered, FIXTURE["context"])
    with pytest.raises(credential.CredentialError):
        credential.OneTimeKey.generate().open(FIXTURE["result"], FIXTURE["context"])


@pytest.mark.parametrize("change", [
    lambda r: r.update(revision=0),
    lambda r: r.update(revision=True),
    lambda r: r["credential_envelope"].update(algorithm="none"),
    lambda r: r.pop("credential_envelope"),
    lambda r: r["credential_envelope"].update(nonce=""),
    lambda r: r["credential_envelope"].update(ephemeral_public_key="not-a-point"),
])
def test_rejects_malformed_results(change):
    key = credential.OneTimeKey.from_private_value(FIXTURE["private_key_d"])
    broken = copy.deepcopy(FIXTURE["result"])
    change(broken)
    with pytest.raises(credential.CredentialError):
        key.open(broken, FIXTURE["context"])


def test_generated_keys_are_fresh_and_correctly_shaped():
    first, second = credential.OneTimeKey.generate(), credential.OneTimeKey.generate()
    assert first.public_key != second.public_key
    assert len(first.public_key) == 87 and first.public_key.startswith("B")
    assert credential.credential_context("t", "s", "e") == "simson:sip-credential:v1:t:s:e"
