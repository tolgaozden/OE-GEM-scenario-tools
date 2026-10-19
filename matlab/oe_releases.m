function T = oe_releases(root, maxDepth)
%OE_RELEASES List the model releases found under a release folder.
%   T = OE_RELEASES() walks 'oxford-economics/releases/Global Economic Model'
%   down to 4 levels and returns a table with one row per release:
%       name        e.g. 'Sep26_2 5yr'
%       path        full resource path (use it as the solve input)
%       id          forecast id (use it to fetch data)
%       horizon     '5yr', '25yr', ... ('' if the name carries none)
%       isPrevious  true for releases under a 'Previous releases' folder
%   Rows are sorted newest first (by year, month and release number).
%   T = OE_RELEASES(ROOT, MAXDEPTH) walks another folder or depth. The tree
%   is walked, not assumed, so new folder levels are picked up.
%
%   Example:
%       T = oe_releases();
%       T(~T.isPrevious, :)       % current releases
%
%   See also OE_RESOLVE_RELEASE, OE_RELEASE_SORT_KEY, OE_RESOURCE.

if nargin < 1 || isempty(root)
    root = 'oxford-economics/releases/Global Economic Model';
end
if nargin < 2 || isempty(maxDepth)
    maxDepth = 4;
end
rows = walk(char(root), 1, maxDepth);
if isempty(rows)
    rows = cell(0, 4);
end
names = rows(:, 1);
paths = rows(:, 2);
ids = rows(:, 3);
horizons = cell(size(names));
for i = 1:numel(names)
    tok = regexp(names{i}, '(\d+)\s*yr\s*$', 'tokens', 'once', 'ignorecase');
    if isempty(tok)
        horizons{i} = '';
    else
        horizons{i} = [tok{1} 'yr'];
    end
end
isPrevious = ~cellfun(@isempty, regexpi(paths, 'previous releases', 'once'));
T = table(names, paths, ids, horizons, isPrevious, ...
    'VariableNames', {'name', 'path', 'id', 'horizon', 'isPrevious'});
if height(T) > 1
    key = oe_release_sort_key(T.name);
    key(isnan(key)) = -Inf;   % undated names go last
    [~, order] = sortrows([key, double(~T.isPrevious)], [-1 -2 -3 -4]);
    T = T(order, :);
end
end

function rows = walk(path, depth, maxDepth)
% Returns an n-by-4 cell array {name, path, id, type} of the leaves below PATH.
rows = cell(0, 4);
res = oe_resource(path);
kids = {};
for f = {'Children', 'Items', 'Resources'}
    if isstruct(res) && isfield(res, f{1}) && ~isempty(res.(f{1}))
        kids = as_records(res.(f{1}));
        break
    end
end
for i = 1:numel(kids)
    k = kids{i};
    name = field_text(k, 'Name');
    kpath = field_text(k, 'Path');
    if isempty(kpath)
        kpath = [regexprep(path, '/+$', '') '/' name];
    end
    type = field_text(k, {'Type', 'ResourceType'});
    id = field_text(k, 'Id');
    isDir = ~isempty(regexpi(type, 'dir|folder', 'once'));
    % A child without a type and without a dated name is probably a folder:
    % look inside it, and record it as a leaf only if it turns out empty.
    unknown = isempty(type) && isempty(oe_release_sort_key(name));
    if isDir || unknown
        if depth < maxDepth
            sub = walk(kpath, depth + 1, maxDepth);
            if isempty(sub) && unknown
                sub = {name, kpath, id, type};
            end
            rows = [rows; sub]; %#ok<AGROW>
        end
    else
        rows(end + 1, :) = {name, kpath, id, type}; %#ok<AGROW>
    end
end
end
