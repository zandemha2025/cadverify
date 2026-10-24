"""Import from a link: which links are taken, and what each becomes (pure, no network).

Each refused class of URL, each provider's rewrite to its download address,
the redirect allowlist, the file-name rules, the setting and the sealing.
"""
from __future__ import annotations

import pytest
import httpx

from src.services import link_import as L


def _refused(url: str) -> L.LinkRefused:
    with pytest.raises(L.LinkRefused) as exc:
        L.plan_link(url)
    return exc.value


# -- refused classes ---------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://www.dropbox.com/s/abc/bracket.step",
    "ftp://www.dropbox.com/s/abc/bracket.step",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "gopher://www.dropbox.com/s/abc/bracket.step",
])
def test_only_https(url):
    assert _refused(url).code in {"LINK_NOT_HTTPS", "LINK_INVALID"}


@pytest.mark.parametrize("url", [
    "https://user:pass@www.dropbox.com/s/abc/bracket.step",
    "https://user@www.dropbox.com/s/abc/bracket.step",
    # A provider name as user info, another host behind it.
    "https://www.dropbox.com@evil.example/s/abc/bracket.step",
])
def test_no_user_info(url):
    assert _refused(url).code == "LINK_USERINFO"


@pytest.mark.parametrize("url", [
    "https://www.dropbox.com:8443/s/abc/bracket.step",
    "https://www.dropbox.com:80/s/abc/bracket.step",
    "https://drive.google.com:444/file/d/1AbCdEfGhIjKlMnOp/view",
])
def test_port_443_only(url):
    assert _refused(url).code == "LINK_PORT"


def test_explicit_port_443_is_the_same_link():
    assert L.plan_link("https://www.dropbox.com:443/s/abc/bracket.step").provider == "dropbox"


@pytest.mark.parametrize("url", [
    "https://169.254.169.254/latest/meta-data/",
    "https://127.0.0.1/bracket.step",
    "https://10.0.0.5/bracket.step",
    "https://[::1]/bracket.step",
    "https://[fd00:ec2::254]/latest",
    "https://100.100.100.200/latest",
    "https://0.0.0.0/x",
    "https://2130706433/x",
])
def test_ip_literals_are_refused(url):
    assert _refused(url).code in {"LINK_NOT_SUPPORTED", "LINK_INVALID"}


@pytest.mark.parametrize("url", [
    "https://example.com/bracket.step",
    "https://localhost/bracket.step",
    "https://metadata.google.internal/computeMetadata/v1/",
    "https://www.dropbox.com.evil.example/s/abc/bracket.step",
    "https://evil-dropbox.com/s/abc/bracket.step",
    "https://dropbox.com.evil.example/s/abc/bracket.step",
    "https://drive.google.com.evil.example/file/d/1AbCdEfGhIjKlMnOp/view",
    "https://dl.dropboxusercontent.com/s/abc/bracket.step",
    "https://ec2-1-2-3-4.compute-1.amazonaws.com/bracket.step",
    "https://amazonaws.com/bucket/key.step",
    "https://contoso.sharepoint.com.evil.example/:u:/g/x",
    "https://contoso.sharepoint.us/:u:/g/x",
    "https://mybucket.s3.amazonaws.com.cn/key.step",
    "https://www.dropbox.com./s/abc/bracket.step",
])
def test_hosts_off_the_allowlist_are_refused(url):
    refused = _refused(url)
    assert refused.code in {"LINK_NOT_SUPPORTED", "LINK_INVALID"}
    if refused.code == "LINK_NOT_SUPPORTED":
        assert refused.message == L.NOT_SUPPORTED


@pytest.mark.parametrize("url", [
    "",
    "   ",
    "https://www.dropbox.com/s/abc/bracket step.step",
    "https://www.dropbox.com/s/abc/bracket.step\r\nX-Injected: 1",
    "https://www.dropbox.com\\@evil.example/s/abc/b.step",
    "https://www.dropbox.com/s/" + "a" * 5000,
])
def test_malformed_links_are_refused(url):
    assert _refused(url).code in {"LINK_INVALID", "LINK_NOT_SUPPORTED"}


