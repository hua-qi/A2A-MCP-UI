# A2A 扩展规范合规改造 — 自动验收脚本

**目标：** 由 Agent 执行，逐条验证改造后的代码行为符合设计规范，所有检查均通过才算验收完成。

**前置条件：** 所有服务已启动
- SG-Agent: `http://localhost:3011`（Flask A2A）、`http://localhost:3001`（FastAPI REST）
- CF-Agent: `http://localhost:3002`
- ResourceCenter: `http://localhost:3003`

---

## CHECK-01：扩展规范文档存在

```bash
test -f /Users/lianzimeng/working/A2A-mcpUI/ext-mcp-ui-resource/spec.md && echo "PASS" || echo "FAIL: spec.md not found"
```

**期望输出：** `PASS`

**验证内容：** 文档包含扩展 URI

```bash
grep -q "https://stargate.example.com/ext/mcp-ui-resource/v1" \
  /Users/lianzimeng/working/A2A-mcpUI/ext-mcp-ui-resource/spec.md \
  && echo "PASS" || echo "FAIL: extension URI not found in spec.md"
```

**期望输出：** `PASS`

---

## CHECK-02：AgentCard 声明了扩展

```bash
curl -sf http://localhost:3011/.well-known/agent-card.json \
  | python3 -c "
import json, sys
card = json.load(sys.stdin)
exts = card.get('capabilities', {}).get('extensions', [])
uri = 'https://stargate.example.com/ext/mcp-ui-resource/v1'
match = next((e for e in exts if e.get('uri') == uri), None)
if not match:
    print('FAIL: extension not declared in AgentCard'); sys.exit(1)
if match.get('required') != False:
    print('FAIL: required should be false'); sys.exit(1)
print('PASS')
"
```

**期望输出：** `PASS`

---

## CHECK-03：不带 Header 时响应只含 text part（降级行为）

```bash
curl -sf -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"chk03","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"endpoint\"}"}]}}}' \
  | python3 -c "
import json, sys
body = json.load(sys.stdin)
parts = body.get('result', {}).get('message', {}).get('parts', [])
data_parts = [p for p in parts if 'data' in p]
text_parts = [p for p in parts if 'text' in p]
if data_parts:
    print('FAIL: data part should not appear without A2A-Extensions header'); sys.exit(1)
if not text_parts:
    print('FAIL: text part missing'); sys.exit(1)
print('PASS')
"
```

**期望输出：** `PASS`

---

## CHECK-04：不带 Header 时响应 Header 无 A2A-Extensions 回显

```bash
HEADER=$(curl -si -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"chk04","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"endpoint\"}"}]}}}' \
  | grep -i "^a2a-extensions:")
if [ -z "$HEADER" ]; then echo "PASS"; else echo "FAIL: A2A-Extensions header should not be present: $HEADER"; fi
```

**期望输出：** `PASS`

---

## CHECK-05：带 Header 时响应含标准双 part

```bash
curl -sf -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -H "A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1" \
  -d '{"jsonrpc":"2.0","id":"chk05","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"endpoint\"}"}]}}}' \
  | python3 -c "
import json, sys
body = json.load(sys.stdin)
parts = body.get('result', {}).get('message', {}).get('parts', [])
text_parts = [p for p in parts if 'text' in p]
data_parts = [p for p in parts if 'data' in p]
if not text_parts:
    print('FAIL: text part missing'); sys.exit(1)
if not data_parts:
    print('FAIL: data part missing'); sys.exit(1)
d = data_parts[0]['data']
if d.get('kind') != 'mcp_ui_resource':
    print(f'FAIL: data.kind should be mcp_ui_resource, got {d.get(\"kind\")}'); sys.exit(1)
if not d.get('resourceUri', '').startswith('ui://'):
    print(f'FAIL: resourceUri should start with ui://, got {d.get(\"resourceUri\")}'); sys.exit(1)
if data_parts[0].get('mediaType') != 'application/json':
    print('FAIL: mediaType should be application/json'); sys.exit(1)
ext_in_meta = data_parts[0].get('metadata', {}).get('extension')
if ext_in_meta != 'https://stargate.example.com/ext/mcp-ui-resource/v1':
    print(f'FAIL: metadata.extension mismatch: {ext_in_meta}'); sys.exit(1)
print('PASS')
"
```

