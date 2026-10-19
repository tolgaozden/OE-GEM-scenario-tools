function T = oe_fetch(forecastId, indicators, groups, opts)
%OE_FETCH Fetch values for indicators x groups into a long table.
%   T = OE_FETCH(FORECASTID, INDICATORS, GROUPS) requests every indicator
%   for every group (codes as char, string or cell arrays) from a forecast
%   or release. FORECASTID is a forecast id or the struct returned by
%   OE_RESOLVE_RELEASE or OE_SOLVE (field forecastId). The result has one
%   row per value, with variables
%       forecast   label (opts.label)
%       indicator  indicator code, e.g. 'GDP'
%       group      group code, e.g. 'US'
%       period     '2026Q1' (quarterly) or '2026' (annual)
%       freq       'Q' or 'A'
%       value      level as returned by the API
%       measure    'level' (transforms change it, see OE_TRANSFORM)
%   Rows are sorted by forecast, indicator, group and period.
%
%   T = OE_FETCH(..., OPTS) with OPTS fields:
%       label           forecast label (default 'forecast')
%       from, to        keep periods in this window; annual rows are
%                       compared by year (default: everything)
%       annualFallback  re-request pairs with no data at annual frequency,
%                       for economies the model keeps annual-only
%                       (default true)
%       batch           selections per request, at most 400 (default 400)
%       frequency       '' (API default) or 'Annual' to ask for annual
%                       values directly
%
%   Example:
%       rel = oe_resolve_release('latest:5yr');
%       T = oe_fetch(rel, {'GDP', 'CPI'}, {'US', 'JAPAN'}, ...
%                    struct('label', 'baseline', 'from', '2025Q1', 'to', '2030Q4'));
%       % Check mnemonics in your own catalogue (oe_catalogue) first.
%
%   See also OE_TRANSFORM, OE_TABLE, OE_RUN_SCENARIOS.

if nargin < 4
    opts = struct();
end
o = merge_opts(opts, struct('label', 'forecast', 'from', '', 'to', '', 'annualFallback', true, ...
    'batch', 400, 'frequency', ''), 'oe_fetch');
fid = forecast_id(forecastId);
inds = code_list(indicators, 'indicators');
grps = code_list(groups, 'groups');
batch = max(1, min(400, round(o.batch)));

[gi, ii] = ndgrid(1:numel(grps), 1:numel(inds));
pairInd = inds(ii(:));
pairGrp = grps(gi(:));
url = ['/v1/forecast-contents/' oe_quote_path(fid) '/variables?onlyProps=Values'];

S = fetch_pairs(url, pairInd, pairGrp, char(o.frequency), batch);
if o.annualFallback && isempty(o.frequency)
    got = {};
    if ~isempty(S.ind)
        got = strcat(upper(S.ind), '|', upper(S.grp));
    end
    want = strcat(upper(pairInd), '|', upper(pairGrp));
    missing = ~ismember(want, got);
    if any(missing)
        A = fetch_pairs(url, pairInd(missing), pairGrp(missing), 'Annual', batch);
        if ~isempty(A.ind)
            fprintf('oe_fetch: %d indicator/group pair(s) came back only at annual frequency.\n', numel(A.ind));
        end
        S = merge_series(S, A);
    end
end

% Expand one entry per series into one row per value.
nv = cellfun(@numel, S.values);
n = sum(nv);
indicator = cell(n, 1);
group = cell(n, 1);
period = cell(n, 1);
value = nan(n, 1);
r = 0;
for k = 1:numel(nv)
    idx = r + (1:nv(k));
    indicator(idx) = S.ind(k);
    group(idx) = S.grp(k);
    period(idx) = S.periods{k};
    value(idx) = S.values{k};
    r = r + nv(k);
end
[~, q] = period_parts(period);
freq = repmat({'Q'}, n, 1);
freq(q == 0) = {'A'};
forecast = repmat({char(o.label)}, n, 1);
measure = repmat({'level'}, n, 1);
T = table(forecast, indicator, group, period, freq, value, measure);
T = T(period_in_range(T.period, o.from, o.to), :);
if height(T) > 1
    T = sortrows(T, {'forecast', 'indicator', 'group', 'period'});
end
if height(T) == 0
    warning('oe:noData', 'oe_fetch returned no values. Check the codes against oe_catalogue and the from/to window.');
end
end

function c = code_list(x, what)
if ischar(x)
    c = {x};
elseif isstring(x)
    c = cellstr(x(:));
elseif iscellstr(x)
    c = x(:);
else
    error('oe:badInput', '%s must be a char, string array or cell array of codes.', what);
end
c = strtrim(c);
c = c(~cellfun(@isempty, c));
c = unique(c, 'stable');
if isempty(c)
    error('oe:badInput', 'No %s given.', what);
end
end

function S = fetch_pairs(url, pairInd, pairGrp, freq, batch)
% One entry per returned series: S.ind{k}, S.grp{k}, S.periods{k}, S.values{k}.
S = struct('ind', {{}}, 'grp', {{}}, 'periods', {{}}, 'values', {{}});
n = numel(pairInd);
for b = 1:batch:n
    idx = b:min(b + batch - 1, n);
    sel = cell(1, numel(idx));
    for k = 1:numel(idx)
        if isempty(freq)
            sel{k} = struct('IndicatorCode', pairInd{idx(k)}, 'GroupCode', pairGrp{idx(k)});
        else
            sel{k} = struct('IndicatorCode', pairInd{idx(k)}, 'GroupCode', pairGrp{idx(k)}, 'Frequency', freq);
        end
    end
    recs = as_records(oe_api('POST', url, sel));
    for k = 1:numel(recs)
        rec = recs{k};
        if ~isstruct(rec) || ~isfield(rec, 'Values') || isempty(rec.Values)
            continue
        end
        [P, V] = parse_values(rec.Values);
        if isempty(P)
            continue
        end
        S.ind{end + 1, 1} = field_text(rec, 'IndicatorCode');
        S.grp{end + 1, 1} = field_text(rec, 'GroupCode');
        S.periods{end + 1, 1} = P;
        S.values{end + 1, 1} = V;
    end
end
end

function [P, V] = parse_values(vals)
recs = as_records(vals);
n = numel(recs);
raw = cell(n, 1);
V = nan(n, 1);
for k = 1:n
    r = recs{k};
    if ~isstruct(r) || ~isfield(r, 'Period')
        continue
    end
    raw{k} = r.Period;
    if isfield(r, 'Value')
        v = r.Value;
        if (isnumeric(v) || islogical(v)) && isscalar(v)
            V(k) = double(v);
        elseif ischar(v) || isstring(v)
            V(k) = str2double(v);
        end
    end
end
[~, ~, P] = period_parts(raw);
ok = ~cellfun(@isempty, P);
P = P(ok);
V = V(ok);
end

function S = merge_series(S, A)
for f = {'ind', 'grp', 'periods', 'values'}
    S.(f{1}) = [S.(f{1}); A.(f{1})];
end
end
