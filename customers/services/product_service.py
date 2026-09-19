import threading
import time
from datetime import timedelta

from django.core.paginator import Paginator
from django.utils import timezone

from base.repositories import ProductRepository, CategoryRepository
from base.helpers.response import ServiceResponse

# Best sellers change slowly, but ranking them aggregates every order line of
# the last 30 days (with refunds netted): ~150 ms on a till with a busy month.
# Rank once every few minutes; products and prices themselves are always read
# fresh, so a price or availability change still shows immediately.
POPULARITY_TTL_SECONDS = 300
_popularity_lock = threading.Lock()
_popularity = {'at': None, 'ranks': {}}


def popularity_ranks():
    """{product_id: rank} of the last 30 days' best sellers (0 = best)."""
    fresh = _popularity['at'] is not None and time.monotonic() - _popularity['at'] < POPULARITY_TTL_SECONDS
    if fresh:
        return _popularity['ranks']
    with _popularity_lock:
        if _popularity['at'] is not None and time.monotonic() - _popularity['at'] < POPULARITY_TTL_SECONDS:
            return _popularity['ranks']
        from base.repositories.order_item import POPULAR_WINDOW_DAYS, OrderItemRepository
        window_start = timezone.now() - timedelta(days=POPULAR_WINDOW_DAYS)
        rows = OrderItemRepository.get_top_products(date_from=window_start, limit=500)
        ranks = {row['product_id']: index for index, row in enumerate(rows)}
        _popularity.update(at=time.monotonic(), ranks=ranks)
        return ranks


def reset_popularity_cache():
    with _popularity_lock:
        _popularity.update(at=None, ranks={})


def _serialize_product(product):
    return {
        'id': product.id,
        'name': product.name,
        'description': product.description,
        'price': str(product.price),
        'colors': product.colors,
        'is_instant': product.is_instant,
        'category_id': product.category_id,
        'category': {
            'id': product.category.id,
            'name': product.category.name,
            'slug': product.category.slug,
        } if product.category else None,
        'is_deleted': product.is_deleted,
        'created_at': product.created_at.isoformat() if product.created_at else None,
        'updated_at': product.updated_at.isoformat() if product.updated_at else None,
    }


ALLOWED_ORDER_FIELDS = {
    'name', '-name', 'price', '-price',
    'created_at', '-created_at', 'updated_at', '-updated_at',
    'id', '-id', 'category__name', '-category__name',
}


class CustomerProductService:

    @staticmethod
    def get_all_products(page=1, per_page=20, search=None, category_ids=None,
                         order_by='-created_at', popular=True):
        queryset = ProductRepository.model.objects.select_related('category').filter(is_deleted=False, category__is_deleted=False, category__status='ACTIVE')

        if search:
            queryset = ProductRepository.search(queryset, search)

        if category_ids:
            if isinstance(category_ids, str):
                category_ids = [int(x.strip()) for x in category_ids.split(',') if x.strip().isdigit()]
            if category_ids:
                queryset = queryset.filter(category_id__in=category_ids)

        if order_by not in ALLOWED_ORDER_FIELDS:
            order_by = '-created_at'
        if popular:
            # Top-selling first (default), then the requested order. Composes
            # with the category/search filters above. The menu is small, so
            # sorting in Python beats a 500-branch SQL CASE on every request.
            ranks = popularity_ranks()
            unranked = len(ranks)
            # Rank ids only (cheap), then load just the requested page.
            ids = sorted(queryset.order_by(order_by).values_list('id', flat=True),
                         key=lambda pid: ranks.get(pid, unranked))
            paginator = Paginator(ids, per_page)
            page_obj = paginator.get_page(page)
            by_id = {p.id: p for p in queryset.filter(id__in=list(page_obj.object_list))}
            page_obj.object_list = [by_id[pid] for pid in page_obj.object_list if pid in by_id]
        else:
            page_obj, paginator = ProductRepository.paginate(queryset.order_by(order_by), page, per_page)

        products = [_serialize_product(p) for p in page_obj.object_list]

        return ServiceResponse.success(data={
            'products': products,
            'pagination': {
                'current_page': page_obj.number,
                'total_pages': paginator.num_pages,
                'total_products': paginator.count,
                'per_page': per_page,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
        })

    @staticmethod
    def get_products_by_category(category_id):
        category = CategoryRepository.get_by_id(category_id)
        if not category or category.status != 'ACTIVE':
            return ServiceResponse.not_found("Category not found")

        products = ProductRepository.get_by_category_id(category_id).select_related('category').order_by('name')
        return ServiceResponse.success(data={
            'products': [_serialize_product(p) for p in products],
            'category': {
                'id': category.id,
                'name': category.name,
                'slug': category.slug,
            },
        })

    @staticmethod
    def get_product_by_id(product_id):
        product = ProductRepository.get_by_id_cached(product_id)
        if not product or not product.category or product.category.is_deleted or product.category.status != 'ACTIVE':
            return ServiceResponse.not_found("Product not found")

        return ServiceResponse.success(data={'product': _serialize_product(product)})
