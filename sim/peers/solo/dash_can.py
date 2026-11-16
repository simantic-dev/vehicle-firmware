CONFIG_FILE = "@SIMANTIC@/standins/solo/dash_can.yaml"
exec(compile(open("@SIMANTIC@/peers/generic/can/table_node.py").read(), "peers/can/table_node.py", "exec"))
