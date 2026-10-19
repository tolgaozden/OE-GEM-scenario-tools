function T2 = oe_transform(T, step, baselineLabel)
%OE_TRANSFORM Growth rates, annual averages and deviations on a long table.
%   T2 = OE_TRANSFORM(T, STEP) applies STEP to the long table T from
%   OE_FETCH or OE_RUN_SCENARIOS:
%       'yoy'         % change on the same period a year earlier
%                     (quarterly: 4 quarters back; annual: 1 year back)
%       'annual_avg'  mean of the four quarters of each year; years with
%                     fewer than 4 quarters give NaN; annual rows pass
%                     through unchanged
%       'dev_pct'     % deviation of each scenario from the baseline
%       'dev_abs'     scenario minus baseline (use it for rates and for
%                     growth rates, where it gives percentage points)
%       'level'       no change
%   Chain steps with '|' or a cell array: 'annual_avg|yoy|dev_abs'.
%   T2 = OE_TRANSFORM(T, STEP, BASELINELABEL) names the baseline forecast
%   label for the dev_* steps (default 'baseline'). Deviation steps drop
%   the baseline rows.
%
%   Lags are found by period arithmetic, not by row position, so a gap in
%   the data gives NaN rather than a misaligned value. The measure
%   variable records the steps applied, e.g. 'annual_avg|yoy|dev_abs'.
%
%   Example:
%       A = oe_transform(T, 'annual_avg|yoy');           % annual growth
%       D = oe_transform(A, 'dev_abs', 'baseline');      % pp difference
%
%   See also OE_FETCH, OE_TABLE.

if nargin < 3 || isempty(baselineLabel)
    baselineLabel = 'baseline';
end
baselineLabel = char(baselineLabel);
if ischar(step) || (isstring(step) && isscalar(step))
    steps = strsplit(char(step), '|');
elseif iscellstr(step) || isstring(step)
    steps = cellstr(step);
else
    error('oe:badStep', 'STEP must be text such as ''yoy'' or ''annual_avg|yoy'', or a cell array of steps.');
end
T2 = long_table(T);
for i = 1:numel(steps)
    s = lower(strtrim(steps{i}));
    switch s
        case 'level'
        case 'yoy'
            T2 = yoy(T2);
        case 'annual_avg'
            T2 = annual_avg(T2);
        case {'dev_pct', 'dev_abs'}
            T2 = deviation(T2, s(5:end), baselineLabel);
        otherwise
            error('oe:badStep', ['Unknown step "%s". Use yoy, annual_avg, dev_pct, dev_abs or level; ' ...
                'chain them with "|", e.g. "annual_avg|yoy".'], steps{i});
    end
    if ~strcmp(s, 'level')
        T2.measure = add_step(T2.measure, s);
    end
end
if height(T2) > 1
    T2 = sortrows(T2, {'forecast', 'indicator', 'group', 'period'});
end
end

function T = yoy(T)
[~, q] = period_parts(T.period);
lagP = period_shift(T.period, -4 * (q > 0) - (q == 0));
k = row_key(T, T.period);
kLag = row_key(T, lagP);
[tf, loc] = ismember(kLag, k);
tf = tf & ~isnan(q);
v = nan(height(T), 1);
v(tf) = 100 * (T.value(tf) ./ T.value(loc(tf)) - 1);
T.value = v;
end

function T = annual_avg(T)
[yr, q] = period_parts(T.period);
isQ = q > 0;
A = T(~isQ, :);
Q = T(isQ, :);
if isempty(Q)
    T = A;
    return
end
years = arrayfun(@(y) sprintf('%d', y), yr(isQ), 'UniformOutput', false);
[~, first, grp] = unique(row_key(Q, years), 'stable');
ok = ~isnan(Q.value);
x = Q.value;
x(~ok) = 0;
total = accumarray(grp, x);
count = accumarray(grp, double(ok));
avg = total ./ count;
avg(count < 4) = NaN;   % an incomplete year has no annual average
n = numel(first);
N = table(Q.forecast(first), Q.indicator(first), Q.group(first), years(first), repmat({'A'}, n, 1), ...
    avg, Q.measure(first), 'VariableNames', T.Properties.VariableNames);
T = [A; N];
end

function T = deviation(T, kind, base)
isBase = strcmp(T.forecast, base);
if ~any(isBase)
    error('oe:noBaseline', 'No rows have forecast label "%s" (labels present: %s). Pass the baseline label as the third argument.', ...
        base, strjoin(unique(T.forecast)', ', '));
end
B = T(isBase, :);
S = T(~isBase, :);
sep = {char(31)};
kB = strcat(B.indicator, sep, B.group, sep, B.measure, sep, B.period);
kS = strcat(S.indicator, sep, S.group, sep, S.measure, sep, S.period);
[tf, loc] = ismember(kS, kB);
v = nan(height(S), 1);
if strcmp(kind, 'pct')
    v(tf) = 100 * (S.value(tf) ./ B.value(loc(tf)) - 1);
else
    v(tf) = S.value(tf) - B.value(loc(tf));
end
S.value = v;
T = S;
end

function k = row_key(T, periods)
sep = {char(31)};
if isempty(periods)
    k = cell(0, 1);
    return
end
k = strcat(T.forecast, sep, T.indicator, sep, T.group, sep, T.measure, sep, periods);
end

function m = add_step(m, s)
isLevel = strcmp(m, 'level') | cellfun(@isempty, m);
m(isLevel) = {s};
m(~isLevel) = strcat(m(~isLevel), {['|' s]});
end
