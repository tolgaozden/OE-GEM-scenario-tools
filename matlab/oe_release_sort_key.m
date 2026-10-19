function key = oe_release_sort_key(name)
%OE_RELEASE_SORT_KEY Sortable [year month n] key for a dated release name.
%   KEY = OE_RELEASE_SORT_KEY(NAME) reads names of the form MonYY[_n]
%   followed by a horizon, such as 'Sep26_2 5yr' -> [2026 9 2] or
%   'Jun26 25yr' -> [2026 6 0]. For one name, an undated name gives [].
%   For a cell array or string array of names, KEY has one row per name and
%   undated names give a row of NaN. Sorting the rows sorts the releases
%   by year, then month, then release number.
%
%   Example:
%       k = oe_release_sort_key({'Sep26_2 5yr'; 'Sep26_10 5yr'; 'Jun26_1 5yr'});
%       [~, newestFirst] = sortrows(k, [-1 -2 -3]);
%
%   See also OE_RELEASES, OE_RESOLVE_RELEASE.

if ischar(name) || (isstring(name) && isscalar(name))
    key = one_key(char(name));
    if any(isnan(key))
        key = [];
    end
    return
end
names = cellstr(name);
key = nan(numel(names), 3);
for i = 1:numel(names)
    key(i, :) = one_key(names{i});
end
end

function k = one_key(s)
k = nan(1, 3);
months = {'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'};
s = strtrim(s);
% Two steps on purpose: MATLAB's regexp does not report a token captured
% inside an optional group, so the release number gets its own pattern.
if isempty(regexp(s, '^[A-Za-z]{3}\d{2}(?:_\d+)?(?:\s|$)', 'once'))
    return
end
m = find(strcmpi(s(1:3), months), 1);
if isempty(m)
    return
end
n = 0;
tok = regexp(s, '^[A-Za-z]{3}\d{2}_(\d+)', 'tokens', 'once');
if ~isempty(tok)
    n = str2double(tok{1});
end
k = [2000 + str2double(s(4:5)), m, n];
end
