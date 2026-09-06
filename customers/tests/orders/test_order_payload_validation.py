"""Reject malformed order input before it reaches money or stock writes."""
import json
import pytest
from django.test import RequestFactory
from customers.requests.order_requests import create_order_request


def _parse(items):
    request = RequestFactory().post('/orders', data=json.dumps({'user_id': 1, 'items': items}), content_type='application/json')
    return create_order_request(request)


@pytest.mark.parametrize('item', [None, 5, True, 'product_id', ['product_id']])
def test_create_rejects_non_object_items(item):
    data, error = _parse([item])
    assert data is None
    assert error[1] == 422


@pytest.mark.parametrize('product_id', [True, 1.5, {'id': 1}, [1], 'abc', 2**63])
def test_create_rejects_invalid_product_identifiers(product_id):
    data, error = _parse([{'product_id': product_id, 'quantity': 1}])
    assert data is None
    assert error[1] == 422


@pytest.mark.parametrize('quantity', [True, 2**31])
def test_create_rejects_boolean_or_unstorable_quantity(quantity):
    data, error = _parse([{'product_id': 1, 'quantity': quantity}])
    assert data is None
    assert error[1] == 422


def test_create_normalizes_numeric_product_identifier_for_service_lookup():
    data, error = _parse([{'product_id': '1', 'quantity': 1}])
    assert error is None
    assert data['items'][0]['product_id'] == 1


@pytest.mark.parametrize('product_id', [True, 1.5, {'id': 1}, [1], 'abc', 2**63])
@pytest.mark.parametrize('package, service_name, method_name', [('customers', 'CustomerOrderService', 'add_item_to_order'), ('waiters', 'WaiterOrderService', 'add_item')])
def test_add_item_rejects_invalid_id_before_business_writes(product_id, package, service_name, method_name, monkeypatch):
    import importlib
    import inspect
    from types import SimpleNamespace
    from unittest.mock import Mock

    views = importlib.import_module(f'{package}.views.order_views')
    service = getattr(views, service_name)
    operation = Mock(side_effect=AssertionError('invalid input reached business writes'))
    monkeypatch.setattr(service, method_name, operation)
    request = RequestFactory().post('/orders/1/add-item', data=json.dumps({'product_id': product_id}), content_type='application/json')
    request.user = SimpleNamespace(id=1, role='ADMIN')
    response = inspect.unwrap(views.add_item)(request, 1)
    assert response.status_code == 422
    operation.assert_not_called()


@pytest.mark.parametrize('package, service_name, method_name', [('customers', 'CustomerOrderService', 'add_item_to_order'), ('waiters', 'WaiterOrderService', 'add_item')])
def test_add_item_normalizes_numeric_string_id(package, service_name, method_name, monkeypatch):
    import importlib
    import inspect
    from types import SimpleNamespace
    from unittest.mock import Mock

    views = importlib.import_module(f'{package}.views.order_views')
    operation = Mock(return_value=({'success': True}, 200))
    monkeypatch.setattr(getattr(views, service_name), method_name, operation)
    request = RequestFactory().post('/orders/1/add-item', data=json.dumps({'product_id': '001', 'quantity': 2}), content_type='application/json')
    request.user = SimpleNamespace(id=1, role='ADMIN')
    assert inspect.unwrap(views.add_item)(request, 1).status_code == 200
    assert operation.call_args.args[:3] == (1, 1, 2)


@pytest.mark.parametrize('field', ['customer_id', 'delivery_person_id'])
@pytest.mark.parametrize('value', [True, False, 1.5, {'id': 1}, [1], 'abc', 2**63, 0, -1])
def test_create_rejects_invalid_order_reference_ids(field, value):
    payload = {'user_id': 1, 'items': [{'product_id': 1}], field: value}
    request = RequestFactory().post('/orders', data=json.dumps(payload), content_type='application/json')
    data, error = create_order_request(request)
    assert data is None
    assert error[1] == 422
    assert field in error[0]['errors']


@pytest.mark.parametrize('field', ['customer_id', 'delivery_person_id'])
def test_create_normalizes_order_reference_ids(field):
    payload = {'user_id': 1, 'items': [{'product_id': 1}], field: '001'}
    request = RequestFactory().post('/orders', data=json.dumps(payload), content_type='application/json')
    data, error = create_order_request(request)
    assert error is None
    assert data[field] == 1


@pytest.mark.django_db
@pytest.mark.parametrize('field', ['product_id', 'place_id', 'table_id'])
@pytest.mark.parametrize('value', [True, 1.5, 2**63, {'id': 1}])
def test_waiter_create_rejects_invalid_reference_ids(field, value, regular_user, product):
    from base.models import Order
    from waiters.services.order_service import WaiterOrderService

    regular_user.role = 'WAITER'
    regular_user.save(update_fields=['role'])
    kwargs = {'user_id': regular_user.id, 'items': [{'product_id': product.id}]}
    if field == 'product_id':
        kwargs['items'][0]['product_id'] = value
    else:
        kwargs[field] = value
    before = Order.objects.count()
    result, status = WaiterOrderService.create_order(**kwargs)
    assert status == 422, result
    assert Order.objects.count() == before


@pytest.mark.parametrize('field', ['customer_id', 'delivery_person_id'])
@pytest.mark.parametrize('value', [None, ''])
def test_create_keeps_empty_optional_reference_unset(field, value):
    payload = {'user_id': 1, 'items': [{'product_id': 1}], field: value}
    request = RequestFactory().post('/orders', data=json.dumps(payload), content_type='application/json')
    data, error = create_order_request(request)
    assert error is None
    assert data[field] is None
