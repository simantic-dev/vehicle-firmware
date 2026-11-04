CONFIG = {"name": "sink", "tick_us": 1000, "messages": []}
exec(compile(open("@SIM_FIXTURES@/peers/can/table_node.py").read(), "table_node.py", "exec"))
