module fir_filter #(
  parameter WIDTH = 16,
  parameter N = 8
) (
  input  logic                             clk,
  input  logic                             rst,
  input  logic signed [WIDTH-1:0]          x_in,
  input  logic signed [N-1:0][WIDTH-1:0]   h,
  output logic signed [2*WIDTH+$clog2(N):0] y_out
);

  localparam int ACC_W = 2*WIDTH + $clog2(N) + 1;

  logic signed [N-1:0][WIDTH-1:0] x_delay;
  logic signed [ACC_W-1:0]        sum_comb;

  integer i;

  always_comb begin
    sum_comb = '0;
    for (i = 0; i < N; i = i + 1) begin
      if (i == 0) begin
        sum_comb = sum_comb + ($signed(x_in) * $signed(h[i]));
      end else begin
        sum_comb = sum_comb + ($signed(x_delay[i-1]) * $signed(h[i]));
      end
    end
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      for (i = 0; i < N; i = i + 1) begin
        x_delay[i] <= '0;
      end
      y_out <= '0;
    end else begin
      x_delay[0] <= x_in;
      for (i = 1; i < N; i = i + 1) begin
        x_delay[i] <= x_delay[i-1];
      end
      y_out <= sum_comb;
    end
  end

endmodule