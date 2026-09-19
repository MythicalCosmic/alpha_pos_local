"""Popular-product reporting tests."""

import pytest
from django.utils import timezone

from base.models import Category, Order, OrderItem, Product
from customers.services.product_service import CustomerProductService


pytestmark = pytest.mark.django_db


class TestPopularProductsFilter:
    def test_popular_puts_top_seller_first(self, regular_user, category):
        hot = Product.objects.create(name="Hot", price="10.00", category=category)
        cold = Product.objects.create(name="Cold", price="10.00", category=category)
        order = Order.objects.create(
            user=regular_user,
            status="COMPLETED",
            is_paid=True,
            display_id=1,
            subtotal="10.00",
            total_amount="10.00",
            paid_at=timezone.now(),
        )
        OrderItem.objects.create(
            order=order,
            product=hot,
            quantity=50,
            price="10.00",
        )

        result, status = CustomerProductService.get_all_products(popular=True)

        assert status == 200
        assert result["data"]["products"][0]["id"] == hot.id

        unranked_result, _ = CustomerProductService.get_all_products(popular=False)
        assert unranked_result["data"]["products"][0]["id"] == cold.id

    def test_popular_respects_category(self, regular_user, category):
        other = Category.objects.create(name="Other")
        in_category = Product.objects.create(
            name="InCat",
            price="10.00",
            category=category,
        )
        Product.objects.create(
            name="Elsewhere",
            price="10.00",
            category=other,
        )
        order = Order.objects.create(
            user=regular_user,
            status="COMPLETED",
            is_paid=True,
            display_id=1,
            subtotal="10.00",
            total_amount="10.00",
            paid_at=timezone.now(),
        )
        OrderItem.objects.create(
            order=order,
            product=in_category,
            quantity=5,
            price="10.00",
        )

        result, status = CustomerProductService.get_all_products(
            popular=True,
            category_ids=[category.id],
        )

        assert status == 200
        assert {product["name"] for product in result["data"]["products"]} == {
            "InCat",
        }


def _sell(user, product, quantity):
    order = Order.objects.create(
        user=user,
        status="COMPLETED",
        is_paid=True,
        display_id=Order.objects.count() + 1,
        subtotal="10.00",
        total_amount="10.00",
        paid_at=timezone.now(),
    )
    OrderItem.objects.create(order=order, product=product, quantity=quantity, price="10.00")


class TestPopularityCache:
    def test_ranking_is_reused_within_the_ttl(self, regular_user, category, django_assert_max_num_queries):
        first = Product.objects.create(name="First", price="10.00", category=category)
        second = Product.objects.create(name="Second", price="10.00", category=category)
        _sell(regular_user, first, 5)

        result, _ = CustomerProductService.get_all_products(popular=True)
        assert [p["id"] for p in result["data"]["products"]][:2] == [first.id, second.id]

        # A new best seller does not reorder the menu until the ranking expires...
        _sell(regular_user, second, 50)
        with django_assert_max_num_queries(3):
            cached, _ = CustomerProductService.get_all_products(popular=True)
        assert [p["id"] for p in cached["data"]["products"]][:2] == [first.id, second.id]

        # ...but product changes show at once: only the ranking is cached.
        Product.objects.filter(pk=first.pk).update(price="12.50")
        fresh, _ = CustomerProductService.get_all_products(popular=True)
        assert fresh["data"]["products"][0]["price"] == "12.50"

    def test_expired_ranking_is_recomputed(self, regular_user, category, monkeypatch):
        from customers.services import product_service

        first = Product.objects.create(name="First", price="10.00", category=category)
        second = Product.objects.create(name="Second", price="10.00", category=category)
        _sell(regular_user, first, 5)
        CustomerProductService.get_all_products(popular=True)
        _sell(regular_user, second, 50)

        monkeypatch.setattr(product_service, "POPULARITY_TTL_SECONDS", 0)
        result, _ = CustomerProductService.get_all_products(popular=True)
        assert [p["id"] for p in result["data"]["products"]][:2] == [second.id, first.id]

    def test_popular_pages_keep_the_ranked_order(self, regular_user, category):
        products = [Product.objects.create(name=f"P{i}", price="10.00", category=category) for i in range(5)]
        for quantity, product in enumerate(products, start=1):
            _sell(regular_user, product, quantity)
        expected = [p.id for p in reversed(products)]

        seen = []
        for page in (1, 2, 3):
            result, status = CustomerProductService.get_all_products(popular=True, page=page, per_page=2)
            assert status == 200
            seen += [p["id"] for p in result["data"]["products"]]
        assert seen == expected