@pytest.mark.parametrize("url", [
    "https://www.dropbox.com/sh/abc/def?dl=0",
    "https://www.dropbox.com/scl/fo/abc/def?rlkey=x",
    "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOp",
    "https://drive.google.com/drive/u/0/folders/1AbCdEfGhIjKlMnOp",
    "https://1drv.ms/f/s!AbCdEf123",
    "https://contoso.sharepoint.com/:f:/g/personal/x/EabcDEF",
])
def test_folder_links_are_refused(url):
    refused = _refused(url)
    assert refused.code == "LINK_FOLDER"
    assert "folder" in refused.message


@pytest.mark.parametrize("url", [
    "https://drive.google.com/drive/my-drive",
    "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOp/edit",
    "https://www.dropbox.com/home",
    "https://onedrive.live.com/about",
    "https://contoso.sharepoint.com/_layouts/15/viewlsts.aspx",
    "https://mybucket.s3.us-east-1.amazonaws.com/",
    "https://s3.us-east-1.amazonaws.com/mybucket",
])
def test_provider_pages_that_are_not_one_file_are_refused(url):
    assert _refused(url).code == "LINK_NOT_A_FILE_LINK"


def test_scalecad_own_buckets_are_refused(monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_S3_BUCKET", "cadverify-prod-blobs")
    monkeypatch.setenv("DIRECT_UPLOAD_S3_BUCKET", "cadverify-prod-incoming")
    monkeypatch.setenv("LINK_IMPORT_REFUSED_S3_BUCKETS", "cadverify-backups, other-internal")
    for url in (
        "https://cadverify-prod-blobs.s3.us-east-1.amazonaws.com/org/x.step?X-Amz-Signature=a",
        "https://s3.us-east-1.amazonaws.com/cadverify-prod-incoming/incoming/x/part.step?X-Amz-Signature=a",
        "https://CADVERIFY-PROD-BLOBS.s3.amazonaws.com/x.step",
        "https://cadverify-backups.s3.dualstack.us-west-2.amazonaws.com/x.step",
        "https://s3-eu-west-1.amazonaws.com/other-internal/x.step",
    ):
        assert _refused(url).code == "LINK_OWN_STORAGE", url
    assert L.plan_link("https://customer-bucket.s3.us-east-1.amazonaws.com/x.step?X-Amz-Signature=a").provider == "s3"


# -- each provider's rewrite -------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing",
    "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view",
    "https://drive.google.com/file/u/0/d/1AbCdEfGhIjKlMnOp/edit",
    "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOp",
    "https://drive.google.com/uc?id=1AbCdEfGhIjKlMnOp&export=download",
    "https://docs.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp",
])
def test_google_drive_links_fetch_from_usercontent(url):
    plan = L.plan_link(url)
    assert plan.provider == "google_drive" and plan.label == "Google Drive"
    assert plan.fetch_url == "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOp&export=download"


def test_google_drive_keeps_the_resource_key():
    plan = L.plan_link("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?resourcekey=0-abcDEF")
    assert plan.fetch_url.endswith("&resourcekey=0-abcDEF")


@pytest.mark.parametrize("url,fetch,name", [
    ("https://www.dropbox.com/scl/fi/abc123/bracket.step?rlkey=k3y&dl=0",
     "https://www.dropbox.com/scl/fi/abc123/bracket.step?rlkey=k3y&dl=1", "bracket.step"),
    ("https://www.dropbox.com/s/abc123/bracket%20v2.stl?dl=0",
     "https://www.dropbox.com/s/abc123/bracket%20v2.stl?dl=1", "bracket v2.stl"),
    ("https://dropbox.com/s/abc123/plate.iges",
     "https://www.dropbox.com/s/abc123/plate.iges?dl=1", "plate.iges"),
    ("https://www.dropbox.com/scl/fi/abc123/part.step.gz?rlkey=k&st=s&raw=1",
     "https://www.dropbox.com/scl/fi/abc123/part.step.gz?rlkey=k&st=s&dl=1", "part.step.gz"),
])
def test_dropbox_links_ask_for_the_download(url, fetch, name):
    plan = L.plan_link(url)
    assert plan.provider == "dropbox"
    assert plan.fetch_url == fetch
    assert plan.filename_hint == name


