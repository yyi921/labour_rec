"""
URL configuration for reconciliation app
"""
from django.urls import path
from reconciliation.views import upload_views, dashboard_views, mapping_views, data_validation_views

app_name = 'reconciliation'

urlpatterns = [
    # Dashboard endpoints
    path('dashboard/', dashboard_views.pay_period_list, name='pay_period_list'),
    path('dashboard/<str:pay_period_id>/', dashboard_views.reconciliation_dashboard, name='dashboard'),

    # Mapping verification and cost allocation endpoints
    path('verify-mapping/<str:pay_period_id>/', mapping_views.verify_tanda_mapping, name='verify_mapping'),
    path('api/save-mappings/<str:pay_period_id>/', mapping_views.save_location_mapping, name='save_location_mapping'),
    path('api/run-cost-allocation/<str:pay_period_id>/', mapping_views.run_cost_allocation, name='run_cost_allocation'),
    path('cost-allocation/<str:pay_period_id>/', mapping_views.cost_allocation_view, name='cost_allocation_view'),
    path('api/save-cost-allocations/<str:pay_period_id>/', mapping_views.save_cost_allocations, name='save_cost_allocations'),
    path('api/save-all-allocations/<str:pay_period_id>/', mapping_views.save_all_allocations, name='save_all_allocations'),

    # Data validation endpoints
    path('validation/<uuid:upload_id>/', data_validation_views.validation_result_view, name='validation_result'),

    # Upload endpoints
    path('api/uploads/smart/', upload_views.smart_upload, name='smart_upload'),
    path('api/uploads/<uuid:upload_id>/override/', upload_views.override_upload, name='override_upload'),
    path('api/uploads/', upload_views.list_uploads, name='list_uploads'),
    path('api/uploads/<uuid:upload_id>/', upload_views.upload_detail, name='upload_detail'),
]