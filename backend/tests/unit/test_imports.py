# backend/tests/test_imports.py

def test_core_modules_import():
    import config
    import db.bootstrap
    import db.ingestion.main
    import db.ingestion.utils