module exp_fixed_point #(
  parameter WIDTH = 8
) (
  input  logic               clk,
  input  logic               rst,
  input  logic               enable,
  input  logic [WIDTH-1:0]   x_in,
  output logic [2*WIDTH-1:0] exp_out
);

  localparam int FRAC = WIDTH - 1;
  localparam int OUTW = 2 * WIDTH;

  logic [WIDTH-1:0]       x_s0;
  logic                   v_s0;

  logic [OUTW-1:0]        sum_s1;
  logic [OUTW-1:0]        x_s1_ext;
  logic [2*WIDTH-1:0]     x2_full_s1;
  logic                   v_s1;

  logic [OUTW-1:0]        sum_s2;
  logic [OUTW-1:0]        x2_term_s2;
  logic [3*WIDTH-1:0]     x3_full_s2;
  logic                   v_s2;

  logic [OUTW-1:0]        one_const;
  logic [OUTW-1:0]        x_in_ext_s0;
  logic [OUTW-1:0]        x2_term_calc_s1;
  logic [OUTW-1:0]        x3_term_calc_s2;
  logic [OUTW-1:0]        final_sum_s2;

  assign one_const     = {{(OUTW-(FRAC+1)){1'b0}}, 1'b1, {FRAC{1'b0}}};
  assign x_in_ext_s0    = {{WIDTH{1'b0}}, x_s0};
  assign x2_term_calc_s1 = x2_full_s1 >> (FRAC + 1);
  assign x3_term_calc_s2 = (x3_full_s2 >> (2 * FRAC)) / 6;
  assign final_sum_s2    = sum_s2 + x3_term_calc_s2;

  always_ff @(posedge clk) begin
    if (rst) begin
      x_s0       <= '0;
      v_s0       <= 1'b0;
      sum_s1     <= '0;
      x_s1_ext   <= '0;
      x2_full_s1 <= '0;
      v_s1       <= 1'b0;
      sum_s2     <= '0;
      x2_term_s2 <= '0;
      x3_full_s2 <= '0;
      v_s2       <= 1'b0;
      exp_out    <= '0;
    end else begin
      if (enable) begin
        x_s0 <= x_in;
        v_s0 <= 1'b1;
      end else begin
        v_s0 <= 1'b0;
      end

      sum_s1     <= one_const + x_in_ext_s0;
      x_s1_ext   <= x_in_ext_s0;
      x2_full_s1 <= x_s0 * x_s0;
      v_s1       <= v_s0;

      sum_s2     <= sum_s1 + x2_term_calc_s1;
      x2_term_s2 <= x2_term_calc_s1;
      x3_full_s2 <= x2_full_s1 * x_s1_ext[WIDTH-1:0];
      v_s2       <= v_s1;

      if (v_s2) begin
        exp_out <= final_sum_s2;
      end
    end
  end

endmodule