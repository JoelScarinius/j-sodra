from types import SimpleNamespace
from unittest.mock import Mock, patch
from pathlib import Path
import pytest
from pipeline.data_service import DataService

def settings(secret='proxy-secret'):
    return SimpleNamespace(
        wyscout_proxy_shared_secret=secret,
        supabase_function_url='https://example.invalid/functions/v1/wyscout-proxy',
        http_timeout_seconds=30,
    )

def test_data_service_sends_proxy_header_not_query_secret():
    response=Mock(status_code=200);response.json.return_value={'seasons':[]}
    with patch('pipeline.data_service.requests.get',return_value=response) as get:
        result=DataService(settings()).fetch_api('/competitions/810/seasons',{'fetch':'competition'})
    assert result=={'seasons':[]}
    kwargs=get.call_args.kwargs
    assert kwargs['headers']['X-Proxy-Key']=='proxy-secret'
    assert kwargs['headers']['Accept']=='application/json'
    assert 'proxy-secret' not in kwargs['params'].values()
    assert 'Authorization' not in kwargs['headers']
    assert 'apikey' not in kwargs['headers']

def test_missing_proxy_secret_fails_clearly():
    with pytest.raises(RuntimeError,match='WYSCOUT_PROXY_SHARED_SECRET'):
        DataService(settings(None)).fetch_api('/search',{'query':'Jonkopings','objType':'team'})

def test_proxy_source_allows_pipeline_endpoint_shapes():
    source=Path('supabase/functions/wyscout-proxy/index.ts').read_text()
    for fragment in ['/search', 'competitions', 'seasons', 'teams', 'fixtures', 'matches', 'events', 'formations', 'advancedstats']:
        assert fragment in source
    assert 'PROXY_SHARED_SECRET' in source
    assert 'x-proxy-key' in source
