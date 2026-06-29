def test_now_iso():
    from common.utils.identifiers import now_iso    
    
    x = now_iso()
    assert isinstance(x, str)
    
def test_uuid_8():
    from common.utils.identifiers import uuid_8
    id = uuid_8()
    assert isinstance(id, str)
    assert len(id) == 8