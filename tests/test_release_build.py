from tools.build_release import application_hidden_imports


def test_release_build_analyzes_external_application_dependencies() -> None:
    imports = application_hidden_imports()
    assert "webbrowser" in imports
    assert "signriver_app.infrastructure.persistence.database" in imports
    assert "signriver_app.infrastructure.installs.engine" in imports
    assert "signriver_app.application.download_queue" in imports
