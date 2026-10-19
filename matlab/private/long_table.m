function T = long_table(T)
%LONG_TABLE Check and tidy a long results table (private helper).
%   Returns the table with the standard columns in the standard order:
%   forecast, indicator, group, period, freq, value, measure. Text columns
%   become cell arrays of char (string or categorical columns, e.g. from
%   readtable, are converted). A missing measure column is filled with
%   'level' and a missing freq column is derived from the period. Numeric
%   periods (annual years read back from CSV) become text.

if ~istable(T)
    error('oe:badInput', 'Expected a table with variables forecast, indicator, group, period, value.');
end
need = {'forecast', 'indicator', 'group', 'period', 'value'};
missing = need(~ismember(need, T.Properties.VariableNames));
if ~isempty(missing)
    error('oe:badInput', 'Table is missing variable(s): %s. Use the output of oe_fetch or oe_run_scenarios.', ...
        strjoin(missing, ', '));
end
n = height(T);
for c = {'forecast', 'indicator', 'group', 'measure', 'freq'}
    name = c{1};
    if ~ismember(name, T.Properties.VariableNames)
        continue
    end
    col = T.(name);
    if isstring(col) || iscategorical(col)
        T.(name) = cellstr(col);
    end
end
[~, q, P] = period_parts(T.period);
T.period = P;
if ~ismember('freq', T.Properties.VariableNames)
    f = repmat({'Q'}, n, 1);
    f(q == 0) = {'A'};
    T.freq = f;
end
if ~ismember('measure', T.Properties.VariableNames)
    T.measure = repmat({'level'}, n, 1);
end
T.value = double(T.value);
T = T(:, {'forecast', 'indicator', 'group', 'period', 'freq', 'value', 'measure'});
end
