# Generic table-driven CAN device (CAN.ScriptedCanNode). Configured from YAML, JSON or a DBC subset; no third-party
# imports (a built-in YAML subset parser reads the files; PyYAML's OFF/ON/yes/no booleans would break state names). Format: peers/README.md.
#
# Attach through a two-line shim next to the fixture (the engine runs the file as source, so config is a global):
#     CONFIG_FILE = "peers/can/configs/inverter_4x.yaml"
#     exec(compile(open("peers/can/table_node.py").read(), "peers/can/table_node.py", "exec"))
import ast
import json
import math
import os
import re


def _scalar(s):
    s = s.strip()
    if s == "":
        return None
    if s[0] in "\"'" and s[-1] == s[0] and len(s) >= 2:
        return s[1:-1]
    low = s.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "~"):
        return None
    try:
        return int(s, 0)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _split_top(s):
    out, depth, quote, cur = [], 0, None, ""
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "[{":
            depth += 1
            cur += ch
        elif ch in "]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _split_key(s):
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(s) or s[i + 1] == " "):
            return s[:i].strip(), s[i + 1:].strip()
    return None, s


def _value(s):
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        d = {}
        for part in _split_top(s[1:-1]):
            k, v = _split_key(part)
            d[_scalar(k)] = _value(v)
        return d
    if s.startswith("[") and s.endswith("]"):
        return [_value(p) for p in _split_top(s[1:-1])]
    return _scalar(s)


def _strip_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def parse_yaml_subset(text):
    """Block maps, block lists, one-line {..} / [..], scalars, comments. Anchors, multi-line scalars and tags are not supported."""
    lines = []
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if line.strip():
            lines.append((len(line) - len(line.lstrip()), line.strip()))
    pos = [0]

    def block(indent):
        if lines[pos[0]][1].startswith("- ") or lines[pos[0]][1] == "-":
            return seq(indent)
        return mapping(indent)

    def mapping(indent):
        d = {}
        while pos[0] < len(lines) and lines[pos[0]][0] == indent and not lines[pos[0]][1].startswith("- "):
            k, v = _split_key(lines[pos[0]][1])
            if k is None:
                raise ValueError("bad line: " + lines[pos[0]][1])
            pos[0] += 1
            if v == "":
                if pos[0] < len(lines) and (lines[pos[0]][0] > indent or
                                            (lines[pos[0]][0] == indent and lines[pos[0]][1].startswith("- "))):
                    d[_scalar(k)] = block(lines[pos[0]][0])
                else:
                    d[_scalar(k)] = None
            else:
                d[_scalar(k)] = _value(v)
        return d

    def seq(indent):
        out = []
        while pos[0] < len(lines) and lines[pos[0]][0] == indent and lines[pos[0]][1].startswith("-"):
            rest = lines[pos[0]][1][1:].strip()
            if rest == "":
                pos[0] += 1
                out.append(block(lines[pos[0]][0]))
                continue
            k, v = _split_key(rest)
            if k is not None and not rest.startswith(("{", "[")):
                # "- key: v" opens a map whose later keys sit at indent + 2
                lines[pos[0]] = (indent + 2, rest)
                out.append(mapping(indent + 2))
            else:
                pos[0] += 1
                out.append(_value(rest))
        return out

    return block(lines[0][0]) if lines else {}


def load_config(path):
    text = open(path).read()
    if path.endswith(".json"):
        return json.loads(text)
    return parse_yaml_subset(text)


def parse_dbc(text):
    """BO_ / SG_ / GenMsgCycleTime of a DBC. Returns {name: message dict with 'sender'} using the config message format."""
    msgs, cur, by_id = {}, None, {}
    for line in text.splitlines():
        m = re.match(r"\s*BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)", line)
        if m:
            raw = int(m.group(1))
            ext = bool(raw & 0x80000000)
            cur = {"name": m.group(2), "id": raw & 0x1FFFFFFF, "extended": ext, "dlc": int(m.group(3)),
                   "sender": m.group(4), "signals": []}
            msgs[cur["name"]] = cur
            by_id[raw] = cur
            continue
        m = re.match(r"\s*SG_\s+(\w+)\s*(?:m\d*M?\s*)?:\s*(\d+)\|(\d+)@([01])([+-])\s*\(([^,]+),([^)]+)\)", line)
        if m and cur:
            cur["signals"].append({"name": m.group(1), "start": int(m.group(2)), "length": int(m.group(3)),
                                   "order": "little" if m.group(4) == "1" else "big", "signed": m.group(5) == "-",
                                   "scale": float(m.group(6)), "offset": float(m.group(7))})
            continue
        m = re.match(r'\s*BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+)\s*;', line)
        if m and int(m.group(1)) in by_id:
            by_id[int(m.group(1))]["period_ms"] = int(m.group(2))
    return msgs


def _bit_positions(sig):
    """Bit indices (byte*8 + bit) from signal LSB to MSB; DBC numbering for both byte orders."""
    start, n = sig["start"], sig["length"]
    if sig.get("order", sig.get("endian", "little")) == "little":
        return [start + i for i in range(n)]
    pos, b = [], start
    for _ in range(n):
        pos.append(b)
        b = b + 15 if b % 8 == 0 else b - 1
    return list(reversed(pos))


