import odib


def test_main_runs(capsys) -> None:
    odib.main()
    assert "Odin" in capsys.readouterr().out
