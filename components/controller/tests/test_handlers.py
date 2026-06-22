import main


def test_handlers_exist():
    assert callable(main.on_create)
    assert callable(main.on_update)
    assert callable(main.on_delete)
