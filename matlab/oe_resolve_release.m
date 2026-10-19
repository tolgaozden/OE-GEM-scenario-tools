function res = oe_resolve_release(spec, releases)
%OE_RESOLVE_RELEASE Turn a release name, path or 'latest' into a resource.
%   RES = OE_RESOLVE_RELEASE(SPEC) returns a struct with at least Id, Name
%   and Path. SPEC can be:
%       a full path        'oxford-economics/releases/...', '/me/...'
%       a release name     e.g. 'Sep26_2 5yr', searched in the release tree
%       'latest'           newest dated release of any horizon
%       'latest:5yr'       newest release with that horizon ('latest:25yr', ...)
%       a forecast id      returned as struct('Id', SPEC, 'Name', SPEC, 'Path', '')
%   Newest means the largest (year, month, release number) read from the
%   name (see OE_RELEASE_SORT_KEY); current releases win ties against
%   copies under 'Previous releases'.
%
%   RES = OE_RESOLVE_RELEASE(SPEC, RELEASES) searches a release table you
%   already have (the output of OE_RELEASES) instead of walking the tree
%   again. Rows found there are returned without another request.
%
%   Example:
%       rel = oe_resolve_release('latest:5yr');
%       fprintf('%s -> %s\n', rel.Name, rel.Path);
%
%   See also OE_RELEASES, OE_RELEASE_SORT_KEY, OE_RESOURCE.

if isstring(spec)
    spec = char(spec);
end
if ~ischar(spec) || isempty(strtrim(spec))
    error('oe:badInput', 'Release spec must be text: a release name, a path, ''latest'' or ''latest:5yr''.');
end
spec = strtrim(spec);
given = nargin >= 2 && ~isempty(releases);

uuid = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$';
if ~isempty(regexp(spec, uuid, 'once'))
    res = struct('Id', spec, 'Name', spec, 'Path', '');
    fprintf('Release: forecast id %s (no path; it can be fetched but not used as a solve input)\n', spec);
    return
end
if contains(spec, '/')
    res = complete(oe_resource(spec), spec);
    fprintf('Release: %s\n', res.Path);
    return
end

if ~given
    releases = oe_releases();
end
names = cellstr(releases.name);
isPrev = logical(releases.isPrevious);
low = lower(spec);
if strcmp(low, 'latest') || startsWith(low, 'latest:')
    horizon = strrep(low(7:end), ':', '');
    horizon = strrep(horizon, ' ', '');
    key = oe_release_sort_key(names);
    ok = ~isnan(key(:, 1));
    if ~isempty(horizon)
        ok = ok & strcmpi(cellstr(releases.horizon), horizon);
    end
    if ~any(ok)
        error('oe:noRelease', 'No dated release matches "%s". Releases seen: %s. Run oe_releases() to list them.', ...
            spec, list_names(names));
    end
    cand = find(ok);
    [~, order] = sortrows([key(cand, :), double(~isPrev(cand))], [-1 -2 -3 -4]);
    pick = cand(order(1));
else
    hit = find(strcmpi(names, spec));
    if isempty(hit)
        error('oe:noRelease', 'Release "%s" not found. Releases seen: %s. Run oe_releases() to list them.', ...
            spec, list_names(names));
    end
    hit = [hit(~isPrev(hit)); hit(isPrev(hit))];   % prefer the current copy
    pick = hit(1);
end

id = char(string(releases.id(pick)));
path = char(string(releases.path(pick)));
if given && ~isempty(id)
    res = struct('Id', id, 'Name', names{pick}, 'Path', path);
else
    res = complete(oe_resource(path), path);
end
fprintf('Release: %s (%s)\n', names{pick}, path);
end

function res = complete(res, path)
% Fill Path and Name from the path asked for if the reply leaves them out.
if ~isstruct(res) || ~isscalar(res)
    error('oe:noRelease', 'No resource found at "%s".', path);
end
if ~isfield(res, 'Path') || isempty(res.Path)
    res.Path = path;
end
if ~isfield(res, 'Name') || isempty(res.Name)
    segs = strsplit(regexprep(path, '/+$', ''), '/');
    res.Name = segs{end};
end
end

function s = list_names(names)
if isempty(names)
    s = '(none)';
elseif numel(names) > 10
    s = [strjoin(names(1:10)', ', ') sprintf(', ... (%d in all)', numel(names))];
else
    s = strjoin(names(:)', ', ');
end
end
