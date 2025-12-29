from reconciliation.models import ParsedData, PayPeriod

pay_period = PayPeriod.objects.filter(period_id='2025-11-30').first()
print(f"Period: {pay_period.period_id}")
print(f"has_cost_allocation flag: {pay_period.has_cost_allocation}")

records_with_iqb = ParsedData.objects.filter(
    pay_period__period_id='2025-11-30',
    iqb_cost_allocation__isnull=False
).count()

records_with_tanda = ParsedData.objects.filter(
    pay_period__period_id='2025-11-30',
    tanda_cost_allocation__isnull=False
).count()

print(f"Records with IQB cost allocation: {records_with_iqb}")
print(f"Records with Tanda cost allocation: {records_with_tanda}")

if records_with_iqb > 0 or records_with_tanda > 0:
    print("\nISSUE: Cost allocation data exists but has_cost_allocation flag is False!")
else:
    print("\nNo cost allocation data found.")