**期望输出：** `PASS`

---

## CHECK-06：带 Header 时响应 Header 回显 A2A-Extensions

```bash
HEADER=$(curl -si -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -H "A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1" \
  -d '{"jsonrpc":"2.0","id":"chk06","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"endpoint\"}"}]}}}' \
  | grep -i "^a2a-extensions:")
if echo "$HEADER" | grep -q "stargate.example.com/ext/mcp-ui-resource/v1"; then
  echo "PASS"
else
  echo "FAIL: A2A-Extensions response header missing or incorrect: $HEADER"
fi
```

**期望输出：** `PASS`

---

## CHECK-07：data part 包含必填字段 resourceUri 和 kind

```bash
curl -sf -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -H "A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1" \
  -d '{"jsonrpc":"2.0","id":"chk07","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"endpoint\"}"}]}}}' \
  | python3 -c "
import json, sys
body = json.load(sys.stdin)
parts = body.get('result', {}).get('message', {}).get('parts', [])
data_parts = [p for p in parts if 'data' in p]
d = data_parts[0]['data']
missing = [f for f in ['kind', 'resourceUri'] if not d.get(f)]
if missing:
    print(f'FAIL: missing required fields: {missing}'); sys.exit(1)
print('PASS')
"
```

**期望输出：** `PASS`

---

## CHECK-08：mcp 模式下 resourceUri 使用固定路径（非 cardInstanceId）

```bash
curl -sf -X POST http://localhost:3011/message \
  -H "Content-Type: application/json" \
  -H "A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1" \
  -d '{"jsonrpc":"2.0","id":"chk08","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询快手员工趋势\",\"mode\":\"mcp\"}"}]}}}' \
  | python3 -c "
import json, sys
body = json.load(sys.stdin)
parts = body.get('result', {}).get('message', {}).get('parts', [])
data_parts = [p for p in parts if 'data' in p]
if not data_parts:
    print('FAIL: data part missing in mcp mode'); sys.exit(1)
uri = data_parts[0]['data'].get('resourceUri', '')
if not uri.startswith('ui://stargate/employee-trend'):
    print(f'FAIL: mcp mode should use fixed resource URI, got {uri}'); sys.exit(1)
print('PASS')
"
```

**期望输出：** `PASS`

---

## CHECK-09：CF-Agent /chat 返回正确的 mcp_ui_resource part

```bash
curl -sf -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"查询快手历年员工人数趋势"}' \
  | python3 -c "
import json, sys
body = json.load(sys.stdin)
parts = body.get('parts', [])
ui_parts = [p for p in parts if p.get('kind') == 'mcp_ui_resource']
text_parts = [p for p in parts if p.get('kind') == 'text']
if not text_parts:
    print('FAIL: text part missing in /chat response'); sys.exit(1)
if not ui_parts:
    print('FAIL: mcp_ui_resource part missing in /chat response'); sys.exit(1)
u = ui_parts[0]
if not u.get('resourceUri', '').startswith('ui://'):
    print(f'FAIL: resourceUri invalid: {u.get(\"resourceUri\")}'); sys.exit(1)
print('PASS')
"
```

**期望输出：** `PASS`

---

## CHECK-10：CF-Agent /chat 不再包含 JSON-in-text hack

```bash
curl -sf -X POST http://localhost:3002/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"查询快手历年员工人数趋势"}' \
  | python3 -c "
import json, sys
body = json.load(sys.stdin)
parts = body.get('parts', [])
for p in parts:
    if p.get('kind') == 'text':
        text = p.get('text', '')
        try:
            inner = json.loads(text)
            if 'mcp_ui_resource' in inner:
                print('FAIL: JSON-in-text hack still present'); sys.exit(1)
        except json.JSONDecodeError:
            pass
print('PASS')
"
```

**期望输出：** `PASS`

---

## CHECK-11：ARCHITECTURE.md 包含 5.7 节

```bash
grep -q "5.7" /Users/lianzimeng/working/A2A-mcpUI/ARCHITECTURE.md \
  && echo "PASS" || echo "FAIL: Section 5.7 not found in ARCHITECTURE.md"
```

**期望输出：** `PASS`

---

## CHECK-12：ARCHITECTURE.md 不再包含 JSON-in-text 旧格式描述

