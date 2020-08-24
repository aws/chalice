import sys
import pytest

from textwrap import dedent

from chalice import analyzer
from chalice.analyzer import Boto3ModuleType, Boto3CreateClientType
from chalice.analyzer import Boto3ClientType, Boto3ClientMethodType
from chalice.analyzer import Boto3ClientMethodCallType
from chalice.analyzer import FunctionType


def aws_calls(source_code):
    real_source_code = dedent(source_code)
    calls = analyzer.get_client_calls(real_source_code)
    return calls


def chalice_aws_calls(source_code):
    real_source_code = dedent(source_code)
    calls = analyzer.get_client_calls_for_app(real_source_code)
    return calls


def known_types_for_module(source_code):
    real_source_code = dedent(source_code)
    compiled = analyzer.parse_code(real_source_code)
    t = analyzer.SymbolTableTypeInfer(compiled)
    t.bind_types()
    known = t.known_types()
    return known


def known_types_for_function(source_code, name):
    real_source_code = dedent(source_code)
    compiled = analyzer.parse_code(real_source_code)
    t = analyzer.SymbolTableTypeInfer(compiled)
    t.bind_types()
    known = t.known_types(scope_name=name)
    return known


def test_can_analyze_chalice_app():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3

        app = Chalice(app_name='james1')
        ec2 = boto3.client('ec2')


        @app.route('/')
        def index():
            ec2.describe_instances()
            return {}
    """) == {'ec2': set(['describe_instances'])}


def test_inferred_module_type():
    assert known_types_for_module("""\
        import boto3
        import os
        a = 1
    """) == {'boto3': Boto3ModuleType()}


def test_recursive_function_none():
    assert aws_calls("""\
        def recursive_function():
            recursive_function()
        recursive_function()
    """) == {}


def test_recursive_comprehension_none():
    assert aws_calls("""\
        xs = []
        def recursive_function():
            [recursive_function() for x in xs]
        recursive_function()
    """) == {}


def test_recursive_function_client_calls():
    assert aws_calls("""\
        import boto3
        def recursive_function():
            recursive_function()
            boto3.client('ec2').describe_instances()
        recursive_function()
    """) == {'ec2': set(['describe_instances'])}


def test_mutual_recursion():
    assert aws_calls("""\
        import boto3
        ec2 = boto3.client('ec2')

        def a():
            b()
            ec2.run_instances()


        def b():
            ec2.describe_instances()
            a()
        a()
    """) == {'ec2': set(['describe_instances', 'run_instances'])}


def test_inferred_module_type_tracks_assignment():
    assert known_types_for_module("""\
        import boto3
        a = boto3
    """) == {'boto3': Boto3ModuleType(),
             'a': Boto3ModuleType()}


def test_inferred_module_type_tracks_multi_assignment():
    assert known_types_for_module("""\
        import boto3
        a = b = c = boto3
    """) == {'boto3': Boto3ModuleType(),
             'a': Boto3ModuleType(),
             'b': Boto3ModuleType(),
             'c': Boto3ModuleType()}


def test_inferred_client_create_type():
    assert known_types_for_module("""\
        import boto3
        a = boto3.client
    """) == {'boto3': Boto3ModuleType(),
             'a': Boto3CreateClientType()}


def test_inferred_client_type():
    assert known_types_for_module("""\
        import boto3
        a = boto3.client('ec2')
    """) == {'boto3': Boto3ModuleType(),
             'a': Boto3ClientType('ec2')}


def test_inferred_client_type_each_part():
    assert known_types_for_module("""\
        import boto3
        a = boto3.client
        b = a('ec2')
    """) == {'boto3': Boto3ModuleType(),
             'a': Boto3CreateClientType(),
             'b': Boto3ClientType('ec2')}


def test_infer_client_method():
    assert known_types_for_module("""\
        import boto3
        a = boto3.client('ec2').describe_instances
    """) == {'boto3': Boto3ModuleType(),
             'a': Boto3ClientMethodType('ec2', 'describe_instances')}


def test_infer_client_method_called():
    assert known_types_for_module("""\
        import boto3
        a = boto3.client('ec2').describe_instances()
    """) == {'boto3': Boto3ModuleType(),
             'a': Boto3ClientMethodCallType('ec2', 'describe_instances')}


def test_infer_type_on_function_scope():
    assert known_types_for_function("""\
        import boto3
        def foo():
            d = boto3.client('dynamodb')
            e = d.list_tables()
        foo()
    """, name='foo') == {
        'd': Boto3ClientType('dynamodb'),
        'e': Boto3ClientMethodCallType('dynamodb', 'list_tables')
    }


def test_can_understand_return_types():
    assert known_types_for_module("""\
        import boto3
        def create_client():
            d = boto3.client('dynamodb')
            return d
        e = create_client()
    """) == {
        'boto3': Boto3ModuleType(),
        'create_client': FunctionType(Boto3ClientType('dynamodb')),
        'e': Boto3ClientType('dynamodb'),
    }


def test_type_equality():
    assert Boto3ModuleType() == Boto3ModuleType()
    assert Boto3CreateClientType() == Boto3CreateClientType()
    assert Boto3ModuleType() != Boto3CreateClientType()

    assert Boto3ClientType('s3') == Boto3ClientType('s3')
    assert Boto3ClientType('s3') != Boto3ClientType('ec2')
    assert Boto3ClientType('s3') == Boto3ClientType('s3')

    assert (Boto3ClientMethodType('s3', 'list_objects') ==
            Boto3ClientMethodType('s3', 'list_objects'))
    assert (Boto3ClientMethodType('ec2', 'describe_instances') !=
            Boto3ClientMethodType('s3', 'list_object'))
    assert (Boto3ClientMethodType('ec2', 'describe_instances') !=
            Boto3CreateClientType())


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
             's3': set(['get_object'])}


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


def test_multiple_targets():
    assert aws_calls("""\
        import boto3
        a = b = boto3.client('dynamodb')
        b.list_tables()
        a.create_table()
    """) == {'dynamodb': set(['create_table', 'list_tables'])}


def test_in_function():
    assert aws_calls("""\
        import boto3
        def foo():
            d = boto3.client('dynamodb')
            d.list_tables()
        foo()
    """) == {'dynamodb': set(['list_tables'])}


def test_ignores_built_in_scope():
    assert aws_calls("""\
        import boto3
        a = boto3.client('dynamodb')
        def foo():
            if a is not None:
                try:
                    a.list_tables()
                except Exception as e:
                    a.create_table()
        foo()
    """) == {'dynamodb': set(['create_table', 'list_tables'])}


def test_understands_scopes():
    assert aws_calls("""\
        import boto3, mock
        d = mock.Mock()
        def foo():
            d = boto3.client('dynamodb')
        d.list_tables()
    """) == {}


def test_function_return_types():
    assert aws_calls("""\
        import boto3
        def create_client():
            return boto3.client('dynamodb')
        create_client().list_tables()
    """) == {'dynamodb': set(['list_tables'])}


def test_propagates_return_types():
    assert aws_calls("""\
        import boto3
        def create_client1():
            return create_client2()
        def create_client2():
            return create_client3()
        def create_client3():
            return boto3.client('dynamodb')
        create_client1().list_tables()
    """) == {'dynamodb': set(['list_tables'])}


def test_decorator_list_is_ignored():
    assert known_types_for_function("""\
        import boto3
        import decorators

        @decorators.retry(10)
        def foo():
            d = boto3.client('dynamodb')
            e = d.list_tables()
        foo()
    """, name='foo') == {
        'd': Boto3ClientType('dynamodb'),
        'e': Boto3ClientMethodCallType('dynamodb', 'list_tables')
    }


def test_can_map_function_params():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        def make_call(client):
            a = 1
            return client.list_tables()
        make_call(d)
    """) == {'dynamodb': set(['list_tables'])}


