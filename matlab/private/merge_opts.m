function o = merge_opts(opts, defaults, caller)
%MERGE_OPTS Merge a user options struct onto defaults (private helper).
%   O = MERGE_OPTS(OPTS, DEFAULTS, CALLER) copies every field of OPTS onto
%   DEFAULTS. Field names match case-insensitively. An unknown field is an
%   error, so a typo in an option name is caught instead of silently ignored.

o = defaults;
if nargin < 1 || isempty(opts)
    return
end
if ~isstruct(opts) || ~isscalar(opts)
    error('oe:badOption', '%s: options must be a scalar struct, e.g. struct(''name'', value).', caller);
end
valid = fieldnames(defaults);
given = fieldnames(opts);
for i = 1:numel(given)
    k = find(strcmpi(valid, given{i}), 1);
    if isempty(k)
        error('oe:badOption', '%s: unknown option "%s". Valid options: %s.', ...
            caller, given{i}, strjoin(valid', ', '));
    end
    o.(valid{k}) = opts.(given{i});
end
end
