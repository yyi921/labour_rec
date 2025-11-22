"""
URL configuration for reconciliation app
"""
from django.urls import path
from reconciliation.views import upload_views, dashboard_views

app_name = 'reconciliation'

urlpatterns = [
    # Dashboard endpoints
    path('dashboard/', dashboard_views.pay_period_list, name='pay_period_list'),
    path('dashboard/<str:pay_period_id>/', dashboard_views.reconciliation_dashboard, name='dashboard'),

    # Upload endpoints
    path('api/uploads/smart/', upload_views.smart_upload, name='smart_upload'),
    path('api/uploads/<uuid:upload_id>/override/', upload_views.override_upload, name='override_upload'),
    path('api/uploads/', upload_views.list_uploads, name='list_uploads'),
    path('api/uploads/<uuid:upload_id>/', upload_views.upload_detail, name='upload_detail'),
]