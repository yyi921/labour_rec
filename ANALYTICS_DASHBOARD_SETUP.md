# Analytics Dashboard Setup Guide

## Overview

The Analytics Dashboard provides AI-powered natural language querying of your payroll database using Claude API. It features:

- 💬 **Natural language queries** - Ask questions in plain English
- 📊 **Automatic visualizations** - Charts, graphs, and tables generated based on your queries
- 🔧 **Extensible tools** - Easy to add new analytics capabilities
- 📈 **Advanced analytics** - Month-over-month, budget comparisons, variance analysis

## Setup Instructions

### 1. Install Required Package

```bash
pip install anthropic
```

### 2. Get Anthropic API Key

1. Sign up for an Anthropic account at https://console.anthropic.com/
2. Navigate to API Keys section
3. Create a new API key
4. Copy the key (starts with `sk-ant-`)

### 3. Configure API Key

**Option A: Environment Variable (Recommended)**

Add to your environment:

**Windows:**
```cmd
setx ANTHROPIC_API_KEY "your-api-key-here"
```

**Mac/Linux:**
```bash
export ANTHROPIC_API_KEY="your-api-key-here"
```

Or add to your `.env` file:
```
ANTHROPIC_API_KEY=your-api-key-here
```

**Option B: Django Settings**

Add to `config/settings.py`:
```python
ANTHROPIC_API_KEY = 'your-api-key-here'
```

### 4. Restart Server

```bash
python manage.py runserver
```

### 5. Access Dashboard

Navigate to: **http://127.0.0.1:8000/analytics/**

## How to Use

### Example Questions

**Employee Statistics:**
- "What percentage of culinary employees are salaried?"
- "Show me headcount by location"
- "How many active employees do we have?"

**Pay Period Analysis:**
- "Compare pay period 2025-11-30 to 2025-11-16"
- "Show me a summary of pay period 2025-11-30"
- "What was the total cost for last period?"

**Trends & Comparisons:**
- "Show month-over-month cost trends"
- "Compare actual vs budget for November 2025"
- "What's the trend in employee headcount?"

**Reconciliation:**
- "Show reconciliation status for period 2025-11-30"
- "How many employees had variances last period?"

### Understanding Results

The dashboard displays results in multiple formats:

1. **Metrics Cards** - Key numbers and percentages
2. **Charts** - Bar charts, line charts, waterfall charts, pie charts
3. **Tables** - Detailed data breakdowns

### Adding New Tools

To add new analytics capabilities:

1. **Add function to `reconciliation/analytics_tools.py`:**
```python
def your_new_function(param1, param2):
    # Your query logic
    return results
```

2. **Add tool definition to `ANALYTICS_TOOLS` list:**
```python
{
    "name": "your_new_function",
    "description": "What this tool does...",
    "input_schema": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
            "param2": {"type": "number", "description": "..."}
        },
        "required": ["param1"]
    }
}
```

3. **Add to `TOOL_FUNCTIONS` mapping:**
```python
TOOL_FUNCTIONS = {
    # ... existing tools
    "your_new_function": your_new_function
}
```

That's it! Claude will automatically know how to use the new tool.

## Current Available Tools

1. **get_employee_statistics** - Employee counts, demographics, percentages
2. **get_payroll_summary** - Payroll totals for a period
3. **compare_pay_periods** - Period-over-period variance analysis
4. **get_cost_breakdown** - Costs by dimension (location, type, etc.)
5. **get_month_over_month** - Monthly trends
6. **get_month_over_budget** - Actual vs budget comparison
7. **get_headcount_by_location** - Headcount breakdown by location
8. **get_reconciliation_status** - Reconciliation match rates and variances

## Architecture

```
User Question (Natural Language)
    ↓
Claude API (Tool Use)
    ↓
Selects appropriate tool(s)
    ↓
Django Backend executes query
    ↓
Returns structured data
    ↓
Claude formats response
    ↓
Frontend renders visualization
```

## Troubleshooting

**Error: "Anthropic package not installed"**
- Run: `pip install anthropic`

**Error: "ANTHROPIC_API_KEY not configured"**
- Set the API key using one of the methods in step 3 above
- Restart your Django server after setting the key

**Error: "No data found"**
- Ensure you have data in your database for the requested period
- Check that pay period IDs are in YYYY-MM-DD format

**Charts not rendering**
- Ensure Plotly CDN is loading (check browser console)
- Check that visualization data is being returned in response

## Cost Considerations

- Claude API is billed per token
- Each query costs approximately $0.01-0.05 depending on complexity
- Tool calls add minimal cost
- Consider implementing caching for frequently asked questions

## Security Notes

- Never commit API keys to version control
- Use environment variables for production
- Implement rate limiting if exposed publicly
- Validate all user inputs (already handled by Django)

## Support

For issues or questions:
1. Check the browser console for errors
2. Check Django logs for backend errors
3. Verify API key is valid and has credits
4. Ensure database has the required data

---

**Happy Analyzing! 📊**
