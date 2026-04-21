import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.timing_feedback import (
    extract_critical_path_from_text,
    extract_log_hints_from_text,
    extract_architecture_hints_from_timing_report,
)


SAMPLE_REPORT = """
===REPORT_WNS===
worst slack max -2.01
===REPORT_TNS===
tns max -27.73
===REPORT_CHECKS_MAX===
Startpoint: b[12] (input port clocked by virtual_clk)
Endpoint: result[5] (output port clocked by virtual_clk)
Path Group: virtual_clk
Path Type: max

Fanout     Cap    Slew   Delay    Time   Description
-----------------------------------------------------------------------------
                                  7.20   data required time
                                 -9.21   data arrival time
-----------------------------------------------------------------------------
                                 -2.01   slack (VIOLATED)
===DONE===
"""


SAMPLE_CTS_LOG = """
repair_timing -setup_margin 0 -hold_margin 0 -repair_tns 100 -match_cell_footprint -verbose
[INFO RSZ-0094] Found 31 endpoints with setup violations.
   Iter   | Removed | Resized | Inserted | Cloned |  Pin  |   Area   |    WNS   |   StTNS    |   EnTNS    |  Viol  |  Worst
------------------------------------------------------------------------------------------------------------------------------
       0* |       0 |       0 |        0 |      0 |     0 |    +0.0% |   -2.530 |     -442.5 |      -59.8 |     31 | y_out[33]$_SDFF_PP0_/D
     470* |       3 |     156 |       17 |      2 |    92 |    +0.4% |   -2.197 |     -406.2 |      -53.2 |     31 | y_out[33]$_SDFF_PP0_/D
    1510* |       3 |     419 |       69 |      12 |   252 |    +1.4% |   -2.068 |     -388.4 |      -48.6 |     31 | y_out[30]$_SDFF_PP0_/D
"""


def test_extract_critical_path_from_text():
    extracted = extract_critical_path_from_text(SAMPLE_REPORT)
    assert extracted is not None
    assert "worst slack max -2.01" in extracted
    assert "tns max -27.73" in extracted
    assert "Startpoint: b[12]" in extracted
    assert "Endpoint: result[5]" in extracted
    assert "slack (VIOLATED)" in extracted



def test_extract_log_hints_from_cts_log():
    hints = extract_log_hints_from_text("4_1_cts.log", SAMPLE_CTS_LOG)
    joined = "\n".join(hints)
    assert "found 31 setup-violating endpoints" in joined
    assert "initial repair WNS -2.530" in joined
    assert "best repair WNS -2.068" in joined
    assert "y_out[30]$_SDFF_PP0_/D" in joined



def test_extract_log_hints_from_no_register_log():
    hints = extract_log_hints_from_text("3_4_place_resized.log", "No registers in design\n")
    assert hints
    assert "no registers in design" in hints[0].lower()



def test_extract_architecture_hints_from_timing_report():
    report = SAMPLE_REPORT + "\n" + "\n".join([
        "_1374_/SUM (sky130_fd_sc_hd__fa_1)",
        "_1379_/SUM (sky130_fd_sc_hd__fa_1)",
        "_1385_/SUM (sky130_fd_sc_hd__fa_1)",
        "_1391_/SUM (sky130_fd_sc_hd__fa_1)",
    ])
    hints = extract_architecture_hints_from_timing_report(report)
    joined = "\n".join(hints)
    assert "carry-save / Wallace-style" in joined
    assert "input-to-output combinational logic" in joined
    assert "Optimize the logic cone between these two points first" in joined
