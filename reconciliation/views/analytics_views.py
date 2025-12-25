"""
Analytics Dashboard Views
Handles AI-powered analytics queries using Claude API
"""
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.conf import settings
import json
import os

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from reconciliation.analytics_tools import ANALYTICS_TOOLS, TOOL_FUNCTIONS


def analytics_dashboard(request):
    """
    Render the analytics dashboard interface
    """
    return render(request, 'reconciliation/analytics_dashboard.html')


@require_http_methods(["POST"])
def analytics_query(request):
    """
    Process analytics queries using Claude API with Tool Use
    """
    if not ANTHROPIC_AVAILABLE:
        return JsonResponse({
            'success': False,
            'error': 'Anthropic package not installed. Run: pip install anthropic'
        })

    try:
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
        conversation_history = data.get('conversation_history', [])

        if not user_message:
            return JsonResponse({
                'success': False,
                'error': 'No message provided'
            })

        # Get API key from environment or settings
        api_key = os.getenv('ANTHROPIC_API_KEY') or getattr(settings, 'ANTHROPIC_API_KEY', None)

        if not api_key:
            return JsonResponse({
                'success': False,
                'error': 'ANTHROPIC_API_KEY not configured. Please set it in your environment or settings.py'
            })

        # Initialize Anthropic client
        client = anthropic.Anthropic(api_key=api_key)

        # Build messages for API
        messages = conversation_history + [
            {"role": "user", "content": user_message}
        ]

        # System prompt
        system_prompt = """You are an AI assistant specialized in payroll analytics. You have access to tools that can query the payroll database to answer questions about employees, costs, variances, and trends.

When answering questions:
1. Use the available tools to fetch accurate data from the database
2. Provide clear, concise answers with specific numbers and percentages
3. Suggest relevant visualizations (charts, tables, metrics) when appropriate
4. If a question requires multiple tools, call them in sequence
5. Always format currency values with $ and 2 decimal places
6. Always format percentages with % symbol

Available data includes:
- Employee information (demographics, employment types, locations)
- Pay period data (costs, hours, employee counts)
- Reconciliation data (variances, match rates)
- Time-based trends (month-over-month, period comparisons)"""

        # Call Claude API with tools
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=ANALYTICS_TOOLS
        )

        # Process response and handle tool calls
        final_response = ""
        visualization_data = None
        tool_results = []

        while response.stop_reason == "tool_use":
            # Extract tool calls
            for content_block in response.content:
                if content_block.type == "tool_use":
                    tool_name = content_block.name
                    tool_input = content_block.input
                    tool_use_id = content_block.id

                    # Execute the tool
                    if tool_name in TOOL_FUNCTIONS:
                        try:
                            result = TOOL_FUNCTIONS[tool_name](**tool_input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps(result)
                            })

                            # Generate visualization if appropriate
                            if not visualization_data:
                                visualization_data = generate_visualization(tool_name, result, user_message)

                        except Exception as e:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": json.dumps({"error": str(e)})
                            })

            # Continue conversation with tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=ANALYTICS_TOOLS
            )

            tool_results = []

        # Extract final text response
        for content_block in response.content:
            if hasattr(content_block, 'text'):
                final_response += content_block.text

        # Update conversation history
        updated_history = messages + [{"role": "assistant", "content": final_response}]

        # Return response
        return JsonResponse({
            'success': True,
            'response': final_response,
            'visualization': visualization_data,
            'conversation_history': updated_history[-10:]  # Keep last 10 messages
        })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


