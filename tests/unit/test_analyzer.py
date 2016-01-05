from chalice.analyzer import get_client_calls
from textwrap import dedent


def aws_calls(source_code):
    real_source_code = dedent(source_code)
    calls = get_client_calls(real_source_code)
    return calls


def test_single_call():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        d.list_tables()
    """) == {'dynamodb': set(['list_tables'])}


def test_multiple_calls():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        d.list_tables()
        d.create_table(TableName='foobar')
    """) == {'dynamodb': set(['list_tables', 'create_table'])}


def test_multiple_services():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        asdf = boto3.client('s3')
        d.list_tables()
        asdf.get_object(Bucket='foo', Key='bar')
        d.create_table(TableName='foobar')
    """) == {'dynamodb': set(['list_tables', 'create_table']),
             's3': set(['get_object']),
             }

def test_in_function():
    assert aws_calls("""\
        import boto3
        def foo():
            d = boto3.client('dynamodb')
            d.list_tables()
    """) == {'dynamodb': set(['list_tables'])}


def test_basic_aliasing():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        alias = d
        alias.list_tables()
    """) == {'dynamodb': set(['list_tables'])}


def test_multiple_aliasing():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        alias = d
        alias2 = alias
        alias3 = alias2
        alias3.list_tables()
    """) == {'dynamodb': set(['list_tables'])}


def test_multiple_aliasing_non_chained():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        alias = d
        alias2 = alias
        alias3 = alias
        alias3.list_tables()
    """) == {'dynamodb': set(['list_tables'])}


def test_can_map_function_params():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        def make_call(client):
            a = 1
            return client.list_tables()
        make_call(d)
    """) == {'dynamodb': set(['list_tables'])}


def test_can_map_function_with_multiple_args():
    assert aws_calls("""\
        import boto3, mock
        m = mock.Mock()
        d = boto3.client('dynamodb')
        def make_call(other, client):
            a = 1
            other.create_table()
            return client.list_tables()
        make_call(m, d)
    """) == {'dynamodb': set(['list_tables'])}


def test_no_calls_found():
    assert aws_calls("""\
        import boto3
    """) == {}


def test_original_name_replaced():
    assert aws_calls("""\
        import boto3
        import some_other_thing
        d = boto3.client('dynamodb')
        d.list_tables()
        d = some_other_thing
        d.create_table()
    """) == {'dynamodb': set(['list_tables'])}


def test_can_track_across_classes():
    return
    # XXX: Are you kidding me???
    assert aws_calls("""\
        import boto3
        ddb = boto3.client('dynamodb')
        class Helper(object):
            def __init__(self, client):
                self.client = client
            def foo(self):
                return self.client.list_tables()
        h = Helper(ddb)
        h.foo()
    """) == {'dynamodb': set(['list_tables'])}
