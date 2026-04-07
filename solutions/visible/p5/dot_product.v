module dot_product #(
    parameter int N = 8,
    parameter int WIDTH = 8
) (
    input  logic clk,
    input  logic rst,
    input  logic signed [N-1:0][WIDTH-1:0] A,
    input  logic signed [N-1:0][WIDTH-1:0] B,
    output logic signed [2*WIDTH+3:0] dot_out,
    output logic valid
);

    localparam int PROD_W = 2*WIDTH;
    localparam int SUM1_W = PROD_W + 1;
    localparam int SUM2_W = SUM1_W + 1;
    localparam int SUM3_W = SUM2_W + 1;
    localparam int OUT_W  = 2*WIDTH + 4;

    logic [N-1:0][PROD_W-1:0] prod_c;
    logic [N-1:0][PROD_W-1:0] prod_r;

    logic [3:0][SUM1_W-1:0] sum1_c;
    logic [3:0][SUM1_W-1:0] sum1_r;

    logic [1:0][SUM2_W-1:0] sum2_c;
    logic [1:0][SUM2_W-1:0] sum2_r;

    logic [SUM3_W-1:0] sum3_c;
    logic [SUM3_W-1:0] sum3_r;

    logic valid_s1, valid_s2, valid_s3, valid_s4;

    genvar i;
    generate
        for (i = 0; i < N; i++) begin : GEN_PROD
            assign prod_c[i] = A[i] * B[i];
        end
    endgenerate

    assign sum1_c[0] = prod_r[0] + prod_r[1];
    assign sum1_c[1] = prod_r[2] + prod_r[3];
    assign sum1_c[2] = prod_r[4] + prod_r[5];
    assign sum1_c[3] = prod_r[6] + prod_r[7];

    assign sum2_c[0] = sum1_r[0] + sum1_r[1];
    assign sum2_c[1] = sum1_r[2] + sum1_r[3];

    assign sum3_c = sum2_r[0] + sum2_r[1];

    always_ff @(posedge clk) begin
        if (rst) begin
            prod_r   <= '0;
            sum1_r   <= '0;
            sum2_r   <= '0;
            sum3_r   <= '0;
            dot_out  <= '0;
            valid_s1 <= 1'b0;
            valid_s2 <= 1'b0;
            valid_s3 <= 1'b0;
            valid_s4 <= 1'b0;
            valid    <= 1'b0;
        end else begin
            prod_r   <= prod_c;
            sum1_r   <= sum1_c;
            sum2_r   <= sum2_c;
            sum3_r   <= sum3_c;
            dot_out  <= sum3_r;
            valid_s1 <= 1'b1;
            valid_s2 <= valid_s1;
            valid_s3 <= valid_s2;
            valid_s4 <= valid_s3;
            valid    <= valid_s4;
        end
    end

endmodule