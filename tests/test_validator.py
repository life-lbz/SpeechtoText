import pytest

from app.services.validator import AudioValidationError, validate_upload


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("a.wav", ".wav"),
        ("B.MP3", ".mp3"),
        ("c.webm", ".webm"),
        ("d.ogg", ".ogg"),
        ("e.m4a", ".m4a"),
        ("f.flac", ".flac"),
    ],
)
def test_accepts_supported_extensions(filename, expected):
    assert validate_upload(filename, 1024) == expected


def test_strips_directory_from_filename():
    assert validate_upload("../../etc/passwd.wav", 1024) == ".wav"


@pytest.mark.parametrize("filename", ["note.txt", "video.mp4", "noext", None])
def test_rejects_unsupported_formats(filename):
    with pytest.raises(AudioValidationError) as excinfo:
        validate_upload(filename, 1024)
    assert excinfo.value.status_code == 400


def test_rejects_empty_file():
    with pytest.raises(AudioValidationError) as excinfo:
        validate_upload("a.wav", 0)
    assert excinfo.value.status_code == 400


def test_rejects_oversized_file():
    with pytest.raises(AudioValidationError) as excinfo:
        validate_upload("a.wav", 10 * 1024 * 1024 + 1)
    assert excinfo.value.status_code == 413
