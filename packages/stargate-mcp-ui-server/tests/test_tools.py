import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from stargate_mcp_ui_server.tools import build_html, get_ui_resource, RESOURCE_URI, LAZY_RESOURCE_URI, build_lazy_html, get_lazy_ui_resource


def test_resource_uri_is_static():
    assert RESOURCE_URI == "ui://stargate/employee-trend"


def test_build_html_contains_container_name():
    html = build_html()
    assert "employeeChartCard" in html
    assert "remoteEntry.js" in html


def test_build_html_contains_react_scripts():
    html = build_html()
    assert "react.production.min.js" in html
    assert "react-dom.production.min.js" in html


def test_get_ui_resource_structure():
    result = get_ui_resource()
    assert isinstance(result, dict)
    assert "resource" in result
    assert result["resource"]["uri"] == RESOURCE_URI
    assert len(result["resource"]["text"]) > 100


def test_build_html_does_not_contain_employee_data():
    html = build_html()
    assert "7000" not in html
    assert "2019" not in html



def test_lazy_resource_uri_is_static():
    assert LAZY_RESOURCE_URI == "ui://stargate/employee-trend-lazy"


def test_build_lazy_html_contains_lazy_component():
    html = build_lazy_html()
    assert "EmployeeChartLazy" in html
    assert "employeeChartCard" in html


def test_build_lazy_html_does_not_contain_employee_data():
    html = build_lazy_html()
    assert "7000" not in html
    assert "2019" not in html


def test_get_lazy_ui_resource_structure():
    result = get_lazy_ui_resource()
    assert isinstance(result, dict)
    assert "resource" in result
    assert result["resource"]["uri"] == LAZY_RESOURCE_URI
    assert len(result["resource"]["text"]) > 100
