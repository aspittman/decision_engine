import pytest
from decision_engine.repositories.store import Repository
from decision_engine.models.contracts import uid, now
from decision_engine.clients.supabase_client import SupabaseClient
from decision_engine.config.settings import Settings


def test_repository_rejects_unscoped_response(config):
    class Client:
        def rows(self,table,filters):
            assert 'organization_id' in filters
            return [{"organization_id":uid()}]
    with pytest.raises(ValueError,match='Cross-organization'):
        Repository(Client(),config).scoped('market_signals',uid())


def test_pagination_includes_short_server_pages():
    client=SupabaseClient(Settings('https://example.supabase.co','secret'))
    offsets=[]
    def request(method,path,params):
        offsets.append(params['offset'])
        return [{'id':i} for i in range(params['offset'],min(params['offset']+2,5))]
    client.request=request
    assert len(client.rows('organizations'))==5
    assert offsets==[0,2,4,5]


def test_secrets_and_https():
    settings=Settings('https://example.supabase.co','super-secret')
    assert 'super-secret' not in repr(settings)
    with pytest.raises(ValueError):
        SupabaseClient(Settings('http://example.com','secret'))
