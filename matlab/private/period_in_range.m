function tf = period_in_range(P, from, to)
%PERIOD_IN_RANGE True for periods inside [FROM, TO] (private helper).
%   TF = PERIOD_IN_RANGE(P, FROM, TO) with FROM/TO empty for an open bound.
%   An annual period is compared by year, so 2026 is inside 2026Q3:2028Q4.
%   A quarterly period against an annual bound uses the whole year:
%   FROM = 2026 means 2026Q1, TO = 2028 means 2028Q4.

[yr, q] = period_parts(P);
tf = ~isnan(yr);
isA = q == 0;
if nargin >= 2 && ~isempty(from)
    [fy, fq] = bound(from, 'from');
    tf = tf & ((isA & yr >= fy) | (~isA & (yr * 4 + q) >= (fy * 4 + max(fq, 1))));
end
if nargin >= 3 && ~isempty(to)
    [ty, tq] = bound(to, 'to');
    if tq == 0
        tq = 4;
    end
    tf = tf & ((isA & yr <= ty) | (~isA & (yr * 4 + q) <= (ty * 4 + tq)));
end
end

function [y, q] = bound(b, label)
[y, q] = period_parts(b);
if numel(y) ~= 1 || isnan(y)
    error('oe:badPeriod', 'Bad "%s" period "%s": use e.g. ''2026Q3'' or ''2026''.', label, char(string(b)));
end
end
