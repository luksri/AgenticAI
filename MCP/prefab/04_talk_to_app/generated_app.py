from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Badge, Button, Card, CardContent, CardHeader, CardTitle,
    Checkbox, Column, H1, H2, H3, Muted, Progress, Ring, Row,
    Tab, Tabs, Text, Calendar
)
from prefab_ui.components.charts import (
    BarChart, ChartSeries, LineChart, PieChart, Sparkline, RadarChart,
)

with PrefabApp(css_class="max-w-5xl mx-auto p-6") as app:
    with Card():
        with CardHeader():
            CardTitle('Skills Assessment Overview')
        with CardContent():
            with Tabs(value='technical_profile'):
                with Tab('Technical Profile', value='technical_profile'):
                    with Column(gap=5):
                        with Column(gap=1):
                            Muted('Total Skill Score')
                            H1('415')
                            Muted('Out of 500 potential')
                        with Column(gap=2):
                            H3('Technical Proficiency')
                            RadarChart(data=[{'axis': 'Python', 'value': 90}, {'axis': 'JS', 'value': 75}, {'axis': 'SQL', 'value': 85}, {'axis': 'DevOps', 'value': 80}, {'axis': 'AI', 'value': 85}],
                                       series=[ChartSeries(data_key='value', label='value')],
                                       axis_key='axis', show_legend=False)
                        H3('Development Areas')
                        with Column(gap=3):
                            with Column(gap=1):
                                Text('Python')
                                Progress(value=90)
                            with Column(gap=1):
                                Text('AI/ML')
                                Progress(value=85)
                            with Column(gap=1):
                                Text('SQL')
                                Progress(value=85)
                            with Column(gap=1):
                                Text('DevOps')
                                Progress(value=80)
                            with Column(gap=1):
                                Text('JavaScript')
                                Progress(value=75)
