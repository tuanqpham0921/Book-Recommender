

async def test_ingestion_smoke():
    from ingestion.main import main
    result = await main()
    
    assert result.ok