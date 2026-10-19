function [yr, q, P] = period_parts(P)
%PERIOD_PARTS Normalise periods and split them into year and quarter (private helper).
%   [YR, Q, PN] = PERIOD_PARTS(P) accepts a char, string array, cell array or
%   numeric years. Each element is normalised the way the API data are:
%   '2026q1' or '2026 Q1' -> '2026Q1'; anything without a Q -> its first
%   4-digit year ('2026-01-01T00:00:00' -> '2026'). YR and Q are column
%   vectors (Q = 0 for annual periods, NaN for unreadable input) and PN is a
%   column cell array of normalised strings ('' when unreadable).

if isnumeric(P)
    C = arrayfun(@(y) sprintf('%d', y), P(:), 'UniformOutput', false);
elseif ischar(P)
    C = {P};
elseif isstring(P)
    C = cellstr(P(:));
elseif iscell(P)
    C = P(:);
else
    error('oe:badPeriod', 'Periods must be text such as ''2026Q3'' or ''2026'', or numeric years.');
end

n = numel(C);
yr = nan(n, 1);
q = nan(n, 1);
P = repmat({''}, n, 1);
for i = 1:n
    s = C{i};
    if ~ischar(s)
        if (isnumeric(s) || isstring(s)) && isscalar(s)
            s = char(string(s));
        else
            continue
        end
    end
    s = upper(regexprep(s, '\s+', ''));
    if contains(s, 'Q')
        tok = regexp(s, '^(\d{4})Q([1-4])$', 'tokens', 'once');
        if numel(tok) == 2
            yr(i) = str2double(tok{1});
            q(i) = str2double(tok{2});
            P{i} = sprintf('%dQ%d', yr(i), q(i));
        end
    else
        y = regexp(s, '\d{4}', 'match', 'once');
        if ~isempty(y)
            yr(i) = str2double(y);
            q(i) = 0;
            P{i} = y;
        end
    end
end
end
