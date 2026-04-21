# Evaluation Directory

Consists of scripts, testbenches and comparisons metrics to evaluate generated solutions. 

For each problem you must run two evaluations scripts

### 1. Functional evaluation of Verilog

This will check the correctness of your generated RTL using the provided testbenches and iVerilog. An example command is provided below

```
python3 evaluate_verilog.py --verilog ../example_problem/output/iclad_seq_detector.v --problem 1 --tb ../example_problem/intermediate/iclad_seq_detector_tb.v
```

### 2. Physical evaluation of layout metrics

This will check the metrics of your generated layouts using the specification jsons provided. An example command is provided below

```
python3 evaluate_openroad.py --odb ../solutions/visible/p1/6_final.odb --sdc ../solutions/visible/p1/6_final.sdc --flow_root ../OpenROAD-flow-scripts --problem 1
```
