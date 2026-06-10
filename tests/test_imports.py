"""Guard against missing dependencies.

Lazily-imported modules (like certificate.py) don't fail at app start —
they crash at request time in production. This test imports every module
eagerly so a missing package fails CI instead of a user's download click.
"""


def test_all_project_modules_import():
    import app          # noqa: F401
    import models       # noqa: F401
    import reminders    # noqa: F401
    import certificate  # noqa: F401  ← lazily imported in app.py; broken deps surface here
