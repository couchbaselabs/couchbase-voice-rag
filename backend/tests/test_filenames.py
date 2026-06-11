import pytest

from utils.filenames import safe_filename


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("hello.pdf", "hello.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\me\\report.pdf", "report.pdf"),
        ("my file name.pdf", "my_file_name.pdf"),
    ],
)
def test_safe_filename_happy_paths(raw, expected):
    assert safe_filename(raw) == expected


def test_safe_filename_rejects_empty_after_sanitization():
    with pytest.raises(ValueError):
        safe_filename("../../")


def test_safe_filename_truncates_but_keeps_extension():
    long_stem = "a" * 300
    result = safe_filename(f"{long_stem}.pdf")
    assert result.endswith(".pdf")
    assert len(result) <= 200


def test_safe_filename_strips_leading_dots():
    result = safe_filename(".hidden.pdf")
    assert not result.startswith(".")