def pack_signal(buf, sig, phys):
    n = sig["length"]
    raw = int(round((phys - sig.get("offset", 0)) / sig.get("scale", 1)))
    if sig.get("signed"):
        raw = max(-(1 << (n - 1)), min((1 << (n - 1)) - 1, raw))
    else:
        raw = max(0, min((1 << n) - 1, raw))
    raw &= (1 << n) - 1
    for i, p in enumerate(_bit_positions(sig)):
        if p // 8 >= len(buf):
            continue
        if (raw >> i) & 1:
            buf[p // 8] |= 1 << (p % 8)
        else:
            buf[p // 8] &= ~(1 << (p % 8))


def unpack_signal(data, sig):
    n, raw = sig["length"], 0
    for i, p in enumerate(_bit_positions(sig)):
        if p // 8 < len(data) and (data[p // 8] >> (p % 8)) & 1:
            raw |= 1 << i
    if sig.get("signed") and raw >> (n - 1):
        raw -= 1 << n
    return raw * sig.get("scale", 1) + sig.get("offset", 0)


_FUNCS = {"min": min, "max": max, "abs": abs, "round": round}


def compile_expr(src):
    tree = ast.parse(str(src), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Expression, ast.Name, ast.Load, ast.Constant, ast.BinOp, ast.UnaryOp, ast.BoolOp,
                                 ast.Compare, ast.IfExp, ast.Call, ast.operator, ast.unaryop, ast.boolop, ast.cmpop)):
            raise ValueError("expression element not allowed in %r: %s" % (src, type(node).__name__))
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in _FUNCS):
            raise ValueError("only min/max/abs/round may be called in %r" % src)
    return compile(tree, "<expr>", "eval")


def eval_expr(code, env):
    return eval(code, {"__builtins__": {}}, dict(_FUNCS, **env))


class _Msg:
    def __init__(self, spec, id_offset):
        self.name = spec["name"]
        self.id = int(spec["id"]) + (0 if spec.get("shared") else id_offset)
        self.ext = bool(spec.get("extended", self.id > 0x7FF))
        self.fd = bool(spec.get("fd", False))
        self.brs = bool(spec.get("brs", self.fd))
        self.dlc = int(spec.get("dlc", 8))
        self.dir = spec.get("dir", "tx")
        self.period = spec.get("period_ms")
        self.on_rx = spec.get("on_rx")
        self.enabled_in = spec.get("enabled_in")
        self.signals = []
        for s in spec.get("signals", []):
            s = dict(s)
            src = s.get("expr", s.get("var", s["name"]) if "value" not in s else s["value"])
            s["_code"] = compile_expr(src)
            s.setdefault("var", s["name"])
            self.signals.append(s)
        self.next_due = None


class _Device:
    def __init__(self, name, cfg, inst, base_dir):
        self.name = name
        off = int(inst.get("id_offset", 0))
        self.vars = dict(cfg.get("vars", {}))
        self.vars.update(inst.get("vars", {}))
        specs = {}
        if cfg.get("dbc"):
            d = cfg["dbc"]
            path = d["file"] if os.path.isabs(d["file"]) or os.path.exists(d["file"]) else os.path.join(base_dir, d["file"])
            for m in parse_dbc(open(path).read()).values():
                m["dir"] = "tx" if m["sender"] == d["node"] else "rx"
                specs[m["name"]] = m
        for m in cfg.get("messages", []):
            if m["name"] in specs:
                specs[m["name"]].update({k: v for k, v in m.items() if k != "signals"})
                if m.get("signals"):
                    specs[m["name"]]["signals"] = m["signals"]
            else:
                specs[m["name"]] = dict(m)
        self.msgs = [_Msg(s, off) for s in specs.values()]
        for m in self.msgs:
            for s in m.signals:
                if m.dir == "rx":
                    self.vars.setdefault(s["var"], 0)
        sm = cfg.get("state_machine", {})
        self.states = sm.get("states", {"RUN": {}}) or {"RUN": {}}
        self.state = sm.get("initial", next(iter(self.states)))
        self.trans = []
        for t in sm.get("transitions", []):
            self.trans.append((t["from"], t["to"], compile_expr(t["when"]) if "when" in t else None, t.get("after_ms")))
        self.lags = [(l["var"], compile_expr(l["target"]), float(l["tau_ms"]), l.get("states"), l.get("idle", 0))
                     for l in cfg.get("lags", [])]
        self.integrators = [(i["var"], compile_expr(i["rate"])) for i in cfg.get("integrators", [])]
        self.faults = []
        for f in list(cfg.get("faults", [])) + list(inst.get("faults", [])):
            self.faults.append({"spec": f, "when": compile_expr(f["when"]) if "when" in f else None, "on": False,
                                "done": False, "start": None})
        self.silenced = None
        self.entered_ms = 0
        self.last_rx = {}
        self.enter(self.state, 0)

    def env(self, t_ms):
        e = dict(self.vars)
        e.update(state=self.state, state_id=list(self.states).index(self.state), t_ms=t_ms,
                 in_state_ms=t_ms - self.entered_ms)
        return e

    def enter(self, state, t_ms):
        self.state = state
        self.entered_ms = t_ms
        self.vars.update((self.states.get(state) or {}).get("set", {}))


