"""
URL configuration for reconciliation app
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

app_name = 'reconciliation'

# We'll add viewsets here later
router = DefaultRouter()

urlpatterns = [
    path('api/', include(router.urls)),
]