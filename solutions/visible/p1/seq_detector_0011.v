module seq_detector_0011(
    input clk,
    input reset,
    input data_in,
    output reg detected
);

    localparam [2:0]
        S0 = 3'b001, // no match
        S1 = 3'b010, // matched "0"
        S2 = 3'b011, // matched "00"
        S3 = 3'b100; // matched "001"

    reg [2:0] state, next_state;
    reg detected_next;

    always_comb begin
        next_state = state;
        detected_next = 1'b0;

        case (state)
            S0: begin
                if (data_in) begin
                    next_state = S0;
                end else begin
                    next_state = S1;
                end
            end

            S1: begin
                if (data_in) begin
                    next_state = S0;
                end else begin
                    next_state = S2;
                end
            end

            S2: begin
                if (data_in) begin
                    next_state = S3;
                end else begin
                    next_state = S2;
                end
            end

            S3: begin
                if (data_in) begin
                    next_state = S0;
                    detected_next = 1'b1;
                end else begin
                    next_state = S1;
                end
            end

            default: begin
                next_state = S0;
                detected_next = 1'b0;
            end
        endcase
    end

    always_ff @(posedge clk) begin
        if (reset) begin
            state <= S0;
            detected <= 1'b0;
        end else begin
            state <= next_state;
            detected <= detected_next;
        end
    end

endmodule