def generate_visualization(tool_name, result, user_query):
    """
    Generate visualization data based on tool results

    Args:
        tool_name (str): Name of the tool that was called
        result (dict/list): Result from the tool
        user_query (str): Original user query

    Returns:
        dict: Visualization specification for frontend
    """
    if isinstance(result, dict) and 'error' in result:
        return None

    # Employee statistics - pie chart or bar chart
    if tool_name == "get_employee_statistics":
        if isinstance(result, list):
            # Grouped data - bar chart
            categories = [item.get('location') or item.get('employment_type') or str(item) for item in result]
            totals = [item.get('total', 0) for item in result]
            salaried = [item.get('salaried', 0) for item in result]
            hourly = [item.get('hourly', 0) for item in result]

            return {
                'type': 'chart',
                'title': 'Employee Distribution',
                'data': [
                    {'x': categories, 'y': salaried, 'type': 'bar', 'name': 'Salaried'},
                    {'x': categories, 'y': hourly, 'type': 'bar', 'name': 'Hourly'}
                ],
                'layout': {
                    'barmode': 'stack',
                    'xaxis': {'title': 'Category'},
                    'yaxis': {'title': 'Count'}
                }
            }
        else:
            # Overall stats - metrics
            return {
                'type': 'metrics',
                'title': 'Employee Statistics',
                'metrics': [
                    {'label': 'Total Employees', 'value': result.get('total', 0)},
                    {'label': 'Salaried', 'value': result.get('salaried', 0)},
                    {'label': 'Hourly', 'value': result.get('hourly', 0)},
                    {'label': 'Salaried %', 'value': f"{result.get('salaried_pct', 0)}%"}
                ]
            }

    # Pay period comparison - waterfall/bridge chart
    elif tool_name == "compare_pay_periods":
        return {
            'type': 'chart',
            'title': f"Pay Period Comparison: {result.get('period_1')} vs {result.get('period_2')}",
            'data': [{
                'type': 'waterfall',
                'orientation': 'v',
                'x': ['Period 1', 'Variance', 'Period 2'],
                'y': [result.get('period_1_total', 0), result.get('variance', 0), result.get('period_2_total', 0)],
                'text': [
                    f"${result.get('period_1_total', 0):,.2f}",
                    f"${result.get('variance', 0):,.2f}",
                    f"${result.get('period_2_total', 0):,.2f}"
                ],
                'textposition': 'outside',
                'connector': {'line': {'color': 'rgb(63, 63, 63)'}}
            }],
            'layout': {
                'yaxis': {'title': 'Cost ($)'},
                'showlegend': False
            }
        }

    # Month over month - line chart
    elif tool_name == "get_month_over_month":
        if isinstance(result, list) and len(result) > 0:
            periods = [item['period'] for item in result]
            values = [item['value'] for item in result]

            return {
                'type': 'chart',
                'title': 'Month-over-Month Trend',
                'data': [{
                    'x': periods,
                    'y': values,
                    'type': 'scatter',
                    'mode': 'lines+markers',
                    'name': 'Cost',
                    'line': {'color': '#667eea', 'width': 3}
                }],
                'layout': {
                    'xaxis': {'title': 'Period'},
                    'yaxis': {'title': 'Value'}
                }
            }

    # Headcount by location - horizontal bar chart
    elif tool_name == "get_headcount_by_location":
        if isinstance(result, list) and len(result) > 0:
            locations = [item['location'] for item in result]
            totals = [item['total'] for item in result]

            return {
                'type': 'chart',
                'title': 'Headcount by Location',
                'data': [{
                    'y': locations,
                    'x': totals,
                    'type': 'bar',
                    'orientation': 'h',
                    'marker': {'color': '#667eea'}
                }],
                'layout': {
                    'xaxis': {'title': 'Employee Count'},
                    'yaxis': {'title': 'Location'},
                    'height': max(400, len(locations) * 30)
                }
            }

    # Cost breakdown - pie chart
    elif tool_name == "get_cost_breakdown":
        if isinstance(result, list) and len(result) > 0:
            dimension_key = list(result[0].keys())[0] if result[0] else 'category'
            labels = [item.get(dimension_key, 'Unknown') for item in result]
            values = [item.get('total_cost', 0) for item in result]

            return {
                'type': 'chart',
                'title': 'Cost Breakdown',
                'data': [{
                    'labels': labels,
                    'values': values,
                    'type': 'pie',
                    'textinfo': 'label+percent',
                    'textposition': 'outside'
                }],
                'layout': {
                    'height': 500
                }
            }

    # Default: show as table
    if isinstance(result, list) and len(result) > 0:
        columns = list(result[0].keys())
        rows = [[str(item.get(col, '')) for col in columns] for item in result]

        return {
            'type': 'table',
            'title': 'Query Results',
            'columns': columns,
            'rows': rows
        }

    return None