def test_onedrive_links_go_through_the_shares_api():
    import base64

    for url in ("https://1drv.ms/u/s!AbCdEf123", "https://onedrive.live.com/?cid=ABC&resid=ABC%21123&authkey=!Akey"):
        plan = L.plan_link(url)
        assert plan.provider == "onedrive"
        token = plan.fetch_url.split("/shares/u!", 1)[1].split("/", 1)[0]
        decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        assert httpx.URL(decoded) == httpx.URL(url)
        assert plan.fetch_url.startswith("https://api.onedrive.com/v1.0/shares/u!")
        assert plan.fetch_url.endswith("/root/content")


@pytest.mark.parametrize("url,fetch", [
    ("https://contoso.sharepoint.com/:u:/g/personal/ana/EabcDEF?e=x1",
     "https://contoso.sharepoint.com/:u:/g/personal/ana/EabcDEF?e=x1&download=1"),
    ("https://contoso-my.sharepoint.com/:u:/r/personal/ana/Documents/bracket.step?csf=1",
     "https://contoso-my.sharepoint.com/:u:/r/personal/ana/Documents/bracket.step?csf=1&download=1"),
    ("https://contoso.sharepoint.com/sites/eng/Shared%20Documents/plate.step",
     "https://contoso.sharepoint.com/sites/eng/Shared%20Documents/plate.step?download=1"),
])
def test_sharepoint_links_ask_for_the_download(url, fetch):
    plan = L.plan_link(url)
    assert plan.provider == "sharepoint" and plan.scope == "contoso"
    assert plan.fetch_url == fetch


@pytest.mark.parametrize("url,bucket,name", [
    ("https://my-parts.s3.us-east-1.amazonaws.com/a/bracket.step?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc",
     "my-parts", "bracket.step"),
    ("https://my-parts.s3.amazonaws.com/bracket.stl?AWSAccessKeyId=A&Signature=s&Expires=1", "my-parts", "bracket.stl"),
    ("https://my-parts.s3-eu-west-1.amazonaws.com/x/y/plate.igs", "my-parts", "plate.igs"),
    ("https://my-parts.s3.dualstack.ap-southeast-2.amazonaws.com/k.step", "my-parts", "k.step"),
    ("https://s3.eu-west-2.amazonaws.com/my-parts/dir/part.zip?X-Amz-Signature=abc", "my-parts", "part.zip"),
    ("https://s3.amazonaws.com/my-parts/part.step", "my-parts", "part.step"),
])
def test_s3_links_are_fetched_as_given(url, bucket, name):
    plan = L.plan_link(url)
    assert plan.provider == "s3" and plan.scope == bucket
    assert httpx.URL(plan.fetch_url) == httpx.URL(url)
    assert plan.filename_hint == name


def test_the_fragment_is_dropped_and_the_query_never_public():
    plan = L.plan_link("https://www.dropbox.com/scl/fi/abc/b.step?rlkey=SECRET&dl=0#frag")
    assert "#" not in plan.fetch_url
    shown = repr(plan.public()) + plan.host + plan.path
    assert "SECRET" not in shown and "rlkey" not in shown
    assert plan.public() == {"provider": "dropbox", "label": "Dropbox", "host": "www.dropbox.com"}


# -- redirects stay within the provider ----------------------------------------

def _plan(url):
    return L.plan_link(url)


@pytest.mark.parametrize("start,target", [
    ("https://www.dropbox.com/s/a/b.step", "https://uc0a1b2c.dl.dropboxusercontent.com/cd/0/get/x/file"),
    ("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view", "https://doc-0s-8c-docs.googleusercontent.com/docs/x"),
    ("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view", "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOp&confirm=t"),
    ("https://1drv.ms/u/s!AbCdEf123", "https://public.am.files.1drv.com/y4m/x.step"),
    ("https://1drv.ms/u/s!AbCdEf123", "https://abc.dm.files.1drv.com/y4m/x.step"),
    ("https://contoso.sharepoint.com/:u:/g/x", "https://contoso-my.sharepoint.com/personal/x/_layouts/15/download.aspx?share=y"),
    ("https://my-parts.s3.amazonaws.com/b.step", "https://my-parts.s3.eu-west-1.amazonaws.com/b.step?X-Amz-Signature=a"),
])
def test_redirects_within_the_provider_are_followed(start, target):
    assert L.check_target(_plan(start), target).host


