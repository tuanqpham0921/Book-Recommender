# backend/tests/test_imports.py

def test_core_modules_import():
    import config
    import db.bootstrap
    import ingestion.main
    import ingestion.utils