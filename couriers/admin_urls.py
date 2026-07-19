"""POS courier routes mounted under /api/couriers/ in config/urls.py.

List/assign admit POS staff; create/regenerate stay manager-only in the views.
"""
from django.urls import path

from couriers import admin_views

urlpatterns = [
    path('', admin_views.couriers_list, name='admin-couriers-list'),
    path('assign', admin_views.assign_order, name='admin-couriers-assign'),
    path('create', admin_views.create_courier, name='admin-couriers-create'),
    path('<int:courier_id>/regenerate', admin_views.regenerate_credential,
         name='admin-couriers-regen'),
]
