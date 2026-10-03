from importlib.metadata import version

import pytest

import odin
from odin.cli import main


def test_version_flag_prints_version(monkeypatch, capsys) -> None:
    monkeypatch.setattr(odin, "__version__", "1.2.3")
    with pytest.raises(SystemExit) as exc:
        main(["--version"], {})
    assert exc.value.code == 0
    assert capsys.readouterr().out == "1.2.3\n"


def test_version_comes_from_package_metadata() -> None:
    assert odin.__version__ == version("odin")