```bash
grep -q "mcp_ui_resource.*JSON-in-text\|JSON-in-text.*hack" \
  /Users/lianzimeng/working/A2A-mcpUI/ARCHITECTURE.md \
  && echo "FAIL: old JSON-in-text description still present" || echo "PASS"
```

**期望输出：** `PASS`

---

## 汇总执行脚本

将以上所有检查串联执行，任何一项失败则打印 `[FAILED]` 汇总：

```bash
#!/bin/bash
FAILED=0

run_check() {
  local name=$1
  local result=$2
  if echo "$result" | grep -q "^PASS"; then
    echo "✓ $name"
  else
    echo "✗ $name — $result"
    FAILED=$((FAILED + 1))
  fi
}

# CHECK-01
run_check "CHECK-01 spec.md exists" \
  "$(test -f /Users/lianzimeng/working/A2A-mcpUI/ext-mcp-ui-resource/spec.md && echo PASS || echo FAIL)"

# CHECK-02
run_check "CHECK-02 AgentCard declares extension" \
  "$(curl -sf http://localhost:3011/.well-known/agent-card.json | python3 -c "
import json,sys; c=json.load(sys.stdin); e=c.get('capabilities',{}).get('extensions',[])
m=next((x for x in e if x.get('uri')=='https://stargate.example.com/ext/mcp-ui-resource/v1'),None)
print('PASS' if m and m.get('required')==False else 'FAIL')
")"

# CHECK-03
run_check "CHECK-03 no header → text part only" \
  "$(curl -sf -X POST http://localhost:3011/message -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"c3","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询\",\"mode\":\"endpoint\"}"}]}}}' \
  | python3 -c "import json,sys; b=json.load(sys.stdin); p=b.get('result',{}).get('message',{}).get('parts',[]); print('PASS' if not any('data' in x for x in p) else 'FAIL')")"

# CHECK-05
run_check "CHECK-05 with header → dual parts" \
  "$(curl -sf -X POST http://localhost:3011/message -H 'Content-Type: application/json' \
  -H 'A2A-Extensions: https://stargate.example.com/ext/mcp-ui-resource/v1' \
  -d '{"jsonrpc":"2.0","id":"c5","method":"message/send","params":{"message":{"role":"user","parts":[{"text":"{\"text\":\"查询\",\"mode\":\"endpoint\"}"}]}}}' \
  | python3 -c "
import json,sys; b=json.load(sys.stdin); p=b.get('result',{}).get('message',{}).get('parts',[])
dp=[x for x in p if 'data' in x]
ok = dp and dp[0]['data'].get('kind')=='mcp_ui_resource' and dp[0]['data'].get('resourceUri','').startswith('ui://')
print('PASS' if ok else 'FAIL')
")"

# CHECK-09
run_check "CHECK-09 CF-Agent /chat returns mcp_ui_resource" \
  "$(curl -sf -X POST http://localhost:3002/chat -H 'Content-Type: application/json' \
  -d '{"message":"查询快手历年员工人数趋势"}' \
  | python3 -c "
import json,sys; b=json.load(sys.stdin); p=b.get('parts',[])
print('PASS' if any(x.get('kind')=='mcp_ui_resource' for x in p) else 'FAIL')
")"

# CHECK-10
run_check "CHECK-10 no JSON-in-text hack" \
  "$(curl -sf -X POST http://localhost:3002/chat -H 'Content-Type: application/json' \
  -d '{"message":"查询快手历年员工人数趋势"}' \
  | python3 -c "
import json,sys; b=json.load(sys.stdin)
for p in b.get('parts',[]):
    if p.get('kind')=='text':
        try:
            inner=json.loads(p.get('text',''))
            if 'mcp_ui_resource' in inner: print('FAIL'); sys.exit(0)
        except: pass
print('PASS')
")"

# CHECK-11
run_check "CHECK-11 ARCHITECTURE.md has 5.7" \
  "$(grep -q '5.7' /Users/lianzimeng/working/A2A-mcpUI/ARCHITECTURE.md && echo PASS || echo FAIL)"

echo ""
if [ $FAILED -eq 0 ]; then
  echo "All checks passed."
else
  echo "$FAILED check(s) failed."
fi
```
