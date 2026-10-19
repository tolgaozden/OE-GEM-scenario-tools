function out = period_shift(P, n)
%PERIOD_SHIFT Move periods by N steps at their own frequency (private helper).
%   OUT = PERIOD_SHIFT(P, N) returns a column cell array. Quarterly periods
%   move by N quarters, annual periods by N years. N is a scalar or a vector
%   with one entry per period. Unreadable periods give ''.

[yr, q] = period_parts(P);
m = numel(yr);
if isscalar(n)
    n = repmat(n, m, 1);
end
n = n(:);
out = repmat({''}, m, 1);
for i = 1:m
    if isnan(yr(i))
        continue
    end
    if q(i) == 0
        out{i} = sprintf('%d', yr(i) + n(i));
    else
        k = yr(i) * 4 + q(i) - 1 + n(i);
        out{i} = sprintf('%dQ%d', floor(k / 4), mod(k, 4) + 1);
    end
end
end