def test_can_understand_shadowed_vars_from_func_arg():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        def make_call(d):
            return d.list_tables()
        make_call('foo')
    """) == {}


def test_can_understand_shadowed_vars_from_local_scope():
    assert aws_calls("""\
        import boto3, mock
        d = boto3.client('dynamodb')
        def make_call(e):
            d = mock.Mock()
            return d.list_tables()
        make_call(d)
    """) == {}


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


def test_multiple_function_calls():
    assert aws_calls("""\
        import boto3, mock
        m = mock.Mock()
        d = boto3.client('dynamodb')
        def make_call(other, client):
            a = 1
            other.create_table()
            return other_call(a, 2, 3, client)
        def other_call(a, b, c, client):
            return client.list_tables()
        make_call(m, d)
    """) == {'dynamodb': set(['list_tables'])}


def test_can_lookup_var_names_to_functions():
    assert aws_calls("""\
        import boto3
        service_name = 'dynamodb'
        d = boto3.client(service_name)
        d.list_tables()
    """) == {'dynamodb': set(['list_tables'])}


def test_map_string_literals_across_scopes():
    assert aws_calls("""\
        import boto3
        service_name = 'dynamodb'
        def foo():
            service_name = 's3'
            d = boto3.client(service_name)
            d.list_buckets()
        d = boto3.client(service_name)
        d.list_tables()
        foo()
    """) == {'s3': set(['list_buckets']), 'dynamodb': set(['list_tables'])}


def test_can_handle_lambda_keyword():
    assert aws_calls("""\
        def foo(a):
            return sorted(bar.values(),
                          key=lambda x: x.baz[a - 1],
                          reverse=True)
        bar = {}
        foo(12)
    """) == {}


def test_dict_comp_with_no_client_calls():
    assert aws_calls("""\
        import boto3
        foo = {i: i for i in range(10)}
    """) == {}


def test_can_handle_gen_expr():
    assert aws_calls("""\
        import boto3
        ('a' for y in [1,2,3])
    """) == {}


def test_can_detect_calls_in_gen_expr():
    assert aws_calls("""\
        import boto3
        service_name = 'dynamodb'
        d = boto3.client('dynamodb')
        (d.list_tables() for i in [1,2,3])
    """) == {'dynamodb': set(['list_tables'])}


def test_can_handle_gen_from_call():
    assert aws_calls("""\
        import boto3
        service_name = 'dynamodb'
        d = boto3.client('dynamodb')
        (i for i in d.list_tables())
    """) == {'dynamodb': set(['list_tables'])}


def test_can_detect_calls_in_multiple_gen_exprs():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        (d for i in [1,2,3])
        (d.list_tables() for j in [1,2,3])
    """) == {'dynamodb': set(['list_tables'])}


