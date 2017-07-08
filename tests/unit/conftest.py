from pytest import fixture

from chalice.app import Chalice


@fixture(autouse=True)
def ensure_no_local_config(no_local_config):
    pass


@fixture
def sample_app():
    app = Chalice('sample')

    @app.route('/')
    def foo():
        return {}

    return app


@fixture
def sample_app_with_auth():
    app = Chalice('sampleauth')

    @app.authorizer('myauth')
    def myauth(auth_request):
        pass

    @app.route('/', authorizer=myauth)
    def foo():
        return {}

    return app
