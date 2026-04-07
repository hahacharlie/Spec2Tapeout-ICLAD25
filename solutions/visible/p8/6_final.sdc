###############################################################################
# Created by write_sdc
###############################################################################
current_design fp16_multiplier
###############################################################################
# Timing Constraints
###############################################################################
create_clock -name virtual_clk -period 9.0000 
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[0]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[10]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[11]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[12]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[13]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[14]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[15]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[1]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[2]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[3]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[4]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[5]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[6]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[7]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[8]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {a[9]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[0]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[10]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[11]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[12]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[13]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[14]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[15]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[1]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[2]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[3]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[4]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[5]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[6]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[7]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[8]}]
set_input_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {b[9]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[0]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[10]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[11]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[12]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[13]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[14]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[15]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[1]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[2]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[3]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[4]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[5]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[6]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[7]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[8]}]
set_output_delay 1.8000 -clock [get_clocks {virtual_clk}] -add_delay [get_ports {result[9]}]
###############################################################################
# Environment
###############################################################################
###############################################################################
# Design Rules
###############################################################################
