# Data Validation Setup

## Overview

The data validation system automatically validates uploaded files against master data and mappings. It runs after every upload (both smart_upload and override_upload) and displays results on a dedicated validation page.

## What Gets Validated

### For IQB Files (Micropay_IQB):

1. **Cost Account Code - Location Validation**
   - Checks if location codes (first 3 digits of cost account) exist in SageLocation
   - Example: `421-5000` → checks if location `421` exists

2. **Cost Account Code - Department Validation**
   - Checks if department codes (first 2 digits after dash) exist in SageDepartment
   - Example: `421-5000` → checks if department `50` exists

3. **Cost Account Code - Split Data Validation**
   - Checks if cost account codes exist in LocationMapping (Split_Data)
   - Example: `421-5000` must exist in the LocationMapping table

4. **Pay Comp/Add Ded Code Validation**
   - Checks if pay_comp_code values exist in PayCompCodeMapping
   - Example: `Normal`, `Overtime`, etc. must be in PayCompCode Mapping.csv

5. **Employee Code Validation**
   - Checks if employee codes exist in master_employee_file.csv
   - Example: Employee `111197` must be in the master file

### For Tanda Files (Tanda_Timesheet):

1. **Employee Code Validation**
   - Checks if employee_id values exist in master_employee_file.csv

## Files Created

### 1. `reconciliation/data_validator.py`
Contains the `DataValidator` class with all validation logic:
- `validate_upload(upload)` - Main validation function
- `_validate_cost_account_locations(upload)` - Location validation
- `_validate_cost_account_departments(upload)` - Department validation
- `_validate_cost_account_in_split_data(upload)` - Split data validation
- `_validate_pay_comp_codes(upload)` - Pay comp code validation
- `_validate_employee_codes(upload)` - Employee code validation (IQB)
- `_validate_employee_codes_tanda(upload)` - Employee code validation (Tanda)

### 2. `reconciliation/models.py` - Added ValidationResult model
```python
class ValidationResult(models.Model):
    upload = models.OneToOneField(Upload, on_delete=models.CASCADE)
    passed = models.BooleanField(default=False)
    validation_data = models.JSONField()  # Stores full validation results
    created_at = models.DateTimeField(auto_now_add=True)
```

### 3. `reconciliation/views/data_validation_views.py`
Contains the `validation_result_view()` function that displays validation results.

### 4. `reconciliation/templates/reconciliation/validation_result.html`
Beautiful validation results page with:
- Overall PASS/FAIL status with color coding
- Detailed test results for each validation
- Error details with examples
- Action buttons:
  - If PASSED: "Go to Reconciliation Dashboard"
  - If FAILED: "Back to Upload - Re-upload Corrected File"

### 5. Updated `reconciliation/views/upload_views.py`
- Added validation to `smart_upload()` function
- Added validation to `override_upload()` function
- Returns validation URL in API response

### 6. Updated `reconciliation/urls.py`
- Added route: `/validation/<upload_id>/`

### 7. Migration file
- `reconciliation/migrations/0012_validationresult.py`

### 8. Test script: `test_validation.py`
Helper script to test validation manually.

## How It Works

### Upload Flow:

1. User uploads file via `/api/uploads/smart/`
2. File is detected, parsed, and records are imported
3. **Validation runs automatically**
4. ValidationResult is saved to database
5. API returns:
```json
{
    "status": "success",
    "validation": {
        "passed": true/false,
        "validation_url": "/validation/<upload_id>/"
    }
}
```

### Viewing Results:

Navigate to: `/validation/<upload_id>/`

The page shows:
- ✓ Green PASS banner if all tests passed
- ✗ Red FAIL banner if any tests failed
- Detailed breakdown of each test
- Specific errors with examples
- Appropriate action buttons

## Testing

### Manual Testing:

1. Upload a file with validation issues (e.g., invalid cost account codes)
2. Check the API response for `validation_url`
3. Navigate to the validation URL
4. Review the validation results

### Using Test Script:

```bash
# List recent uploads
python test_validation.py

# Test specific upload
python test_validation.py <upload_id>
```

### Example Test Cases:

**Test Case 1: Invalid Location Code**
- Upload IQB file with cost account `100-5000` (location `100` doesn't exist)
- Expected: Location validation fails

**Test Case 2: Invalid Department Code**
- Upload IQB file with cost account `421-2100` (department `21` doesn't exist)
- Expected: Department validation fails

**Test Case 3: Missing in Split Data**
- Upload IQB file with cost account not in LocationMapping
- Expected: Split Data validation fails

**Test Case 4: Invalid Pay Comp Code**
- Upload IQB file with pay_comp_code not in PayCompCodeMapping
- Expected: Pay Comp Code validation fails

**Test Case 5: Invalid Employee Code**
- Upload file with employee code not in master_employee_file.csv
- Expected: Employee Code validation fails

## Master Data Requirements

For validation to work, ensure these files/tables are populated:

1. **SageLocation** - Loaded from `data/Sage Location.csv`
2. **SageDepartment** - Loaded from `data/Sage Department.csv`
3. **PayCompCodeMapping** - Loaded from `data/PayCompCode Mapping.csv`
4. **LocationMapping** - Loaded from Split_Data
5. **master_employee_file.csv** - Located at `data/master_employee_file.csv`

## API Response Format

### Smart Upload Response (with validation):
```json
{
    "status": "success",
    "message": "Micropay_IQB uploaded and processed successfully",
    "upload": {
        "upload_id": "uuid-here",
        "file_type": "Micropay_IQB",
        "records_imported": 1234
    },
    "period": {
        "period_id": "2025-11-16",
        "status": "uploaded"
    },
    "validation": {
        "passed": false,
        "validation_url": "/validation/uuid-here/"
    }
}
```

## Error Handling

- If master_employee_file.csv is missing, employee validation returns error message
- If no validation tests apply (e.g., Journal files), validation passes by default
- All errors are captured and displayed with examples (limited to first 10-20 for readability)

## Future Enhancements

Potential additions:
- Email notifications for failed validations
- Validation history tracking
- Bulk validation for multiple uploads
- Custom validation rules per client
- Auto-correction suggestions
