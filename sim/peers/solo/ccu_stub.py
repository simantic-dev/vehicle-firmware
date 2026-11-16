CONFIG_FILE = "@SIMANTIC@/standins/solo/ccu_stub.yaml"
exec(compile(open("@SIMANTIC@/peers/generic/can/table_node.py").read(), "table_node.py", "exec"))