@pytest.mark.parametrize("start,target,code", [
    ("https://www.dropbox.com/s/a/b.step", "https://drive.usercontent.google.com/download?id=x", "LINK_REDIRECT_REFUSED"),
    ("https://www.dropbox.com/s/a/b.step", "http://uc0a.dl.dropboxusercontent.com/f", "LINK_REDIRECT_REFUSED"),
    ("https://www.dropbox.com/s/a/b.step", "https://uc0a.dl.dropboxusercontent.com:8443/f", "LINK_REDIRECT_REFUSED"),
    ("https://www.dropbox.com/s/a/b.step", "https://u:p@uc0a.dl.dropboxusercontent.com/f", "LINK_REDIRECT_REFUSED"),
    ("https://www.dropbox.com/s/a/b.step", "https://169.254.169.254/latest/meta-data/", "LINK_REDIRECT_REFUSED"),
    ("https://www.dropbox.com/s/a/b.step", "https://localhost/f", "LINK_REDIRECT_REFUSED"),
    ("https://www.dropbox.com/s/a/b.step", "https://a.b.dl.dropboxusercontent.com.evil.example/f", "LINK_REDIRECT_REFUSED"),
    ("https://www.dropbox.com/s/a/b.step", "https://www.dropbox.com/login?cont=x", "LINK_NEEDS_SIGN_IN"),
    ("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view", "https://accounts.google.com/ServiceLogin?x", "LINK_NEEDS_SIGN_IN"),
    ("https://1drv.ms/u/s!AbCdEf123", "https://login.live.com/oauth20", "LINK_NEEDS_SIGN_IN"),
    ("https://contoso.sharepoint.com/:u:/g/x", "https://login.microsoftonline.com/common/oauth2", "LINK_NEEDS_SIGN_IN"),
    ("https://contoso.sharepoint.com/:u:/g/x", "https://fabrikam.sharepoint.com/f", "LINK_REDIRECT_REFUSED"),
    ("https://my-parts.s3.amazonaws.com/b.step", "https://other-bucket.s3.amazonaws.com/b.step", "LINK_REDIRECT_REFUSED"),
    ("https://my-parts.s3.amazonaws.com/b.step", "https://s3.amazonaws.com/other-bucket/b.step", "LINK_REDIRECT_REFUSED"),
    ("https://my-parts.s3.amazonaws.com/b.step", "https://www.dropbox.com/s/a/b.step", "LINK_REDIRECT_REFUSED"),
])
def test_redirects_elsewhere_are_refused(start, target, code):
    with pytest.raises(L.LinkFetchError) as exc:
        L.check_target(_plan(start), target)
    assert exc.value.code == code
    assert "evil" not in exc.value.message and "?" not in exc.value.message


def test_a_relative_redirect_is_joined_to_the_current_address():
    plan = _plan("https://www.dropbox.com/s/a/b.step")
    url = L.check_target(plan, "/scl/fi/abc/b.step?dl=1", base=httpx.URL("https://www.dropbox.com/s/a/b.step?dl=1"))
    assert str(url) == "https://www.dropbox.com/scl/fi/abc/b.step?dl=1"


# -- names ----------------------------------------------------------------------

@pytest.mark.parametrize("header,name", [
    ('attachment; filename="bracket.step"', "bracket.step"),
    ("attachment; filename=plate.stl", "plate.stl"),
    ("attachment; filename*=UTF-8''Halterung%20gro%C3%9F.step", "Halterung groß.step"),
    ('attachment; filename="x.step"; filename*=UTF-8\'\'y.step', "y.step"),
    ('attachment; filename="../../etc/passwd"', "passwd"),
    ('attachment; filename="a\\b\\c.iges"', "c.iges"),
    ("inline", None),
    (None, None),
])
def test_content_disposition_names(header, name):
    assert L.disposition_filename(header) == name


def test_the_name_typed_wins_then_the_servers_then_the_links():
    assert L.choose_filename("mine.step", "served.stl", "hint.iges") == "mine.step"
    assert L.choose_filename(None, "served.stl", "hint.iges") == "served.stl"
    assert L.choose_filename(None, "served.pdf", "hint.iges") == "hint.iges"
    assert L.choose_filename(None, None, "part.step.gz") == "part.step.gz"
    with pytest.raises(L.LinkFetchError) as exc:
        L.choose_filename(None, "readme.pdf", None)
    assert exc.value.code == "LINK_UNKNOWN_TYPE"


