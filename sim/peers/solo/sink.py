CONFIG = {"name": "sink", "tick_us": 1000, "messages": []}
exec(compile(open("@SIMANTIC@/peers/generic/can/table_node.py").read(), "table_node.py", "exec"))
