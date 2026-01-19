"""
MCP Server for Labour Reconciliation Database
Provides tools to query payroll data via Claude Code
"""
import json
from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from mcp.server.fastmcp import FastMCP

from .database import execute_query, execute_single

# Initialize FastMCP server
mcp = FastMCP("Labour Reconciliation")


# Helper functions

def resolve_location(location_name: str) -> Optional[dict]:
    """
    Resolve a location name to its ID.
    Handles partial matches and common aliases.
    """
    # Exact match first
    result = execute_single(
        "SELECT location_id, location_name FROM reconciliation_sagelocation "
        "WHERE LOWER(location_name) = LOWER(%s)" if is_postgresql() else
        "SELECT location_id, location_name FROM reconciliation_sagelocation "
        "WHERE LOWER(location_name) = LOWER(?)",
        (location_name,)
    )
    if result:
        return result

    # Partial match (contains)
    result = execute_single(
        "SELECT location_id, location_name FROM reconciliation_sagelocation "
        "WHERE LOWER(location_name) LIKE LOWER(%s) ORDER BY location_id LIMIT 1" if is_postgresql() else
        "SELECT location_id, location_name FROM reconciliation_sagelocation "
        "WHERE LOWER(location_name) LIKE LOWER(?) ORDER BY location_id LIMIT 1",
        (f"%{location_name}%",)
    )
    return result


def is_postgresql():
    """Check if using PostgreSQL"""
    import os
    return bool(os.environ.get('PGHOST'))


def get_placeholder():
    """Get the correct placeholder for the database"""
    return "%s" if is_postgresql() else "?"


def parse_date_reference(date_ref: str) -> Optional[str]:
    """
    Parse date references like '11 Jan', '28 Dec', '2025-01-11'
    Returns date in YYYY-MM-DD format
    """
    date_ref = date_ref.strip()

    # Try YYYY-MM-DD format
    try:
        datetime.strptime(date_ref, '%Y-%m-%d')
        return date_ref
    except ValueError:
        pass

    # Try 'DD Mon' format (assume current or recent year)
    try:
        current_year = datetime.now().year
        parsed = datetime.strptime(f"{date_ref} {current_year}", '%d %b %Y')
        return parsed.strftime('%Y-%m-%d')
    except ValueError:
        pass

    # Try 'DD Month' format
    try:
        current_year = datetime.now().year
        parsed = datetime.strptime(f"{date_ref} {current_year}", '%d %B %Y')
        return parsed.strftime('%Y-%m-%d')
    except ValueError:
        pass

    return None


