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
