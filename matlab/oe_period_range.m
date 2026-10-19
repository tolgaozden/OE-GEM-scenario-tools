function P = oe_period_range(from, to)
%OE_PERIOD_RANGE Consecutive periods from FROM to TO, inclusive.
%   P = OE_PERIOD_RANGE(FROM, TO) returns a column cell array of period
%   strings. Quarterly periods look like '2026Q3', annual ones like '2026'
%   (numeric years are accepted). Both ends must have the same frequency.
%   P = OE_PERIOD_RANGE('2026Q3:2027Q2') takes the range as one string.
%
%   Example:
%       oe_period_range('2026Q3', '2027Q2')   % {'2026Q3';'2026Q4';'2027Q1';'2027Q2'}
%       oe_period_range(2026, 2028)           % {'2026';'2027';'2028'}
%
%   See also OE_TRANSFORM, OE_TABLE.

if nargin == 1
    parts = strsplit(char(string(from)), ':');
    if numel(parts) ~= 2
        error('oe:badPeriod', 'Give a range as ''FROM:TO'', e.g. ''2026Q3:2028Q4'', or as two arguments.');
    end
    from = parts{1};
    to = parts{2};
end
[y1, q1] = one_period(from);
[y2, q2] = one_period(to);
if (q1 == 0) ~= (q2 == 0)
    error('oe:badPeriod', 'Start "%s" and end "%s" must both be quarterly or both annual.', ...
        char(string(from)), char(string(to)));
end
if q1 == 0
    k = y1:y2;
    P = arrayfun(@(y) sprintf('%d', y), k(:), 'UniformOutput', false);
else
    k = (y1 * 4 + q1 - 1):(y2 * 4 + q2 - 1);
    P = arrayfun(@(x) sprintf('%dQ%d', floor(x / 4), mod(x, 4) + 1), k(:), 'UniformOutput', false);
end
if isempty(P)
    error('oe:badPeriod', 'Start "%s" is after end "%s".', char(string(from)), char(string(to)));
end
end

function [y, q] = one_period(p)
[y, q] = period_parts(p);
if numel(y) ~= 1 || isnan(y)
    error('oe:badPeriod', 'Bad period "%s": use e.g. ''2026Q3'' (quarterly) or ''2026'' (annual).', ...
        char(strjoin(string(p), ',')));
end
end
