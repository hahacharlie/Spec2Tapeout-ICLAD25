module fp16_multiplier(
  input  logic [15:0] a,
  input  logic [15:0] b,
  output logic [15:0] result
);

  logic sign_a;
  logic sign_b;
  logic [4:0] exp_a;
  logic [4:0] exp_b;
  logic [9:0] frac_a;
  logic [9:0] frac_b;

  logic a_exp_zero;
  logic b_exp_zero;
  logic a_exp_max;
  logic b_exp_max;
  logic a_frac_zero;
  logic b_frac_zero;

  logic a_is_zero;
  logic b_is_zero;
  logic a_is_inf;
  logic b_is_inf;
  logic a_is_nan;
  logic b_is_nan;

  logic sign_res;

  logic [10:0] mant_a;
  logic [10:0] mant_b;
  logic [21:0] mant_prod;

  logic norm_shift;
  logic [7:0] exp_sum_biased_u;
  logic [7:0] exp_norm_biased_u;

  logic [10:0] sig_pre;
  logic guard_bit;
  logic round_bit;
  logic sticky_bit;
  logic lsb_bit;
  logic round_inc;

  logic [11:0] sig_rounded_ext;
  logic sig_round_overflow;
  logic [10:0] sig_rounded;
  logic [7:0] exp_rounded_biased_u;

  logic overflow_to_inf;
  logic underflow_to_zero;

  logic [4:0] exp_final_norm;
  logic [9:0] frac_final_norm;

  assign sign_a = a[15];
  assign sign_b = b[15];
  assign exp_a  = a[14:10];
  assign exp_b  = b[14:10];
  assign frac_a = a[9:0];
  assign frac_b = b[9:0];

  assign a_exp_zero  = (exp_a == 5'd0);
  assign b_exp_zero  = (exp_b == 5'd0);
  assign a_exp_max   = (exp_a == 5'd31);
  assign b_exp_max   = (exp_b == 5'd31);
  assign a_frac_zero = (frac_a == 10'd0);
  assign b_frac_zero = (frac_b == 10'd0);

  assign a_is_zero = a_exp_zero && a_frac_zero;
  assign b_is_zero = b_exp_zero && b_frac_zero;
  assign a_is_inf  = a_exp_max && a_frac_zero;
  assign b_is_inf  = b_exp_max && b_frac_zero;
  assign a_is_nan  = a_exp_max && !a_frac_zero;
  assign b_is_nan  = b_exp_max && !b_frac_zero;

  assign sign_res = sign_a ^ sign_b;

  assign mant_a = a_exp_zero ? {1'b0, frac_a} : {1'b1, frac_a};
  assign mant_b = b_exp_zero ? {1'b0, frac_b} : {1'b1, frac_b};
  assign mant_prod = mant_a * mant_b;

  assign norm_shift = mant_prod[21];

  assign exp_sum_biased_u  = {3'b000, exp_a} + {3'b000, exp_b} + 8'd241; // -15 mod 256
  assign exp_norm_biased_u = exp_sum_biased_u + {7'd0, norm_shift};

  assign sig_pre    = norm_shift ? mant_prod[21:11] : mant_prod[20:10];
  assign guard_bit  = norm_shift ? mant_prod[10]    : mant_prod[9];
  assign round_bit  = norm_shift ? mant_prod[9]     : mant_prod[8];
  assign sticky_bit = norm_shift ? (|mant_prod[8:0]) : (|mant_prod[7:0]);
  assign lsb_bit    = sig_pre[0];

  assign round_inc = guard_bit && (round_bit || sticky_bit || lsb_bit);

  assign sig_rounded_ext    = {1'b0, sig_pre} + {11'd0, round_inc};
  assign sig_round_overflow = sig_rounded_ext[11];
  assign sig_rounded        = sig_round_overflow ? sig_rounded_ext[11:1] : sig_rounded_ext[10:0];
  assign exp_rounded_biased_u = exp_norm_biased_u + {7'd0, sig_round_overflow};

  assign overflow_to_inf   = exp_rounded_biased_u[7] || (exp_rounded_biased_u[6:0] >= 7'd31);
  assign underflow_to_zero = exp_rounded_biased_u[7] || (exp_rounded_biased_u[6:0] == 7'd0);

  assign exp_final_norm  = exp_rounded_biased_u[4:0];
  assign frac_final_norm = sig_rounded[9:0];

  always_comb begin
    result = 16'h0000;

    if (a_is_nan || b_is_nan || ((a_is_zero && b_is_inf) || (a_is_inf && b_is_zero))) begin
      result = 16'h7E00;
    end else if (a_is_inf || b_is_inf) begin
      result = {sign_res, 5'h1F, 10'h000};
    end else if (a_is_zero || b_is_zero) begin
      result = {sign_res, 5'h00, 10'h000};
    end else if (overflow_to_inf) begin
      result = {sign_res, 5'h1F, 10'h000};
    end else if (underflow_to_zero) begin
      result = {sign_res, 5'h00, 10'h000};
    end else begin
      result = {sign_res, exp_final_norm, frac_final_norm};
    end
  end

endmodule