def test_multiple_gen_exprs():
    assert aws_calls("""\
        (i for i in [1,2,3])
        (j for j in [1,2,3])
    """) == {}


def test_can_handle_list_expr_with_api_calls():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        [d.list_tables() for y in [1,2,3]]
    """) == {'dynamodb': set(['list_tables'])}


def test_can_handle_multiple_listcomps():
    assert aws_calls("""\
        bar_key = 'bar'
        baz_key = 'baz'
        items = [{'foo': 'sun', 'bar': 'moon', 'baz': 'stars'}]
        foos = [i['foo'] for i in items]
        bars = [j[bar_key] for j in items]
        bazs = [k[baz_key] for k in items]
    """) == {}


def test_can_analyze_lambda_function():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3
        app = Chalice(app_name='james1')
        ec2 = boto3.client('ec2')
        @app.lambda_function(name='lambda1')
        def index():
            ec2.describe_instances()
            return {}
    """) == {'ec2': set(['describe_instances'])}


def test_can_analyze_schedule():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3
        app = Chalice(app_name='james1')
        s3cli = boto3.client('s3')
        @app.schedule('rate(1 hour)')
        def index():
            s3cli.list_buckets()
            return {}
    """) == {'s3': set(['list_buckets'])}


def test_can_analyze_combination():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3
        app = Chalice(app_name='james1')
        s3 = boto3.client('s3')
        ec = boto3.client('ec2')
        @app.route('/')
        def index():
            ec2.describe_instances()
            return {}
        @app.schedule('rate(1 hour)')
        def index_sc():
            s3.list_buckets()
            return {}

        @app.lambda_function(name='lambda1')
        def index_lm():
            ec.describe_instances()
            return {}

        @random
        def foo():
            return {}

    """) == {'s3': set(['list_buckets']),
             'ec2': set(['describe_instances'])}


def test_can_handle_dict_comp():
    assert aws_calls("""\
        import boto3
        ddb = boto3.client('dynamodb')
        tables = {t: t for t in ddb.list_tables()}
    """) == {'dynamodb': set(['list_tables'])}


def test_can_handle_dict_comp_if():
    assert aws_calls("""\
        import boto3
        ddb = boto3.client('dynamodb')
        tables = {t: t for t in [1] if ddb.list_tables()}
    """) == {'dynamodb': set(['list_tables'])}


def test_can_handle_comp_ifs():
    assert aws_calls("""\
        [(x,y) for x in [1,2,3,4] for y in [1,2,3,4] if x % 2 == 0]
    """) == {}


def test_can_handle_dict_comp_ifs():
    assert aws_calls("""\
        import boto3
        d = boto3.client('dynamodb')
        {x: y for x in d.create_table()\
         for y in d.update_table()\
         if d.list_tables()}
        {x: y for x in d.create_table()\
         for y in d.update_table()\
         if d.list_tables()}
    """) == {'dynamodb': set(['list_tables', 'create_table', 'update_table'])}


