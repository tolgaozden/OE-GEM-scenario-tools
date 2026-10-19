function W = oe_table(T, indicator, opts)
%OE_TABLE Pivot one indicator of a long table into a wide table.
%   W = OE_TABLE(T, INDICATOR) takes the rows of INDICATOR from the long
%   table T (from OE_FETCH, OE_RUN_SCENARIOS or OE_TRANSFORM) and returns
%   one row per group x forecast, with variables group, forecast and one
%   column per period ('2026Q1', ... or '2026', ...). If T holds more than
%   one measure for the indicator, a measure variable is added as well.
%   Group x forecast pairs without data are left out.
%
%   W = OE_TABLE(T, INDICATOR, OPTS) with OPTS fields:
%       groups     groups to keep, in this order (default: all)
%       forecasts  forecast labels to keep, in this order (default: all,
%                  with 'baseline' first)
%       measure    keep only this measure, e.g. 'annual_avg|yoy'
%       from, to   period window (annual periods compared by year)
%       decimals   round the values (default: no rounding)
%
%   Example:
%       G = oe_transform(T, 'annual_avg|yoy|dev_abs');
%       W = oe_table(G, 'GDP', struct('from', '2026', 'to', '2030', 'decimals', 2));
%       writetable(W, 'gdp_growth_deviation.csv');
%
%   See also OE_TRANSFORM, OE_FETCH.

if nargin < 3
    opts = struct();
end
o = merge_opts(opts, struct('groups', {{}}, 'forecasts', {{}}, 'measure', '', 'from', '', 'to', '', ...
    'decimals', []), 'oe_table');
T = long_table(T);
indicator = char(indicator);
T = T(strcmpi(T.indicator, indicator), :);
if isempty(T)
    error('oe:noData', 'No rows for indicator "%s". Check the code and the table passed in.', indicator);
end
if ~isempty(o.measure)
    T = T(strcmp(T.measure, char(o.measure)), :);
end
T = T(period_in_range(T.period, o.from, o.to), :);

if isempty(o.groups)
    groups = unique(T.group, 'stable');
else
    groups = cellstr(o.groups);
end
if isempty(o.forecasts)
    forecasts = unique(T.forecast, 'stable');
    isBase = strcmp(forecasts, 'baseline');
    forecasts = [forecasts(isBase); forecasts(~isBase)];
else
    forecasts = cellstr(o.forecasts);
end
measures = unique(T.measure, 'stable');
multi = numel(measures) > 1;
periods = unique(T.period);   % text order is time order within a frequency

sep = {char(31)};
key = strcat(T.group, sep, T.forecast, sep, T.measure);
[gg, ff, mm] = ndgrid(1:numel(groups), 1:numel(forecasts), 1:numel(measures));
order = sortrows([gg(:), ff(:), mm(:)]);
rowG = groups(order(:, 1));
rowF = forecasts(order(:, 2));
rowM = measures(order(:, 3));
rowKey = strcat(rowG(:), sep, rowF(:), sep, rowM(:));
present = ismember(rowKey, key);
rowG = rowG(present);
rowF = rowF(present);
rowM = rowM(present);
rowKey = rowKey(present);

[~, r] = ismember(key, rowKey);
[~, c] = ismember(T.period, periods);
ok = r > 0 & c > 0;
M = nan(numel(rowKey), numel(periods));
M(sub2ind(size(M), r(ok), c(ok))) = T.value(ok);
if ~isempty(o.decimals)
    M = round(M, o.decimals);
end

W = table(rowG(:), rowF(:), 'VariableNames', {'group', 'forecast'});
if multi
    W.measure = rowM(:);
end
W = [W, array2table(M, 'VariableNames', periods(:)')];
end