def test_drive_confirm_form_is_read():
    page = b"""<!DOCTYPE html><html><body>
      <p>Google Drive can't scan this file for viruses.</p>
      <form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
        <input type="submit" id="uc-download-link" value="Download anyway"/>
        <input type="hidden" name="id" value="1AbCdEfGhIjKlMnOp">
        <input type="hidden" name="export" value="download">
        <input type="hidden" name="confirm" value="t">
        <input type="hidden" name="uuid" value="0f1e2d3c">
      </form></body></html>"""
    target = L.drive_confirm_target(page, httpx.URL("https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOp&export=download"))
    assert target == "https://drive.usercontent.google.com/download?id=1AbCdEfGhIjKlMnOp&export=download&confirm=t&uuid=0f1e2d3c"
    assert L.drive_confirm_target(b"<html><body>Sign in</body></html>", httpx.URL("https://drive.usercontent.google.com/x")) is None


# -- the setting and the sealed link ------------------------------------------

def test_on_by_default_off_by_setting_and_never_on_the_regulated_plane(monkeypatch):
    monkeypatch.delenv("LINK_IMPORT_ENABLED", raising=False)
    monkeypatch.delenv("PRODUCTION_REGULATED_BOUNDARY_REQUIRED", raising=False)
    assert L.link_import_enabled() is True
    monkeypatch.setenv("LINK_IMPORT_ENABLED", "0")
    assert L.link_import_enabled() is False
    monkeypatch.setenv("LINK_IMPORT_ENABLED", "1")
    monkeypatch.setenv("PRODUCTION_REGULATED_BOUNDARY_REQUIRED", "1")
    assert L.link_import_enabled() is False


def test_regulated_production_refuses_to_start_with_link_import_on(monkeypatch):
    from src.config.production import assert_production_operations

    monkeypatch.setenv("RELEASE", "v1.0.0")
    monkeypatch.setenv("PRODUCTION_REGULATED_BOUNDARY_REQUIRED", "1")
    monkeypatch.setenv("AUTH_MODE", "saml")
    monkeypatch.setenv("PASSWORD_LOGIN_ENABLED", "0")
    monkeypatch.setenv("MAGIC_LINK_ENABLED", "0")
    monkeypatch.setenv("RECONSTRUCTION_BACKEND", "local")
    monkeypatch.setenv("RECONSTRUCTION_ALLOW_REMOTE_EGRESS", "0")
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("LINK_IMPORT_ENABLED", "1")
    with pytest.raises(RuntimeError, match="LINK_IMPORT_ENABLED=0"):
        assert_production_operations()
    monkeypatch.setenv("LINK_IMPORT_ENABLED", "0")
    assert_production_operations()


def test_the_link_is_sealed_for_the_worker(monkeypatch):
    monkeypatch.delenv("RELEASE", raising=False)
    url = "https://www.dropbox.com/scl/fi/abc/b.step?rlkey=SECRET&dl=0"
    sealed = L.seal_url(url)
    assert sealed.startswith("fernet:v1:") and "SECRET" not in sealed
    assert L.open_sealed_url(sealed) == url
    with pytest.raises(L.LinkFetchError):
        L.open_sealed_url("fernet:v1:not-a-token")
    with pytest.raises(L.LinkFetchError):
        L.open_sealed_url(url)


def test_logs_and_error_reports_scrub_share_link_secrets():
    from src.auth.scrubbing import _scrub_str

    text = ("GET https://my-parts.s3.amazonaws.com/b.step?X-Amz-Credential=AKIA/x&X-Amz-Signature=deadbeef "
            "https://www.dropbox.com/scl/fi/a/b.step?rlkey=k3y&dl=1 https://onedrive.live.com/?authkey=!A1&cid=2")
    out = _scrub_str(text)
    for secret in ("deadbeef", "AKIA", "k3y", "!A1"):
        assert secret not in out
    assert "dl=1" in out and "cid=2" in out


def test_the_total_budget_grows_with_size_and_is_capped():
    assert L.total_budget_sec(0, 2 * 1024**3) == L.TOTAL_BASE_SEC
    assert L.total_budget_sec(100 * 1024**2, 2 * 1024**3) == L.TOTAL_BASE_SEC + 100 * L.TOTAL_SEC_PER_MIB
    assert L.total_budget_sec(None, 2 * 1024**3) == L.TOTAL_CAP_SEC
