CONFIG_FILE = "@SIMANTIC@/standins/solo/ccu_stub.yaml"
exec(compile(open("@SIM_FIXTURES@/peers/can/table_node.py").read(), "table_node.py", "exec"))
