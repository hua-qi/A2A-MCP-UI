REMOTE_ENTRY_URL = "http://localhost:3004/remoteEntry.js"
COMPONENT_NAME = "EmployeeChart"
CONTAINER_NAME = "employeeChartCard"

MCP_INIT_SCRIPT = """
(function() {
  window.addEventListener('message', function(e) {
    var msg = e.data;
    if (msg && msg.method === 'ui/notifications/sandbox-resource-ready') {
      window.parent.postMessage({
        jsonrpc: '2.0',
        method: 'ui/notifications/initialized',
        params: {}
      }, '*');
    }
  });
})();
"""


def build_employee_trend_shell(component_name: str = COMPONENT_NAME) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
</head>
<body style="margin:0">
<div id="root"></div>
<script src="{REMOTE_ENTRY_URL}"></script>
<script>
{MCP_INIT_SCRIPT}
(function() {{
  Promise.resolve().then(function() {{
    if (typeof {CONTAINER_NAME} === 'undefined') throw new Error('Container {CONTAINER_NAME} not found');
    var shareScope = Object.create(null);
    shareScope['default'] = {{}};
    shareScope['default']['react'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return React; }}; }}, loaded: 1, from: 'host' }}
    }};
    shareScope['default']['react-dom'] = {{
      '18.3.1': {{ get: function() {{ return function() {{ return ReactDOM; }}; }}, loaded: 1, from: 'host' }}
    }};
    if ({CONTAINER_NAME}.init) {{
      try {{ {CONTAINER_NAME}.init(shareScope['default']); }} catch(e) {{}}
    }}
    return {CONTAINER_NAME}.get('./{component_name}');
  }}).then(function(factory) {{
    var Comp = factory().default;
    ReactDOM.createRoot(document.getElementById('root'))
      .render(React.createElement(Comp, {{}}));
  }}).catch(function(e) {{
    document.body.innerHTML = '<p style="color:red;padding:16px">加载失败: ' + e.message + '</p>';
  }});
}})();
</script>
</body></html>"""
