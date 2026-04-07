###############################################################################
# Created by write_sdc
###############################################################################
current_design exp_fixed_point
###############################################################################
# Timing Constraints
###############################################################################
create_clock -name clk -period 4.5000 [get_ports {clk}]
set_propagated_clock [get_clocks {clk}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {enable}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {rst}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {x_in[0]}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {x_in[1]}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {x_in[2]}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {x_in[3]}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {x_in[4]}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {x_in[5]}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {x_in[6]}]
set_input_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {x_in[7]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[0]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[10]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[11]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[12]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[13]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[14]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[15]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[1]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[2]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[3]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[4]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[5]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[6]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[7]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[8]}]
set_output_delay 0.9000 -clock [get_clocks {clk}] -add_delay [get_ports {exp_out[9]}]
###############################################################################
# Environment
###############################################################################
###############################################################################
# Design Rules
###############################################################################