@pytest.mark.skipif(sys.version[0] == '2', reason=(
    'Async await syntax is not in Python 2'
))
def test_can_handle_async_await():
    assert aws_calls("""\
        import boto3
        import asyncio
        async def test():
            d = boto3.client('dynamodb')
            d.list_tables()
            await asyncio.sleep(1)
        test()
    """) == {'dynamodb': set(['list_tables'])}


def test_can_analyze_custom_auth():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3

        ec2 = boto3.client('ec2')
        app = Chalice(app_name='custom-auth')

        @app.authorizer()
        def index(auth_request):
            ec2.describe_instances()
            return {}
    """) == {'ec2': set(['describe_instances'])}


def test_can_analyze_s3_events():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3

        s3 = boto3.client('s3')
        app = Chalice(app_name='s3-event')

        @app.on_s3_event(bucket='mybucket')
        def index(event):
            s3.list_buckets()
            return {}
    """) == {'s3': set(['list_buckets'])}


def test_can_analyze_sns_events():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3

        s3 = boto3.client('s3')
        app = Chalice(app_name='sns-event')

        @app.on_sns_message(topic='mytopic')
        def index(event):
            s3.list_buckets()
            return {}
    """) == {'s3': set(['list_buckets'])}


def test_can_analyze_sqs_events():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3

        s3 = boto3.client('s3')
        app = Chalice(app_name='sqs-event')

        @app.on_sqs_message(queue='myqueue')
        def index(event):
            s3.list_buckets()
            return {}
    """) == {'s3': set(['list_buckets'])}


def test_can_analyze_transfer_manager_methods():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3

        s3 = boto3.client('s3')
        app = Chalice(app_name='sqs-event')

        @app.on_s3_event(bucket='mybucket')
        def index(event):
            s3.download_file(event.bucket, event.key, 'foo')
            return {}
    """) == {'s3': set(['download_file'])}


def test_can_handle_replacing_function_name():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3

        app = Chalice(app_name='sqs-event')

        def index():
            pass

        @app.on_sqs_message(queue='myqueue')
        def index(event):
            foo = boto3.client('s3').list_buckets()

    """) == {'s3': set(['list_buckets'])}


def test_can_handle_multiple_shadowing():
    assert chalice_aws_calls("""\
        from chalice import Chalice
        import boto3

        app = Chalice(app_name='sqs-event')

        def index():
            pass

        @app.on_sqs_message(queue='myqueue')
        def index(event):
            foo = boto3.client('s3').list_buckets()

        @app.on_s3_event(bucket='mybucket')
        def index(event):
            bar = boto3.client('s3').head_bucket(Bucket='foo')

    """) == {'s3': set(['list_buckets', 'head_bucket'])}


# def test_tuple_assignment():
#     assert aws_calls("""\
#         import boto3
#         import some_other_thing
#         a, d = (1, boto3.client('dynamodb'))
#         d.list_tables()
#         d.create_table()
#     """) == {'dynamodb': set(['list_tables'])}


# def test_multiple_client_assignment():
#     assert aws_calls("""\
#         import boto3
#         import some_other_thing
#         s3, db = (boto3.client('s3'), boto3.client('dynamodb'))
#         db.list_tables()
#         s3.get_object(Bucket='a', Key='b')
#     """) == {'dynamodb': set(['list_tables'])
#             's3': set(['get_object'])}


# def test_understands_instance_methods():
#     assert aws_calls("""\
#         import boto3, mock
#         class Foo(object):
#             def make_call(self, client):
#                 return client.list_tables()
#
#         d = boto3.client('dynamodb')
#         instance = Foo()
#         instance.make_call(d)
#     """) == {'dynamodb': set(['list_tables'])}


# def test_understands_function_and_methods():
#     assert aws_calls("""\
#         import boto3, mock
#         class Foo(object):
#             def make_call(self, client):
#                 return foo_call(1, client)
#
#         def foo_call(a, client):
#             return client.list_tables()
#
#         d = boto3.client('dynamodb')
#         instance = Foo()
#         instance.make_call(d)
#     """) == {'dynamodb': set(['list_tables'])}


# def test_can_track_across_classes():
#     assert aws_calls("""\
#         import boto3
#         ddb = boto3.client('dynamodb')
#         class Helper(object):
#             def __init__(self, client):
#                 self.client = client
#             def foo(self):
#                 return self.client.list_tables()
#         h = Helper(ddb)
#         h.foo()
#     """) == {'dynamodb': set(['list_tables'])}
