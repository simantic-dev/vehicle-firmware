# writes inv4.yaml: four-inverter CAN device (local, encodes the vehicle's inverter protocol) for peers/can/table_node.py
# All eight periodic frames use the same 10 ms period (the CAN medium serialises them); no stagger.
INV = [("1",0x80,0x81,0x82,0x92,0x99),("2",0x85,0x86,0x87,0x93,0x102),("3",0x70,0x71,0x72,0x90,0x97),("4",0x75,0x76,0x77,0x91,0x98)]
o = ["# 4 inverters on CAN3 (500 kbit): STATUS + TEMPS + DYNAMICS tx every 10 ms, CONTROL_WORD + CONTROL_INPUT rx.",
     "# HV present from hv_on_ms; quit_dc_on follows hv_enable; quit_inverter_on follows inverter_enable and driver_enable and quit_dc_on;",
     "# torque echo = positive torque limit through a 20 ms lag while enabled and the speed set point is > 0; temperatures follow the echo.",
     "name: inv4", "tick_us: 500", "vars:", "  hv_on_ms: 1000"]
for n,*_ in INV:
    for v in ("inv_en","hv_en","drv_en","rm_err","spd","plim","nlim","tq","err"): o.append("  %s%s: 0" % (v,n))
o.append("messages:")
for n,st,tp,dy,wd,ci in INV:
    ready = "(t_ms >= hv_on_ms)"
    quit_dc = "(%s and hv_en%s)" % (ready, n)
    quit_inv = "(%s and inv_en%s and drv_en%s)" % (quit_dc, n, n)
    o += [f"  - name: INV{n}_STATUS", f"    id: 0x{st:X}", "    shared: true", "    dir: tx", "    period_ms: 10", "    dlc: 8", "    signals:",
          f"      - {{name: system_ready, start: 8, length: 1, expr: \"1 if {ready} else 0\"}}",
          f"      - {{name: error, start: 9, length: 1, expr: err{n}}}",
          f"      - {{name: quit_dc_on, start: 11, length: 1, expr: \"1 if {quit_dc} else 0\"}}",
          f"      - {{name: dc_on, start: 12, length: 1, expr: \"1 if ({ready} and hv_en{n}) else 0\"}}",
          f"      - {{name: quit_inverter_on, start: 13, length: 1, expr: \"1 if {quit_inv} else 0\"}}",
          f"      - {{name: inverter_on, start: 14, length: 1, expr: \"1 if {quit_inv} else 0\"}}",
          f"      - {{name: dc_bus_voltage, start: 16, length: 16, expr: \"400 if {ready} else 0\"}}",
          f"  - name: INV{n}_TEMPS", f"    id: 0x{tp:X}", "    shared: true", "    dir: tx", "    period_ms: 10", "    dlc: 6", "    signals:",
          f"      - {{name: motor_temp, start: 0, length: 16, signed: true, scale: 0.1, expr: \"40 + 1.2 * tq{n}\"}}",
          f"      - {{name: inverter_temp, start: 16, length: 16, signed: true, scale: 0.1, expr: \"45 + 0.8 * tq{n}\"}}",
          f"  - name: INV{n}_DYNAMICS", f"    id: 0x{dy:X}", "    shared: true", "    dir: tx", "    period_ms: 10", "    dlc: 8", "    signals:",
          f"      - {{name: actual_power_w, start: 0, length: 32, value: 0}}",
          f"      - {{name: actual_torque_nm_ro, start: 32, length: 16, signed: true, scale: 0.0098, expr: tq{n}}}",
          f"      - {{name: actual_speed_rpm, start: 48, length: 16, signed: true, value: 0}}",
          f"  - name: INV{n}_CONTROL_WORD", f"    id: 0x{wd:X}", "    shared: true", "    dir: rx", "    dlc: 8", "    signals:",
          f"      - {{name: inverter_enable, start: 8, length: 1, var: inv_en{n}}}",
          f"      - {{name: hv_enable, start: 9, length: 1, var: hv_en{n}}}",
          f"      - {{name: driver_enable, start: 10, length: 1, var: drv_en{n}}}",
          f"      - {{name: remove_error, start: 11, length: 1, var: rm_err{n}}}",
          f"  - name: INV{n}_CONTROL_INPUT", f"    id: 0x{ci:X}", "    shared: true", "    dir: rx", "    dlc: 8", "    signals:",
          f"      - {{name: speed_setpoint_rpm, start: 0, length: 16, signed: true, var: spd{n}}}",
          f"      - {{name: positive_torque_limit, start: 16, length: 16, signed: true, scale: 0.0098, var: plim{n}}}",
          f"      - {{name: negative_torque_limit, start: 32, length: 16, signed: true, scale: 0.0098, var: nlim{n}}}"]
o.append("lags:")
for n,*_ in INV:
    en = "(t_ms >= hv_on_ms and hv_en%s and inv_en%s and drv_en%s and spd%s > 0)" % ((n,)*4)
    o.append(f"  - {{var: tq{n}, target: \"plim{n} if {en} else 0\", tau_ms: 20}}")
o += ["faults:",
      "  - {at_ms: 8600, action: set, vars: {err1: 1}}",
      "  - {when: \"t_ms > 8700 and rm_err1 == 1\", action: set, vars: {err1: 0}}"]
open("inv4.yaml","w").write("\n".join(o)+"\n")
