"""
URL configuration for reconciliation app
"""
from django.urls import path
from reconciliation.views import upload_views, dashboard_views, mapping_views, data_validation_views, journal_views, admin_views, analytics_views, prt_wc_dashboard

app_name = 'reconciliation'

urlpatterns = [
    # Dashboard endpoints
    path('dashboard/', dashboard_views.pay_period_list, name='pay_period_list'),
    path('dashboard/<str:pay_period_id>/', dashboard_views.reconciliation_dashboard, name='dashboard'),
    path('dashboard/<str:pay_period_id>/download-accrual-journal/', dashboard_views.download_accrual_sage_journal, name='download_accrual_journal'),
    path('api/pay-periods/delete/', dashboard_views.delete_pay_periods, name='delete_pay_periods'),

    # Analytics dashboard
    path('analytics/', analytics_views.analytics_dashboard, name='analytics_dashboard'),
    path('analytics/query/', analytics_views.analytics_query, name='analytics_query'),

    # Monthly dashboard
    path('monthly-dashboard/', dashboard_views.monthly_dashboard, name='monthly_dashboard'),
    path('monthly-dashboard/download/', dashboard_views.download_comparison_data, name='download_comparison_data'),

    # FNE Payroll Comparison dashboard
    path('fne-dashboard/', dashboard_views.fne_dashboard, name='fne_dashboard'),
    path('fne-dashboard/download/', dashboard_views.download_fne_comparison, name='download_fne_comparison'),

    # Payroll Tax & Workcover dashboard
    path('prt-wc-dashboard/<str:period_id>/', prt_wc_dashboard.prt_wc_dashboard, name='prt_wc_dashboard'),
    path('prt-wc-dashboard/<str:period_id>/download-employee-breakdown/', prt_wc_dashboard.download_prt_wc_employee_breakdown, name='download_prt_wc_breakdown'),
    path('prt-wc-dashboard/<str:period_id>/download-sage-journal/', prt_wc_dashboard.download_prt_wc_sage_journal, name='download_prt_wc_sage_journal'),

    # Mapping verification and cost allocation endpoints
    path('verify-mapping/<str:pay_period_id>/', mapping_views.verify_tanda_mapping, name='verify_mapping'),
    path('api/save-mappings/<str:pay_period_id>/', mapping_views.save_location_mapping, name='save_location_mapping'),
    path('api/run-cost-allocation/<str:pay_period_id>/', mapping_views.run_cost_allocation, name='run_cost_allocation'),
    path('cost-allocation/<str:pay_period_id>/', mapping_views.cost_allocation_view, name='cost_allocation_view'),
    path('api/save-cost-allocations/<str:pay_period_id>/', mapping_views.save_cost_allocations, name='save_cost_allocations'),
    path('api/save-all-allocations/<str:pay_period_id>/', mapping_views.save_all_allocations, name='save_all_allocations'),
    path('api/apply-bulk-source/<str:pay_period_id>/', mapping_views.apply_bulk_source, name='apply_bulk_source'),

    # Data validation endpoints
    path('validation/summary/<str:pay_period_id>/', data_validation_views.validation_summary_view, name='validation_summary'),
    path('validation/<uuid:upload_id>/', data_validation_views.validation_result_view, name='validation_result'),

    # Journal generation endpoints
    path('journal/<str:pay_period_id>/', journal_views.generate_journal, name='generate_journal'),
    path('journal/<str:pay_period_id>/download/', journal_views.download_journal, name='download_journal'),
    path('journal/<str:pay_period_id>/download-sage/', journal_views.download_journal_sage, name='download_journal_sage'),
    path('journal/<str:pay_period_id>/download-xero/', journal_views.download_journal_xero, name='download_journal_xero'),
    path('journal/<str:pay_period_id>/download-snapshot/', journal_views.download_employee_snapshot, name='download_employee_snapshot'),
    path('leave-accrual/<str:this_period_id>/', journal_views.leave_accrual_auto_period, name='leave_accrual_auto'),
    path('leave-accrual/<str:last_period_id>/<str:this_period_id>/', journal_views.generate_leave_accrual_journal, name='generate_leave_accrual'),
    path('leave-accrual/<str:last_period_id>/<str:this_period_id>/download-<str:leave_type>-sage/', journal_views.download_leave_journal_sage, name='download_leave_journal_sage'),
    path('leave-accrual/<str:last_period_id>/<str:this_period_id>/download-<str:leave_type>-employees/', journal_views.download_leave_employee_breakdown, name='download_leave_employee_breakdown'),
    path('leave-accrual/<str:last_period_id>/<str:this_period_id>/download-cost-allocation/', journal_views.download_employee_cost_allocation, name='download_employee_cost_allocation'),

    # Upload endpoints
    path('uploads/multi/', upload_views.multi_upload, name='multi_upload'),
    path('api/uploads/smart/', upload_views.smart_upload, name='smart_upload'),
    path('api/uploads/accrual/', upload_views.accrual_upload, name='accrual_upload'),
    path('api/payroll-tax-workcover/', upload_views.payroll_tax_workcover_process, name='payroll_tax_workcover'),
    path('api/uploads/<uuid:upload_id>/override/', upload_views.override_upload, name='override_upload'),
    path('api/uploads/', upload_views.list_uploads, name='list_uploads'),
    path('api/uploads/<uuid:upload_id>/', upload_views.upload_detail, name='upload_detail'),

    # Admin endpoints
    path('employees/import/', admin_views.import_employees, name='import_employees'),
]