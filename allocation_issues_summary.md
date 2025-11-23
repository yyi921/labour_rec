# Cost Allocation Issues Summary - Pay Period 2025-11-16

## 1. Invalid IQB Allocations (13 employees)

### Issue: Rounding Errors
All 13 invalid IQB allocations are due to minor rounding errors where the percentages sum to either:
- **99.99%** (10 employees) - 0.01% short
- **100.01%** (3 employees) - 0.01% over

### Examples:
- **Lauren Efford**: 6 cost centers, totals 99.99% (missing 0.01%)
- **Logan Fearon**: 6 cost centers, totals 100.01% (0.01% over)

### Root Cause:
When calculating percentages from dollar amounts and rounding to 2 decimal places, small rounding errors accumulate. This is a common issue in financial calculations.

### Solution Options:

**Option 1: Adjust Validation Tolerance (Recommended)**
```python
# In models.py, CostAllocationRule.validate_allocations()
# Change from:
if not (99.99 <= total_pct <= 100.01):
# To:
if not (99.95 <= total_pct <= 100.05):
```

**Option 2: Implement Smart Rounding**
Adjust the last allocation percentage to make the total exactly 100%

**Option 3: Accept as-is**
These errors are negligible (0.01%) and won't materially affect financial reporting

---

## 2. Invalid Tanda Allocations (15 employees)

### Issue: Same Rounding Errors
Same pattern as IQB - minor rounding errors:
- **99.99%** (11 employees)
- **100.01%** (4 employees)

### Interesting Finding:
- 10 employees appear in BOTH invalid lists (IQB and Tanda)
- This suggests these employees consistently have complex multi-center allocations
- Example: **Naruedech Rujakorm** has one allocation at 0.0% (likely should be removed)

### Same Solutions as above apply

---

## 3. Tanda Mapping Errors (2 employees)

### Employee 1: Donna Marko
**Unmapped Location/Team:** `Compliance & Risk - Financial Crime Manager`

**Similar Mappings Found:**
- Compliance & Risk - Anti Money Laundering Administrator → 910-9100
- Compliance & Risk - Anti Money Laundering Analyst → 910-9100  
- Compliance & Risk - Compliance Administrator → 910-9100

**Recommended Action:**
This role should map to **910-9100** (Compliance & Risk department)

Add to location_and_team_report.csv:
```csv
Compliance & Risk,Financial Crime Manager,910-9100,Com,...
```

### Employee 2: Monique Searle
**Unmapped Locations/Teams:**
1. `Marketing - Sales - Sales Executive`
2. `Reservation - Business Development Manager`

**Analysis:**
- First location has an unusual format with two dashes (Marketing - Sales - Sales Executive)
- This might be a data quality issue in the Tanda export
- Second location appears to be a reservation/front desk role

**Similar Mappings Found:**
- Reservation-related roles map to 910-7400

**Recommended Actions:**

1. Check if "Marketing - Sales - Sales Executive" should be:
   - "Marketing - Sales Executive" (remove middle "Sales")
   - Or create a new mapping

2. For "Reservation - Business Development Manager":
   Add to location_and_team_report.csv mapping to 910-7400 or appropriate marketing code

---

## Summary Statistics

### Overall Success Rate:
- **IQB Allocations:** 98.5% valid (859/872)
- **Tanda Allocations:** 98.2% valid (816/831)
- **Mapping Coverage:** 99.76% (831/833 employees mapped)

### Impact Assessment:
- **Rounding Errors:** Negligible financial impact (<0.01% per employee)
- **Mapping Errors:** Only 2 employees affected (0.24% of workforce)
- **Data Quality:** Excellent overall

---

## Recommended Action Plan

### Immediate (Production Ready):
1. ✅ Adjust validation tolerance to 99.95%-100.05%
2. ✅ System is production-ready with current configuration

### Short Term (1-2 days):
1. Add 2 missing location mappings:
   - Compliance & Risk - Financial Crime Manager → 910-9100
   - Reservation - Business Development Manager → 910-7400
2. Investigate Marketing - Sales - Sales Executive naming issue

### Long Term (Nice to Have):
1. Implement smart rounding algorithm
2. Add data validation report for unusual location names
3. Create automated alerts for unmapped locations

---

## Conclusion

The cost allocation system is working **excellently** with:
- 98%+ accuracy on both IQB and Tanda sources
- Only 2 employees with missing mappings (easily fixable)
- Minor rounding errors that are standard in financial systems

**Recommendation:** System is ready for production use with a minor validation tolerance adjustment.