class Node:
    def __init__(self, ctx):
        self.ctx = ctx
        cfg = globals().get("CONFIG") or load_config(CONFIG_FILE)
        base = os.path.dirname(globals().get("CONFIG_FILE", "")) or "."
        self.tick_us = int(cfg.get("tick_us", 1000))
        self.t_ms = 0.0
        self.rx_log = []
        self.tx_count = {}
        self.trace = bool(cfg.get("log", True))
        insts = cfg.get("instances") or {cfg.get("name", "dev"): {}}
        self.devs = [_Device(n, cfg, i or {}, base) for n, i in insts.items()]
        self.index = {}
        for d in self.devs:
            for m in d.msgs:
                if m.dir == "rx":
                    self.index.setdefault((m.id, m.ext), []).append((d, m))
            for m in d.msgs:
                if m.dir == "tx" and m.period:
                    m.next_due = float(m.period)
        ctx.schedule_periodic(self.tick_us)

    def _log(self, msg):
        if self.trace:
            self.ctx.info("%7.1f ms %s" % (self.t_ms, msg))

    def _step(self, d):
        env = d.env(self.t_ms)
        for _ in range(len(d.states) + 1):
            for frm, to, when, after in d.trans:
                if frm != d.state:
                    continue
                if after is not None and env["in_state_ms"] < after:
                    continue
                if when is not None and not eval_expr(when, env):
                    continue
                self._log("%s state %s -> %s" % (d.name, d.state, to))
                d.enter(to, self.t_ms)
                env = d.env(self.t_ms)
                break
            else:
                break
        dt = self.tick_us / 1000.0
        for var, target, tau, states, idle in d.lags:
            tgt = eval_expr(target, env) if states is None or d.state in states else idle
            d.vars[var] += (tgt - d.vars[var]) * (1 - math.exp(-dt / tau)) if tau > 0 else tgt - d.vars[var]
        for var, rate in d.integrators:
            d.vars[var] += eval_expr(rate, env) * dt / 1000.0
        for f in d.faults:
            spec, a = f["spec"], f
            if not a["on"] and not a["done"]:
                hit = (spec.get("at_ms") is not None and self.t_ms >= spec["at_ms"]) or \
                      (f["when"] is not None and eval_expr(f["when"], env))
                if hit:
                    a["on"], a["start"] = True, self.t_ms
                    self._log("%s fault start: %s" % (d.name, spec.get("action", "silence")))
                    if spec.get("action", "silence") == "set":
                        d.vars.update(spec.get("vars", {}))
            if a["on"] and spec.get("for_ms") is not None and self.t_ms >= a["start"] + spec["for_ms"]:
                a["on"], a["done"] = False, True
                self._log("%s fault end" % d.name)
                if spec.get("action", "silence") == "set":
                    d.vars.update(spec.get("clear_vars", {}))

    def _silent(self, d, m):
        for f in d.faults:
            if f["on"] and f["spec"].get("action", "silence") == "silence":
                names = f["spec"].get("messages")
                if names is None or m.name in names:
                    return True
        return False

    def encode(self, d, m):
        buf = bytearray(m.dlc)
        env = d.env(self.t_ms)
        for s in m.signals:
            pack_signal(buf, s, float(eval_expr(s["_code"], env)))
        return bytes(buf)

    def _send(self, d, m):
        if self._silent(d, m) or (m.enabled_in and d.state not in m.enabled_in):
            return
        kw = {}
        if m.ext:
            kw["extended"] = True
        if m.fd:
            kw["fd"] = True
            kw["brs"] = m.brs
        self.ctx.send(m.id, self.encode(d, m), **kw)
        self.tx_count[(d.name, m.name)] = self.tx_count.get((d.name, m.name), 0) + 1

    def on_frame(self, frame):
        key = (frame["id"], bool(frame.get("extended", False)))
        for d, m in self.index.get(key, []):
            data = bytes(frame["data"])
            vals = {s["name"]: unpack_signal(data, s) for s in m.signals}
            for s in m.signals:
                d.vars[s["var"]] = vals[s["name"]]
            self.rx_log.append((self.t_ms, d.name, m.name, vals))
            del self.rx_log[:-1000]
            if d.last_rx.get(m.name) != vals:
                d.last_rx[m.name] = vals
                self._log("%s rx %s %s" % (d.name, m.name, " ".join("%s=%g" % kv for kv in vals.items())))
            self._step(d)
            for r in d.msgs:
                if r.dir == "tx" and r.on_rx == m.name:
                    self._send(d, r)

    def on_timer(self):
        self.t_ms += self.tick_us / 1000.0
        for d in self.devs:
            self._step(d)
            for m in d.msgs:
                if m.next_due is not None and self.t_ms + 1e-9 >= m.next_due:
                    m.next_due += m.period
                    self._send(d, m)
