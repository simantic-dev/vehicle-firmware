CONFIG_FILE = "@SIMANTIC@/standins/solo/dash_can.yaml"
exec(compile(open("@SIM_FIXTURES@/peers/can/table_node.py").read(), "peers/can/table_node.py", "exec"))
