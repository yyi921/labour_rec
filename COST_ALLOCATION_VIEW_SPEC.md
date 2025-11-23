# Cost Allocation View - Detailed Specification

## Overview
Complex view allowing users to review and override employee cost allocations with multiple viewing modes and filters.

## Features Breakdown

### 1. View Modes (Tabs)
- **$ Value by GL** - Shows dollar amounts grouped by GL account (6345 Salaries, 2310 AL Provision, 6370 Super, etc.)
- **% Allocation by Cost Center** - Shows percentage allocation by cost center (421-5000, 910-9100, etc.)

### 2. Data Sources
- **IQB** (default) - Allocation based on IQB cost account codes
- **Tanda** - Allocation based on Tanda timesheet locations
- **Override** - Manual user input

### 3. Filters
- **Sage Location** (421 Marmor, 422 Terasu, 910 Shared Services, etc.)
- **Sage Department** (50 Food, 70 Accommodation, 90 Finance, etc.)

### 4. Employee Table Columns
- Employee Code
- Employee Name  
- Total Cost
- IQB Allocation (%)
- Tanda Allocation (% or "No Tanda Timesheets Found")
- Override Input (text box: "###-##00: %, ###-##00: %")
- Source Selection (Radio/Checkbox: IQB / Tanda / Override)

### 5. GL Summary (Top of Page)
When in "$ Value by GL" view:
- Show total by GL account
- Verify totals match IQB Grand Total from Dashboard

### 6. Save & Review Flow
1. User selects source (IQB/Tanda/Override) for employees
2. Clicks "Save"
3. Navigate to "Review Changes" page showing:
   - Employees with changes
   - Old vs New allocation
   - Comments field
   - "Go Back" or "Finalize" buttons
4. "Finalize" marks allocation ready for Sage Journal Generation

### 7. Persistence
- Checkbox selections (IQB/Tanda/Override) persist when:
  - Switching between tabs ($ vs %)
  - Changing filters (Location/Department)
  - Refreshing page

## Implementation Plan

### Phase 1: Models & Data Loading
- SageLocation model
- SageDepartment model
- Load from CSV files
- Link to CostAllocationRule model

### Phase 2: View & Controller
- cost_allocation_view() - Main view
- Get employee allocations with all sources
- Apply filters
- Calculate GL totals

### Phase 3: Frontend (Template)
- Tab interface ($ vs %)
- Filter dropdowns
- Employee table with checkboxes
- Override input validation
- AJAX save

### Phase 4: Review & Finalize
- allocation_review() view
- Show changes
- Comments
- Finalize endpoint
- Update PayPeriod status

## Technical Details

### Cost Account Format
`421-5000`
- Location: 421 (Marmor)
- Department: 50 (Food)

### GL Account Mapping
(From cost_allocation.py)
- 6345: Salaries & Wages
- 6370: Superannuation
- 6300: Annual Leave
- 6310: Sick Leave
- 6320: Long Service Leave

### Override Input Format
Text box accepts:
```
421-5000: 60, 422-5000: 40
```
Or:
```
421-5000: 60%, 422-5000: 40%
```

Validation:
- Must sum to 100%
- Cost accounts must be valid format (###-####)
- Percentages must be numbers

