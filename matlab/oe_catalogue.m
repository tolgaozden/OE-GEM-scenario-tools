function [ind, grp] = oe_catalogue(forecastId, xlsxFile)
%OE_CATALOGUE Indicator and group catalogue of a forecast or release.
%   [IND, GRP] = OE_CATALOGUE(FORECASTID) returns two tables. IND has
%   Code and Name plus any other scalar fields the API returns for the
%   indicators; GRP has Code, Name and Type plus extras for the groups
%   (economies and aggregates). FORECASTID is a forecast id or the struct
%   returned by OE_RESOLVE_RELEASE.
%
%   [IND, GRP] = OE_CATALOGUE(FORECASTID, XLSXFILE) also writes a workbook
%   with sheets Indicators, Groups and Shocks (indicators whose code or
%   name mentions shock, residual, add factor or dummy). An existing file
%   is replaced.
%
%   Use the catalogue to check every mnemonic before using it in a
%   scenario: codes differ between model versions.
%
%   Example:
%       rel = oe_resolve_release('latest:5yr');
%       [ind, grp] = oe_catalogue(rel, 'catalogue.xlsx');
%       ind(contains(lower(ind.Name), 'oil'), :)
%
%   See also OE_FETCH, OE_EQUATIONS.

fid = forecast_id(forecastId);
base = ['/v1/forecast-contents/' oe_quote_path(fid)];
ind = records_table(oe_api('GET', [base '/indicators']), {'Code', 'Name'});
grp = records_table(oe_api('GET', [base '/groups']), {'Code', 'Name', 'Type'});

if nargin >= 2 && ~isempty(xlsxFile)
    xlsxFile = char(xlsxFile);
    if isfile(xlsxFile)
        delete(xlsxFile);   % avoid stale sheets from an earlier run
    end
    writetable(ind, xlsxFile, 'Sheet', 'Indicators');
    writetable(grp, xlsxFile, 'Sheet', 'Groups');
    text = strcat(ind.Code, {' '}, ind.Name);
    isShock = ~cellfun(@isempty, regexpi(text, 'shock|residual|add[- ]?factor|dummy', 'once'));
    writetable(ind(isShock, :), xlsxFile, 'Sheet', 'Shocks');
    fprintf('Catalogue written to %s (%d indicators, %d groups)\n', xlsxFile, height(ind), height(grp));
end
end

function T = records_table(data, lead)
% Flatten a list of JSON records into a table: LEAD columns first, then
% every other field that holds scalar values, sorted by Code.
recs = as_records(data);
n = numel(recs);
names = lead;
for i = 1:n
    if isstruct(recs{i})
        f = fieldnames(recs{i});
        names = [names, f(~ismember(f, names))']; %#ok<AGROW>
    end
end
cols = cell(1, numel(names));
keep = true(1, numel(names));
for j = 1:numel(names)
    vals = cell(n, 1);
    isNum = true;
    anyVal = false;
    for i = 1:n
        v = [];
        if isstruct(recs{i}) && isfield(recs{i}, names{j})
            v = recs{i}.(names{j});
        end
        if (isnumeric(v) || islogical(v)) && isscalar(v)
            vals{i} = double(v);
            anyVal = true;
        elseif (ischar(v) && size(v, 1) <= 1) || (isstring(v) && isscalar(v))
            vals{i} = char(v);
            isNum = false;
            anyVal = true;
        elseif isempty(v)
            vals{i} = [];
        else
            keep(j) = false;   % nested lists or objects are left out
        end
    end
    if ~anyVal && ~ismember(names{j}, lead)
        keep(j) = false;
    end
    if isNum && anyVal
        x = nan(n, 1);
        has = ~cellfun(@isempty, vals);
        x(has) = cell2mat(vals(has));
        cols{j} = x;
    else
        txt = repmat({''}, n, 1);
        for i = 1:n
            if ischar(vals{i})
                txt{i} = vals{i};
            elseif ~isempty(vals{i})
                txt{i} = char(string(vals{i}));
            end
        end
        cols{j} = txt;
    end
end
T = table(cols{keep}, 'VariableNames', names(keep));
if n > 0
    T = sortrows(T, 'Code');
end
end