def decimal_to_float(obj):
    """Convert Decimal objects to float for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: decimal_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [decimal_to_float(item) for item in obj]
    return obj


# MCP Tools

@mcp.tool()
def list_locations() -> str:
    """
    List all valid location names in the system.
    Returns location IDs and names from the Sage Location master data.
    """
    locations = execute_query(
        "SELECT location_id, location_name FROM reconciliation_sagelocation "
        "ORDER BY location_name"
    )

    if not locations:
        return "No locations found in the database."

    result = "Available Locations:\n"
    result += "-" * 40 + "\n"
    for loc in locations:
        result += f"  {loc['location_id']}: {loc['location_name']}\n"

    return result


@mcp.tool()
def list_pay_periods(limit: int = 10) -> str:
    """
    List recent pay periods with date ranges.
    Shows periods that have employee snapshot data.

    Args:
        limit: Maximum number of periods to return (default 10)
    """
    ph = get_placeholder()

    periods = execute_query(
        f"""
        SELECT DISTINCT p.period_id, p.period_start, p.period_end, p.process_type
        FROM reconciliation_payperiod p
        INNER JOIN reconciliation_employeepayperiodsnapshot s ON s.pay_period_id = p.period_id
        WHERE p.process_type = 'actual_pay_period'
        ORDER BY p.period_end DESC
        LIMIT {ph}
        """,
        (limit,)
    )

    if not periods:
        return "No pay periods with data found."

    result = "Recent Pay Periods:\n"
    result += "-" * 60 + "\n"
    result += f"{'Period ID':<15} {'Start':<12} {'End':<12} {'Type'}\n"
    result += "-" * 60 + "\n"

    for p in periods:
        start = p['period_start'] or 'N/A'
        if hasattr(start, 'strftime'):
            start = start.strftime('%d %b %Y')
        end = p['period_end']
        if hasattr(end, 'strftime'):
            end = end.strftime('%d %b %Y')
        result += f"{p['period_id']:<15} {str(start):<12} {str(end):<12} {p['process_type']}\n"

    return result


@mcp.tool()
def compare_location_labour(
    location: str,
    period_a: str,
    period_b: str
) -> str:
    """
    Compare labour costs between two periods for a specific location.
    Shows total cost, headcount, and variance.

    Args:
        location: Location name (e.g., 'Missong', 'Marmor')
        period_a: First period (e.g., '2024-12-28' or '28 Dec')
        period_b: Second period (e.g., '2025-01-11' or '11 Jan')
    """
    # Resolve location
    loc = resolve_location(location)
    if not loc:
        return f"Location '{location}' not found. Use list_locations() to see valid locations."

    location_id = loc['location_id']
    location_name = loc['location_name']

    # Parse dates
    date_a = parse_date_reference(period_a)
    date_b = parse_date_reference(period_b)

    if not date_a:
        return f"Could not parse date '{period_a}'. Use format like '11 Jan' or '2025-01-11'."
    if not date_b:
        return f"Could not parse date '{period_b}'. Use format like '28 Dec' or '2024-12-28'."

    # Find matching pay periods
    ph = get_placeholder()
    period_a_obj = execute_single(
        f"SELECT period_id, period_end FROM reconciliation_payperiod WHERE period_id = {ph}",
        (date_a,)
    )
    period_b_obj = execute_single(
        f"SELECT period_id, period_end FROM reconciliation_payperiod WHERE period_id = {ph}",
        (date_b,)
    )

    if not period_a_obj:
        return f"No pay period found for date {date_a}. Use list_pay_periods() to see available periods."
    if not period_b_obj:
        return f"No pay period found for date {date_b}. Use list_pay_periods() to see available periods."

    # Query snapshots for both periods, filtering by location in cost_allocation
    def get_location_totals(period_id):
        """Get totals for employees allocated to this location"""
        snapshots = execute_query(
            f"""
            SELECT employee_code, employee_name, total_cost, cost_allocation
            FROM reconciliation_employeepayperiodsnapshot
            WHERE pay_period_id = {ph}
            """,
            (period_id,)
        )

        total_cost = Decimal('0')
        headcount = 0
        employees = []

        for snap in snapshots:
            allocation = snap['cost_allocation']
            if isinstance(allocation, str):
                allocation = json.loads(allocation)

            if not allocation:
                continue

            # Check if this employee has allocation to our location
            if location_id in allocation:
                loc_pct = sum(Decimal(str(pct)) for pct in allocation[location_id].values())
                allocated_cost = Decimal(str(snap['total_cost'] or 0)) * loc_pct / 100
                total_cost += allocated_cost
                headcount += 1
                employees.append({
                    'code': snap['employee_code'],
                    'name': snap['employee_name'],
                    'cost': float(allocated_cost),
                    'pct': float(loc_pct)
                })

        return {
            'total_cost': total_cost,
            'headcount': headcount,
            'employees': sorted(employees, key=lambda x: -x['cost'])[:10]  # Top 10
        }

    totals_a = get_location_totals(date_a)
    totals_b = get_location_totals(date_b)

    cost_variance = totals_b['total_cost'] - totals_a['total_cost']
    headcount_change = totals_b['headcount'] - totals_a['headcount']

    # Format results
    result = f"\nLabour Comparison for {location_name} ({location_id})\n"
    result += "=" * 60 + "\n\n"

    result += f"Period A ({date_a}):\n"
    result += f"  Total Cost:  ${totals_a['total_cost']:,.2f}\n"
    result += f"  Headcount:   {totals_a['headcount']}\n\n"

    result += f"Period B ({date_b}):\n"
    result += f"  Total Cost:  ${totals_b['total_cost']:,.2f}\n"
    result += f"  Headcount:   {totals_b['headcount']}\n\n"

    result += "Variance:\n"
    sign = '+' if cost_variance >= 0 else ''
    result += f"  Cost Change: {sign}${cost_variance:,.2f}\n"
    sign = '+' if headcount_change >= 0 else ''
    result += f"  Headcount:   {sign}{headcount_change}\n\n"

    if totals_a['total_cost'] > 0:
        pct_change = (cost_variance / totals_a['total_cost']) * 100
        sign = '+' if pct_change >= 0 else ''
        result += f"  % Change:    {sign}{pct_change:.1f}%\n"

    return result


@mcp.tool()
def get_location_headcount(
    location: str,
    period: Optional[str] = None
) -> str:
    """
    Get headcount for a location in a specific pay period.
    If no period specified, uses the most recent period.

    Args:
        location: Location name (e.g., 'Missong', 'Marmor')
        period: Pay period (e.g., '2025-01-11' or '11 Jan'). If not provided, uses latest.
    """
    # Resolve location
    loc = resolve_location(location)
    if not loc:
        return f"Location '{location}' not found. Use list_locations() to see valid locations."

    location_id = loc['location_id']
    location_name = loc['location_name']

    ph = get_placeholder()

    # Determine period
    if period:
        date_str = parse_date_reference(period)
        if not date_str:
            return f"Could not parse date '{period}'."
        period_id = date_str
    else:
        # Get most recent period
        latest = execute_single(
            f"""
            SELECT DISTINCT p.period_id, p.period_end
            FROM reconciliation_payperiod p
            INNER JOIN reconciliation_employeepayperiodsnapshot s ON s.pay_period_id = p.period_id
            WHERE p.process_type = 'actual_pay_period'
            ORDER BY p.period_end DESC
            LIMIT 1
            """
        )
        if not latest:
            return "No pay periods with data found."
        period_id = latest['period_id']

    # Get all snapshots for the period
    snapshots = execute_query(
        f"""
        SELECT employee_code, employee_name, total_cost, cost_allocation, employment_status
        FROM reconciliation_employeepayperiodsnapshot
        WHERE pay_period_id = {ph}
        """,
        (period_id,)
    )

    # Filter by location and build employee list
    employees = []
    for snap in snapshots:
        allocation = snap['cost_allocation']
        if isinstance(allocation, str):
            allocation = json.loads(allocation)

        if not allocation:
            continue

        if location_id in allocation:
            loc_pct = sum(Decimal(str(pct)) for pct in allocation[location_id].values())
            allocated_cost = Decimal(str(snap['total_cost'] or 0)) * loc_pct / 100
            employees.append({
                'code': snap['employee_code'],
                'name': snap['employee_name'],
                'cost': allocated_cost,
                'pct': loc_pct,
                'status': snap.get('employment_status', '')
            })

    # Sort by cost (highest first)
    employees.sort(key=lambda x: -x['cost'])

    # Format results
    result = f"\nHeadcount for {location_name} ({location_id})\n"
    result += f"Pay Period: {period_id}\n"
    result += "=" * 70 + "\n\n"
    result += f"Total Headcount: {len(employees)}\n"
    result += f"Total Labour Cost: ${sum(e['cost'] for e in employees):,.2f}\n\n"

    result += f"{'Code':<10} {'Name':<30} {'Allocation %':<12} {'Cost':<12}\n"
    result += "-" * 70 + "\n"

    for emp in employees:
        result += f"{emp['code']:<10} {emp['name'][:28]:<30} {emp['pct']:>8.1f}%    ${emp['cost']:>9,.2f}\n"

    return result


@mcp.tool()
def get_period_summary(period: Optional[str] = None) -> str:
    """
    Get overall payroll summary for a pay period.
    Shows total costs by GL account, location breakdown, and employee count.

    Args:
        period: Pay period (e.g., '2025-01-11' or '11 Jan'). If not provided, uses latest.
    """
    ph = get_placeholder()

    # Determine period
    if period:
        date_str = parse_date_reference(period)
        if not date_str:
            return f"Could not parse date '{period}'."
        period_id = date_str
    else:
        # Get most recent period
        latest = execute_single(
            f"""
            SELECT DISTINCT p.period_id, p.period_end, p.period_start
            FROM reconciliation_payperiod p
            INNER JOIN reconciliation_employeepayperiodsnapshot s ON s.pay_period_id = p.period_id
            WHERE p.process_type = 'actual_pay_period'
            ORDER BY p.period_end DESC
            LIMIT 1
            """
        )
        if not latest:
            return "No pay periods with data found."
        period_id = latest['period_id']

    # Get period details
    period_obj = execute_single(
        f"SELECT period_id, period_start, period_end FROM reconciliation_payperiod WHERE period_id = {ph}",
        (period_id,)
    )

    # Get all snapshots
    snapshots = execute_query(
        f"""
        SELECT
            employee_code, employee_name, total_cost, cost_allocation,
            gl_6345_salaries, gl_6370_superannuation, gl_6300, gl_6355_sick_leave,
            gl_6305, gl_6372_toil, total_hours
        FROM reconciliation_employeepayperiodsnapshot
        WHERE pay_period_id = {ph}
        """,
        (period_id,)
    )

    if not snapshots:
        return f"No data found for period {period_id}."

    # Calculate totals
    total_cost = Decimal('0')
    total_salaries = Decimal('0')
    total_super = Decimal('0')
    total_al = Decimal('0')
    total_sick = Decimal('0')
    total_hours = Decimal('0')
    location_totals = {}

    # Get location cache
    locations = execute_query("SELECT location_id, location_name FROM reconciliation_sagelocation")
    loc_cache = {l['location_id']: l['location_name'] for l in locations}

    for snap in snapshots:
        total_cost += Decimal(str(snap['total_cost'] or 0))
        total_salaries += Decimal(str(snap['gl_6345_salaries'] or 0))
        total_super += Decimal(str(snap['gl_6370_superannuation'] or 0))
        total_al += Decimal(str(snap['gl_6300'] or 0))
        total_sick += Decimal(str(snap['gl_6355_sick_leave'] or 0))
        total_hours += Decimal(str(snap['total_hours'] or 0))

        # Location breakdown
        allocation = snap['cost_allocation']
        if isinstance(allocation, str):
            allocation = json.loads(allocation)

        if allocation:
            for loc_id, depts in allocation.items():
                if loc_id not in location_totals:
                    loc_name = loc_cache.get(loc_id, loc_id)
                    location_totals[loc_id] = {
                        'name': loc_name,
                        'cost': Decimal('0'),
                        'headcount': 0
                    }

                loc_pct = sum(Decimal(str(pct)) for pct in depts.values())
                allocated = Decimal(str(snap['total_cost'] or 0)) * loc_pct / 100
                location_totals[loc_id]['cost'] += allocated
                location_totals[loc_id]['headcount'] += 1

    # Format results
    start = period_obj['period_start'] if period_obj and period_obj.get('period_start') else 'N/A'
    end = period_obj['period_end'] if period_obj else period_id
    if hasattr(start, 'strftime'):
        start = start.strftime('%d %b %Y')
    if hasattr(end, 'strftime'):
        end = end.strftime('%d %b %Y')

    result = f"\nPayroll Summary for Period: {period_id}\n"
    result += f"Date Range: {start} to {end}\n"
    result += "=" * 60 + "\n\n"

    result += "Overview:\n"
    result += f"  Total Employees:    {len(snapshots)}\n"
    result += f"  Total Cost:         ${total_cost:,.2f}\n"
    result += f"  Total Hours:        {total_hours:,.1f}\n\n"

    result += "Cost Breakdown by GL Account:\n"
    result += "-" * 40 + "\n"
    result += f"  Salaries (6345):      ${total_salaries:,.2f}\n"
    result += f"  Superannuation (6370): ${total_super:,.2f}\n"
    result += f"  Annual Leave (6300):   ${total_al:,.2f}\n"
    result += f"  Sick Leave (6355):     ${total_sick:,.2f}\n\n"

    result += "Top Locations by Cost:\n"
    result += "-" * 50 + "\n"
    sorted_locations = sorted(location_totals.items(), key=lambda x: -x[1]['cost'])[:10]
    for loc_id, data in sorted_locations:
        result += f"  {loc_id} - {data['name'][:20]:<20}: ${data['cost']:>12,.2f} ({data['headcount']} employees)\n"

    return result


# Run server
if __name__ == "__main__":
    mcp.run()
